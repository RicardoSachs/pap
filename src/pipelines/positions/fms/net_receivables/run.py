# src/pipelines/positions/fms/net_receivables/run.py
# ---------------------------------------------------------------
# Callable run wrapper for the FMS net-receivables pipeline.
#
# Same two-mode shape as the other feeds; the only feed-specific parts are
# the imports, the staging read, and that extract loops per business day
# (point-in-time). Generic portfolio-resolution / logging helpers come from
# src/pipelines/positions/fms/_common.py.
#
# run_full(start_date, end_date, force)
#   extract (per-day loop) -> stage (own tx) -> fact (2nd tx) -> flip ->
#   reconciliation; raises if any fund was left unresolved (unless
#   allow_unresolved=True).
#
# run_from_stg(batch_id)
#   Rebuild fact from an existing staging batch, Postgres only.
#
# Point-in-time note: a past as-of day is recomputed from the current
# CuentaCobrarPagar, so re-running restates it (loader upserts DO UPDATE).
# For daily ops, run forward one day; optionally re-run a short trailing
# window so late corrections settle before the period stabilizes.
# ---------------------------------------------------------------

import logging
from datetime import date

import pandas as pd

from src.configs.machine_config import assert_fms
from src.db.connection import get_connection
from src.pipelines.positions.fms.net_receivables import extract, transform, loader
from src.pipelines.positions.fms._common import (
    new_batch_id,
    load_portfolios,
    unresolved_funds,
    flip_backfill_pending_to_active,
    log_reconciliation,
    log_null_counts,
)

logger = logging.getLogger(__name__)


def run_full(
    start_date: date,
    end_date: date,
    force: bool = False,
    allow_unresolved: bool = False,
) -> None:
    """
    Full pipeline: extract per business day from FMS, load staging, load fact.
    Idempotent - safe to re-run for the same date range (restates).

    Fails loud on unresolved codigo_fondo (unless allow_unresolved=True):
    the resolved rows still commit, but the run raises so the operator
    registers the missing fund and re-runs.
    """
    assert_fms()

    batch_id = new_batch_id("fms_net_receivables")
    logger.info(f"batch_id={batch_id} start={start_date} end={end_date} force={force}")

    raw_df = extract.extract(start_date, end_date, force=force)
    extracted = len(raw_df)
    if raw_df.empty:
        logger.info("no rows extracted, nothing to load")
        return

    stg_df = transform.transform_for_staging(raw_df, batch_id)
    log_null_counts(stg_df, "staging")

    # Transaction 1: staging commits on its own so a later fact failure can't
    # discard it (run_from_stg can then rebuild without re-hitting FMS).
    with get_connection() as conn:
        staged = loader.load_staging(conn, stg_df)

    # Transaction 2: fact.
    with get_connection() as conn:
        portfolios = load_portfolios(conn)
        unresolved = unresolved_funds(stg_df, portfolios)
        fact_df = transform.transform_for_fact(stg_df, portfolios)
        log_null_counts(fact_df, "fact")
        loaded = loader.load_fact(conn, fact_df)

        flipped = flip_backfill_pending_to_active(conn, fact_df)

    log_reconciliation(extracted, staged, loaded, unresolved, flipped)

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
    No FMS gate: touches only Postgres. Note the staging PK is
    (codigo_fondo, codigo_iso_moneda, date) and excludes batch_id, so a grain
    row carries its most recent batch_id — this rebuilds the latest load.
    """
    logger.info(f"from-stg mode: batch_id={batch_id}")

    with get_connection() as conn:
        stg_df = _read_staging_by_batch(conn, batch_id)
        if stg_df.empty:
            logger.warning(f"no rows in stg_positions_fms_net_receivables for batch_id={batch_id}")
            return

        portfolios = load_portfolios(conn)
        fact_df = transform.transform_for_fact(stg_df, portfolios)
        loader.load_fact(conn, fact_df)

        flip_backfill_pending_to_active(conn, fact_df)


# ---------------------------------------------------------------
# Feed-specific helper (staging table + columns)
# ---------------------------------------------------------------

def _read_staging_by_batch(conn, batch_id: str) -> pd.DataFrame:
    """Read stg_positions_fms_net_receivables rows for a given batch_id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT batch_id, date,
                   codigo_fondo, codigo_iso_moneda,
                   monto_cobrar, monto_pagar,
                   raw_payload
              FROM stg_positions_fms_net_receivables
             WHERE batch_id = %s
            """,
            (batch_id,),
        )
        cols = [c.name for c in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame.from_records(rows, columns=cols)
    logger.info(f"read {len(df)} rows from stg_positions_fms_net_receivables for batch_id={batch_id}")
    return df
