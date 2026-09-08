# src/pipelines/positions/fms/net_receivables/loader.py
# ---------------------------------------------------------------
# Two writers, each idempotent via ON CONFLICT DO UPDATE.
#
# load_staging(conn, stg_df)
#   Writes to stg_positions_fms_net_receivables. PK is
#   (codigo_fondo, codigo_iso_moneda, date).
#
# load_fact(conn, fact_df)
#   Writes to fact_positions_net_receivables. PK is
#   (portfolio_id, codigo_iso_moneda, date, source). Re-running a past
#   as-of day restates it (point-in-time recomputation).
#
# The row-by-row upsert primitives and validators are shared across feeds
# in src/pipelines/positions/fms/_common.py; only the per-feed SQL and
# column lists live here. Both accept an already-open connection; empty
# DataFrames are no-ops.
# ---------------------------------------------------------------

import logging

import pandas as pd
from psycopg import Connection

from src.pipelines.positions.fms._common import (
    validate_columns,
    validate_not_null,
    execute_row_by_row,
)

logger = logging.getLogger(__name__)


STG_COLUMNS = [
    "batch_id", "date",
    "codigo_fondo", "codigo_iso_moneda",
    "monto_cobrar", "monto_pagar",
    "monto_cobrar_soles", "monto_pagar_soles", "tipo_cambio",
    "raw_payload",
]

STG_UPSERT = f"""
INSERT INTO stg_positions_fms_net_receivables ({", ".join(STG_COLUMNS)})
VALUES ({", ".join(["%s"] * len(STG_COLUMNS))})
ON CONFLICT (codigo_fondo, codigo_iso_moneda, date) DO UPDATE SET
    batch_id           = EXCLUDED.batch_id,
    loaded_at          = CURRENT_TIMESTAMP,
    monto_cobrar       = EXCLUDED.monto_cobrar,
    monto_pagar        = EXCLUDED.monto_pagar,
    monto_cobrar_soles = EXCLUDED.monto_cobrar_soles,
    monto_pagar_soles  = EXCLUDED.monto_pagar_soles,
    tipo_cambio        = EXCLUDED.tipo_cambio,
    raw_payload        = EXCLUDED.raw_payload
"""


FACT_COLUMNS = [
    "portfolio_id", "codigo_iso_moneda", "date", "source",
    "monto_cobrar", "monto_pagar",
    "monto_cobrar_soles", "monto_pagar_soles", "tipo_cambio",
]

# The original-currency legs are NOT NULL (see 31_...sql): the query's
# CASE ... ELSE 0 guarantees both are present (0 if a fund has only one side),
# so a null there is a real data problem — caught before the row-by-row INSERT
# so the error names the column + currency. The soles legs and tipo_cambio are
# NULLABLE by design: NULL = missing FMS FX rate for a non-PEN currency, which
# must land (fail-visible via log_null_counts) rather than abort the load.
FACT_NOT_NULL_COLUMNS = [
    "portfolio_id", "codigo_iso_moneda", "date", "source",
    "monto_cobrar", "monto_pagar",
]

FACT_UPSERT = f"""
INSERT INTO fact_positions_net_receivables ({", ".join(FACT_COLUMNS)})
VALUES ({", ".join(["%s"] * len(FACT_COLUMNS))})
ON CONFLICT (portfolio_id, codigo_iso_moneda, date, source) DO UPDATE SET
    monto_cobrar       = EXCLUDED.monto_cobrar,
    monto_pagar        = EXCLUDED.monto_pagar,
    monto_cobrar_soles = EXCLUDED.monto_cobrar_soles,
    monto_pagar_soles  = EXCLUDED.monto_pagar_soles,
    tipo_cambio        = EXCLUDED.tipo_cambio,
    loaded_at          = CURRENT_TIMESTAMP
"""


def load_staging(conn: Connection, stg_df: pd.DataFrame) -> int:
    """Upsert into stg_positions_fms_net_receivables. Returns row count."""
    if stg_df.empty:
        logger.info("load_staging: empty DataFrame, nothing to write")
        return 0

    validate_columns(stg_df, STG_COLUMNS)
    n = execute_row_by_row(conn, STG_UPSERT, stg_df, STG_COLUMNS, jsonb_column="raw_payload")
    logger.info(f"load_staging: upserted {n} rows into stg_positions_fms_net_receivables")
    return n


def load_fact(conn: Connection, fact_df: pd.DataFrame) -> int:
    """Upsert into fact_positions_net_receivables. Returns row count."""
    if fact_df.empty:
        logger.info("load_fact: empty DataFrame, nothing to write")
        return 0

    validate_columns(fact_df, FACT_COLUMNS)
    validate_not_null(fact_df, FACT_NOT_NULL_COLUMNS,
                      table="fact_positions_net_receivables", id_col="codigo_iso_moneda")
    n = execute_row_by_row(conn, FACT_UPSERT, fact_df, FACT_COLUMNS)
    logger.info(f"load_fact: upserted {n} rows into fact_positions_net_receivables")
    return n
