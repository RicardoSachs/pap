# src/pipelines/positions/fms/forwards/run.py
# ---------------------------------------------------------------
# Callable run wrapper for the FMS forwards pipeline.
#
# Two modes, both exposed as callables. The entry-point script
# (scripts/run_fms_forwards.py) is the argparse shell that calls
# these; nothing here does argparse or __main__.
#
# run_full(start_date, end_date, force)
#   1. Assert FMS ingestion enabled on this machine
#   2. Build batch_id from timestamp
#   3. Extract from FMS for start_date..end_date
#   4. Transform to staging shape
#   5. Load staging (idempotent upsert) — its OWN transaction, committed
#      before the fact step so a fact failure can't discard it
#   6. Load dim_portfolio (fms slice) into memory
#   7. Transform to fact shape (portfolio resolution)
#   8. Load fact (idempotent upsert) — second transaction
#   9. Flip any backfill-pending portfolios to active
#  10. Log a reconciliation summary; raise if any fund was left
#      unresolved (unless allow_unresolved=True)
#
# run_from_stg(batch_id)
#   Bypasses FMS entirely (no FMS gate — Postgres only). Reads
#   existing staging rows by batch_id, transforms to fact shape,
#   upserts fact. Used to rebuild fact after fixing a portfolio
#   registration or MTM source without re-hitting FMS.
# ---------------------------------------------------------------

import logging
from datetime import date, datetime, timezone

import pandas as pd

from src.configs.machine_config import assert_fms
from src.db.connection import get_connection
from src.pipelines.positions.fms.forwards import extract, transform, loader

logger = logging.getLogger(__name__)


def run_full(
    start_date: date,
    end_date: date,
    force: bool = False,
    allow_unresolved: bool = False,
) -> None:
    """
    Full pipeline: extract from FMS, load staging, load fact.
    Idempotent - safe to re-run for the same date range.

    Fails loud: if any codigo_fondo can't be resolved to a registered
    dim_portfolio, the resolved rows are still committed (they're valid
    and idempotent) but the run raises afterwards so the operator
    registers the missing fund and re-runs. Pass allow_unresolved=True
    (e.g. for a historical backfill of decommissioned funds) to
    downgrade that to a warning.
    """
    assert_fms()

    batch_id = _new_batch_id()
    logger.info(f"batch_id={batch_id} start={start_date} end={end_date} force={force}")

    raw_df = extract.extract(start_date, end_date, force=force)
    extracted = len(raw_df)
    if raw_df.empty:
        logger.info("no rows extracted, nothing to load")
        return

    stg_df = transform.transform_for_staging(raw_df, batch_id)
    _log_null_counts(stg_df, "staging")

    # Transaction 1: staging commits on its own. A later fact failure must NOT
    # discard the staged rows — otherwise run_from_stg has nothing to rebuild
    # from and you'd have to re-hit FMS just to retry the fact step.
    with get_connection() as conn:
        staged = loader.load_staging(conn, stg_df)

    # Transaction 2: fact. If this rolls back, staging above stays committed.
    with get_connection() as conn:
        portfolios = _load_portfolios(conn)
        unresolved = _unresolved_funds(stg_df, portfolios)
        fact_df = transform.transform_for_fact(stg_df, portfolios)
        _log_null_counts(fact_df, "fact")
        loaded = loader.load_fact(conn, fact_df)

        flipped = _flip_backfill_pending_to_active(conn, fact_df)

    _log_reconciliation(extracted, staged, loaded, unresolved, flipped)

    if unresolved and not allow_unresolved:
        raise RuntimeError(
            f"{len(unresolved)} FMS fund(s) unresolved to a dim_portfolio and "
            f"dropped from fact: {unresolved}. Register them in dim_portfolio "
            f"(seeds/portfolios.csv) and re-run — the upsert backfills the gap. "
            f"Pass allow_unresolved=True to suppress this."
        )


def run_from_stg(batch_id: str) -> None:
    """
    Rebuild fact from an existing staging batch, without re-hitting FMS.

    No FMS gate: this touches only Postgres, so it runs on any machine
    with DB access. Note the staging PK is (codigo_fondo, codigo_sbs,
    date) and does NOT include batch_id, and load_staging overwrites
    batch_id on conflict — so a grain row always carries its most recent
    batch_id. This resolves the common "rebuild what I just loaded" case;
    an older batch_id whose grain was later re-staged returns no rows.
    """
    logger.info(f"from-stg mode: batch_id={batch_id}")

    with get_connection() as conn:
        stg_df = _read_staging_by_batch(conn, batch_id)
        if stg_df.empty:
            logger.warning(f"no rows in stg_positions_fms_forwards for batch_id={batch_id}")
            return

        portfolios = _load_portfolios(conn)
        fact_df = transform.transform_for_fact(stg_df, portfolios)
        loader.load_fact(conn, fact_df)

        _flip_backfill_pending_to_active(conn, fact_df)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _new_batch_id() -> str:
    return "fms_forwards_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _unresolved_funds(stg_df: pd.DataFrame, portfolios: pd.DataFrame) -> list[str]:
    """
    Return the sorted codigo_fondo values present in staging that have no
    matching dim_portfolio (source='fms') row — i.e. the funds
    transform_for_fact will drop.
    """
    if stg_df.empty:
        return []
    known = set(portfolios["procode"])
    present = set(stg_df["codigo_fondo"].dropna().unique())
    return sorted(present - known)


def _log_reconciliation(
    extracted: int,
    staged: int,
    loaded: int,
    unresolved: list[str],
    flipped: int,
) -> None:
    """One-line run summary so silent under-population is visible."""
    logger.info(
        f"reconciliation: extracted={extracted} staged={staged} "
        f"fact_loaded={loaded} unresolved_funds={len(unresolved)} "
        f"portfolios_activated={flipped}"
    )
    if unresolved:
        logger.warning(f"unresolved codigo_fondo dropped from fact: {unresolved}")


def _log_null_counts(df: pd.DataFrame, stage: str) -> None:
    """
    Log any columns carrying nulls at a stage, so a source-origin null (e.g. a
    stale FMS TipoCambioSpot) is visible before it trips a NOT NULL insert.
    Silent when nothing is null.
    """
    if df.empty:
        return
    nulls = {c: int(df[c].isna().sum()) for c in df.columns if df[c].isna().any()}
    if nulls:
        logger.info(f"null counts [{stage}]: {nulls}")


def _load_portfolios(conn) -> pd.DataFrame:
    """Load dim_portfolio (source='fms') into a DataFrame."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT procode, portfolio_id FROM dim_portfolio WHERE source = 'fms'"
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["procode", "portfolio_id"])
    logger.info(f"loaded {len(df)} FMS portfolios from dim_portfolio")
    return df


def _read_staging_by_batch(conn, batch_id: str) -> pd.DataFrame:
    """Read stg_positions_fms_forwards rows for a given batch_id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT batch_id, id_secuencial_fecha_proceso, date,
                   codigo_fondo, codigo_sbs,
                   codigo_iso_moneda_nocional, codigo_iso_moneda_contraparte,
                   valor_nocional, tipo_cambio_spot, nocional_soles,
                   moneda_compra, moneda_venta,
                   raw_payload
              FROM stg_positions_fms_forwards
             WHERE batch_id = %s
            """,
            (batch_id,),
        )
        cols = [c.name for c in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame.from_records(rows, columns=cols)
    logger.info(f"read {len(df)} rows from stg_positions_fms_forwards for batch_id={batch_id}")
    return df


def _flip_backfill_pending_to_active(conn, fact_df: pd.DataFrame) -> int:
    """
    Any FMS portfolio in status 'backfill-pending' that produced at
    least one fact row in this run gets promoted to 'active'. Returns
    the number of portfolios flipped.
    """
    if fact_df.empty:
        return 0
    portfolio_ids = fact_df["portfolio_id"].unique().tolist()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dim_portfolio
               SET status = 'active', updated_at = CURRENT_TIMESTAMP
             WHERE portfolio_id = ANY(%s)
               AND source = 'fms'
               AND status = 'backfill-pending'
            """,
            (portfolio_ids,),
        )
        flipped = cur.rowcount
    if flipped:
        logger.info(f"flipped {flipped} FMS portfolios from backfill-pending to active")
    return flipped
