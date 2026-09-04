# src/pipelines/positions/fms/holdings/loader.py
# ---------------------------------------------------------------
# Writers for the holdings feed: one staging table and three fact tables
# (securities, deposits, portfolio_valuation), each idempotent via
# ON CONFLICT DO UPDATE.
#
# Row-by-row upsert primitives + validators are shared in
# src/pipelines/positions/fms/_common.py. Fact column lists are imported from
# transform.py so the insert contract can't drift from what the transforms
# produce. The many-column UPSERTs are built by _build_upsert to stay correct.
# ---------------------------------------------------------------

import logging

import pandas as pd
from psycopg import Connection

from src.pipelines.positions.fms._common import (
    validate_columns,
    validate_not_null,
    execute_row_by_row,
)
from src.pipelines.positions.fms.holdings.transform import (
    SECURITIES_FACT_COLUMNS,
    DEPOSITS_FACT_COLUMNS,
    VALUATION_FACT_COLUMNS,
)

logger = logging.getLogger(__name__)


def _build_upsert(table: str, columns: list[str], conflict_cols: list[str]) -> str:
    """INSERT … ON CONFLICT (pk) DO UPDATE SET (non-pk cols) + loaded_at."""
    placeholders = ", ".join(["%s"] * len(columns))
    set_cols = [c for c in columns if c not in conflict_cols]
    set_clause = ",\n    ".join(f"{c} = EXCLUDED.{c}" for c in set_cols)
    set_clause += ",\n    loaded_at = CURRENT_TIMESTAMP"
    return (
        f"INSERT INTO {table} ({', '.join(columns)})\n"
        f"VALUES ({placeholders})\n"
        f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET\n    {set_clause}"
    )


# ---- staging --------------------------------------------------

STG_COLUMNS = [
    "batch_id", "id_secuencial_fecha_idi", "date",
    "codigo_fondo", "codigo_sbs", "id_orden_inversion",
    "codigo_iso_moneda", "ind_clase", "importe_pen", "valor_cuota", "valor_cartera",
    "cantidad", "precio_pen", "cantidad_anterior", "precio_anterior_pen",
    "importe_anterior_pen", "monto_intereses_vencimiento_cupon", "monto_ordenes_renta",
    "monto_acciones_liberadas", "monto_dividendos", "monto_rescates",
    "tasa", "dias_vigencia", "id_secuencial_fecha_vencimiento",
    "raw_payload",
]
STG_CONFLICT = ["codigo_fondo", "codigo_sbs", "id_orden_inversion", "date"]
STG_UPSERT = _build_upsert("stg_positions_fms_holdings", STG_COLUMNS, STG_CONFLICT)


# ---- fact: securities -----------------------------------------

SECURITIES_CONFLICT = ["portfolio_id", "security_entity_id", "date", "source"]
SECURITIES_NOT_NULL = ["portfolio_id", "security_entity_id", "date", "source", "importe_pen"]
SECURITIES_UPSERT = _build_upsert("fact_positions_securities", SECURITIES_FACT_COLUMNS, SECURITIES_CONFLICT)


# ---- fact: deposits -------------------------------------------

DEPOSITS_CONFLICT = ["portfolio_id", "id_orden_inversion", "date", "source"]
DEPOSITS_NOT_NULL = ["portfolio_id", "id_orden_inversion", "date", "source",
                     "codigo_iso_moneda", "importe_pen"]
DEPOSITS_UPSERT = _build_upsert("fact_positions_deposits", DEPOSITS_FACT_COLUMNS, DEPOSITS_CONFLICT)


# ---- fact: portfolio valuation --------------------------------

VALUATION_CONFLICT = ["portfolio_id", "date", "source"]
VALUATION_NOT_NULL = ["portfolio_id", "date", "source", "valor_cuota", "valor_cartera"]
VALUATION_UPSERT = _build_upsert("fact_portfolio_valuation", VALUATION_FACT_COLUMNS, VALUATION_CONFLICT)


# ---- load functions -------------------------------------------

def load_staging(conn: Connection, stg_df: pd.DataFrame) -> int:
    if stg_df.empty:
        logger.info("load_staging: empty DataFrame, nothing to write")
        return 0
    validate_columns(stg_df, STG_COLUMNS)
    n = execute_row_by_row(conn, STG_UPSERT, stg_df, STG_COLUMNS, jsonb_column="raw_payload")
    logger.info(f"load_staging: upserted {n} rows into stg_positions_fms_holdings")
    return n


def load_fact_securities(conn: Connection, fact_df: pd.DataFrame) -> int:
    if fact_df.empty:
        logger.info("load_fact_securities: empty DataFrame, nothing to write")
        return 0
    validate_columns(fact_df, SECURITIES_FACT_COLUMNS)
    validate_not_null(fact_df, SECURITIES_NOT_NULL,
                      table="fact_positions_securities", id_col="security_entity_id")
    n = execute_row_by_row(conn, SECURITIES_UPSERT, fact_df, SECURITIES_FACT_COLUMNS)
    logger.info(f"load_fact_securities: upserted {n} rows into fact_positions_securities")
    return n


def load_fact_deposits(conn: Connection, fact_df: pd.DataFrame) -> int:
    if fact_df.empty:
        logger.info("load_fact_deposits: empty DataFrame, nothing to write")
        return 0
    validate_columns(fact_df, DEPOSITS_FACT_COLUMNS)
    validate_not_null(fact_df, DEPOSITS_NOT_NULL,
                      table="fact_positions_deposits", id_col="id_orden_inversion")
    n = execute_row_by_row(conn, DEPOSITS_UPSERT, fact_df, DEPOSITS_FACT_COLUMNS)
    logger.info(f"load_fact_deposits: upserted {n} rows into fact_positions_deposits")
    return n


def load_fact_valuation(conn: Connection, fact_df: pd.DataFrame) -> int:
    if fact_df.empty:
        logger.info("load_fact_valuation: empty DataFrame, nothing to write")
        return 0
    validate_columns(fact_df, VALUATION_FACT_COLUMNS)
    validate_not_null(fact_df, VALUATION_NOT_NULL,
                      table="fact_portfolio_valuation", id_col="portfolio_id")
    n = execute_row_by_row(conn, VALUATION_UPSERT, fact_df, VALUATION_FACT_COLUMNS)
    logger.info(f"load_fact_valuation: upserted {n} rows into fact_portfolio_valuation")
    return n
