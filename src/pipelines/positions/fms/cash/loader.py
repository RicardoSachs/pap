# src/pipelines/positions/fms/cash/loader.py
# ---------------------------------------------------------------
# Two writers, each idempotent via ON CONFLICT DO UPDATE.
#
# load_staging(conn, stg_df)
#   Writes to stg_positions_fms_cash. PK is
#   (codigo_fondo, codigo_institucion, codigo_iso_moneda, date).
#   raw_payload is serialized via psycopg's Jsonb adapter.
#
# load_fact(conn, fact_df)
#   Writes to fact_positions_cash. PK is
#   (portfolio_id, codigo_institucion, codigo_iso_moneda, date, source).
#
# The row-by-row upsert primitives and validators are shared across
# feeds in src/pipelines/positions/fms/_common.py; only the per-feed
# SQL and column lists live here. Both accept an already-open
# connection; empty DataFrames are no-ops.
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
    "batch_id", "id_secuencial_fecha_reporte", "date",
    "codigo_fondo", "codigo_institucion", "codigo_iso_moneda",
    "codigo_instrumento",
    "nombre_institucion",
    "saldo_contable", "monto_total_soles",
    "tasa_interes", "interes_acumulado",
    "raw_payload",
]

STG_UPSERT = f"""
INSERT INTO stg_positions_fms_cash ({", ".join(STG_COLUMNS)})
VALUES ({", ".join(["%s"] * len(STG_COLUMNS))})
ON CONFLICT (codigo_fondo, codigo_institucion, codigo_iso_moneda, codigo_instrumento, date) DO UPDATE SET
    batch_id                    = EXCLUDED.batch_id,
    loaded_at                   = CURRENT_TIMESTAMP,
    id_secuencial_fecha_reporte = EXCLUDED.id_secuencial_fecha_reporte,
    nombre_institucion          = EXCLUDED.nombre_institucion,
    saldo_contable              = EXCLUDED.saldo_contable,
    monto_total_soles           = EXCLUDED.monto_total_soles,
    tasa_interes                = EXCLUDED.tasa_interes,
    interes_acumulado           = EXCLUDED.interes_acumulado,
    raw_payload                 = EXCLUDED.raw_payload
"""


FACT_COLUMNS = [
    "portfolio_id", "codigo_institucion", "codigo_iso_moneda",
    "codigo_instrumento", "date", "source",
    "nombre_institucion",
    "saldo_contable", "monto_total_soles",
    "tasa_interes", "interes_acumulado",
]

# The NOT NULL columns of fact_positions_cash (see 29_fact_positions_cash.sql).
# nombre_institucion / tasa_interes / interes_acumulado are nullable. A null in
# a NOT NULL column is a data problem (e.g. a source row missing SaldoContable,
# MontoTotalSoles, or the CodigoInstrumento grain key) — caught before the
# row-by-row INSERT so the error names the column + currency instead of an
# opaque psycopg NotNullViolation.
FACT_NOT_NULL_COLUMNS = [
    "portfolio_id", "codigo_institucion", "codigo_iso_moneda",
    "codigo_instrumento", "date", "source",
    "saldo_contable", "monto_total_soles",
]

FACT_UPSERT = f"""
INSERT INTO fact_positions_cash ({", ".join(FACT_COLUMNS)})
VALUES ({", ".join(["%s"] * len(FACT_COLUMNS))})
ON CONFLICT (portfolio_id, codigo_institucion, codigo_iso_moneda, codigo_instrumento, date, source) DO UPDATE SET
    nombre_institucion = EXCLUDED.nombre_institucion,
    saldo_contable     = EXCLUDED.saldo_contable,
    monto_total_soles  = EXCLUDED.monto_total_soles,
    tasa_interes       = EXCLUDED.tasa_interes,
    interes_acumulado  = EXCLUDED.interes_acumulado,
    loaded_at          = CURRENT_TIMESTAMP
"""


def load_staging(conn: Connection, stg_df: pd.DataFrame) -> int:
    """Upsert into stg_positions_fms_cash. Returns row count."""
    if stg_df.empty:
        logger.info("load_staging: empty DataFrame, nothing to write")
        return 0

    validate_columns(stg_df, STG_COLUMNS)
    n = execute_row_by_row(conn, STG_UPSERT, stg_df, STG_COLUMNS, jsonb_column="raw_payload")
    logger.info(f"load_staging: upserted {n} rows into stg_positions_fms_cash")
    return n


def load_fact(conn: Connection, fact_df: pd.DataFrame) -> int:
    """Upsert into fact_positions_cash. Returns row count."""
    if fact_df.empty:
        logger.info("load_fact: empty DataFrame, nothing to write")
        return 0

    validate_columns(fact_df, FACT_COLUMNS)
    validate_not_null(fact_df, FACT_NOT_NULL_COLUMNS,
                      table="fact_positions_cash", id_col="codigo_iso_moneda")
    n = execute_row_by_row(conn, FACT_UPSERT, fact_df, FACT_COLUMNS)
    logger.info(f"load_fact: upserted {n} rows into fact_positions_cash")
    return n
