# src/pipelines/positions/fms/holdings/run.py
# ---------------------------------------------------------------
# Callable run wrapper for the FMS holdings feed.
#
# One extract (set-based range) -> one staging table -> THREE facts:
# securities (entity-resolved), deposits, and portfolio_valuation.
#
# run_full(start_date, end_date, force)
#   1. Assert FMS enabled
#   2. Extract (IDI valorization), transform to staging
#   3. Load staging (own transaction)
#   4. Load dim_portfolio + the sbs->entity map into memory
#   5. Shape + load the three facts, flip backfill-pending portfolios
#   6. Reconciliation; raise on unresolved funds/securities (unless allowed)
#
# run_from_stg(batch_id): rebuild the three facts from a staging batch.
#
# Securities are entity-resolved (codigo_sbs -> dim_entity via
# dim_entity_identifiers, id_type='codigo_sbs' / source='sbs'); unresolved
# securities are dropped and fail loud.
# NOTE: on first runs many held securities may be unregistered — if hand-
# registration is impractical, a follow-up can self-register skeletons (as the
# SBS registry does) via get_or_create_entity_id.
# ---------------------------------------------------------------

import logging
from datetime import date

import pandas as pd

from src.configs.machine_config import assert_fms
from src.db.connection import get_connection
from src.pipelines.positions.fms.holdings import extract, transform, loader
from src.pipelines.positions.fms._common import (
    new_batch_id,
    load_portfolios,
    unresolved_funds,
    flip_backfill_pending_to_active,
    log_null_counts,
)

logger = logging.getLogger(__name__)


def run_full(
    start_date: date,
    end_date: date,
    force: bool = False,
    allow_unresolved: bool = False,
) -> None:
    """Extract holdings, load staging, then the three facts. Idempotent."""
    assert_fms()

    batch_id = new_batch_id("fms_holdings")
    logger.info(f"batch_id={batch_id} start={start_date} end={end_date} force={force}")

    raw_df = extract.extract(start_date, end_date, force=force)
    extracted = len(raw_df)
    if raw_df.empty:
        logger.info("no rows extracted, nothing to load")
        return

    stg_df = transform.transform_for_staging(raw_df, batch_id)
    log_null_counts(stg_df, "staging")

    with get_connection() as conn:
        staged = loader.load_staging(conn, stg_df)

    with get_connection() as conn:
        portfolios = load_portfolios(conn)
        securities = _load_securities(conn)

        unres_funds = unresolved_funds(stg_df, portfolios)
        unres_secs = _unresolved_securities(stg_df, securities)

        sec_df = transform.transform_for_fact_securities(stg_df, portfolios, securities)
        dep_df = transform.transform_for_fact_deposits(stg_df, portfolios)
        val_df = transform.transform_for_fact_valuation(stg_df, portfolios)

        n_sec = loader.load_fact_securities(conn, sec_df)
        n_dep = loader.load_fact_deposits(conn, dep_df)
        n_val = loader.load_fact_valuation(conn, val_df)

        flipped = flip_backfill_pending_to_active(conn, val_df)

    _log_reconciliation(extracted, staged, n_sec, n_dep, n_val,
                        unres_funds, unres_secs, flipped)

    if (unres_funds or unres_secs) and not allow_unresolved:
        raise RuntimeError(
            f"unresolved on holdings load — funds: {unres_funds}; "
            f"securities (codigo_sbs): {unres_secs[:10]}{'…' if len(unres_secs) > 10 else ''}. "
            f"Register them and re-run, or pass allow_unresolved=True."
        )


def run_from_stg(batch_id: str) -> None:
    """Rebuild the three facts from an existing staging batch (Postgres only)."""
    logger.info(f"from-stg mode: batch_id={batch_id}")

    with get_connection() as conn:
        stg_df = _read_staging_by_batch(conn, batch_id)
        if stg_df.empty:
            logger.warning(f"no rows in stg_positions_fms_holdings for batch_id={batch_id}")
            return

        portfolios = load_portfolios(conn)
        securities = _load_securities(conn)

        loader.load_fact_securities(conn, transform.transform_for_fact_securities(stg_df, portfolios, securities))
        loader.load_fact_deposits(conn, transform.transform_for_fact_deposits(stg_df, portfolios))
        val_df = transform.transform_for_fact_valuation(stg_df, portfolios)
        loader.load_fact_valuation(conn, val_df)

        flip_backfill_pending_to_active(conn, val_df)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _load_securities(conn) -> pd.DataFrame:
    """Load the sbs -> entity map: (codigo_sbs, security_entity_id)."""
    with conn.cursor() as cur:
        cur.execute(
            # Aliases must match the DataFrame columns below: psycopg dict
            # rows are matched by KEY when building the frame, so mismatched
            # names silently yield all-NaN columns.
            "SELECT id_value AS codigo_sbs, entity_id AS security_entity_id "
            "FROM dim_entity_identifiers "
            "WHERE id_type = 'codigo_sbs' AND source = 'sbs'"
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["codigo_sbs", "security_entity_id"])
    logger.info(f"loaded {len(df)} sbs->entity identifiers from dim_entity_identifiers")
    return df


def _unresolved_securities(stg_df: pd.DataFrame, securities: pd.DataFrame) -> list[str]:
    """codigo_sbs on security (non-deposit) rows not present in the sbs->entity map."""
    if stg_df.empty:
        return []
    sec_rows = stg_df[~stg_df["codigo_sbs"].map(transform.is_deposit)]
    known = set(securities["codigo_sbs"])
    present = set(sec_rows["codigo_sbs"].dropna().unique())
    return sorted(present - known)


def _log_reconciliation(extracted, staged, n_sec, n_dep, n_val,
                        unres_funds, unres_secs, flipped) -> None:
    logger.info(
        f"reconciliation: extracted={extracted} staged={staged} "
        f"securities={n_sec} deposits={n_dep} valuation={n_val} "
        f"unresolved_funds={len(unres_funds)} unresolved_securities={len(unres_secs)} "
        f"portfolios_activated={flipped}"
    )
    if unres_funds:
        logger.warning(f"unresolved codigo_fondo: {unres_funds}")
    if unres_secs:
        logger.warning(f"unresolved codigo_sbs ({len(unres_secs)}): {unres_secs[:20]}")


def _read_staging_by_batch(conn, batch_id: str) -> pd.DataFrame:
    """Read stg_positions_fms_holdings rows for a given batch_id."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(loader.STG_COLUMNS)} "
            f"FROM stg_positions_fms_holdings WHERE batch_id = %s",
            (batch_id,),
        )
        cols = [c.name for c in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame.from_records(rows, columns=cols)
    logger.info(f"read {len(df)} rows from stg_positions_fms_holdings for batch_id={batch_id}")
    return df
