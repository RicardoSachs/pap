# src/pipelines/positions/fms/cash/loader.py
# ---------------------------------------------------------------
# Two writers, each idempotent via ON CONFLICT DO UPDATE.
#
# load_staging(conn, stg_df)
#   Writes to stg_positions_fms_cash. PK is
#   (codigo_fondo, codigo_iso_moneda, date). raw_payload is
#   serialized via psycopg's Jsonb adapter.
#
# load_fact(conn, fact_df)
#   Writes to fact_positions_cash. PK is
#   (portfolio_id, codigo_iso_moneda, date, source).
#
# Both iterate the DataFrame row-by-row and call cur.execute per row
# (project-wide convention; never trips Postgres's 65535 parameter
# cap, simpler to debug, per-row errors point at the offending row).
# Both accept an already-open connection; empty DataFrames are no-ops.
# ---------------------------------------------------------------

import logging

import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)


STG_COLUMNS = [
    "batch_id", "id_secuencial_fecha_reporte", "date",
    "codigo_fondo", "codigo_institucion", "codigo_iso_moneda",
    "nombre_institucion",
    "saldo_contable", "monto_total_soles",
    "tasa_interes", "interes_acumulado",
    "raw_payload",
]

STG_UPSERT = f"""
INSERT INTO stg_positions_fms_cash ({", ".join(STG_COLUMNS)})
VALUES ({", ".join(["%s"] * len(STG_COLUMNS))})
ON CONFLICT (codigo_fondo, codigo_institucion, codigo_iso_moneda, date) DO UPDATE SET
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
    "portfolio_id", "codigo_institucion", "codigo_iso_moneda", "date", "source",
    "nombre_institucion",
    "saldo_contable", "monto_total_soles",
    "tasa_interes", "interes_acumulado",
]

# The NOT NULL columns of fact_positions_cash (see 29_fact_positions_cash.sql).
# nombre_institucion / tasa_interes / interes_acumulado are nullable. A null in
# a NOT NULL column is a data problem (e.g. a source row missing SaldoContable
# or MontoTotalSoles) — caught before the row-by-row INSERT so the error names
# the column + currency instead of an opaque psycopg NotNullViolation.
FACT_NOT_NULL_COLUMNS = [
    "portfolio_id", "codigo_institucion", "codigo_iso_moneda", "date", "source",
    "saldo_contable", "monto_total_soles",
]

FACT_UPSERT = f"""
INSERT INTO fact_positions_cash ({", ".join(FACT_COLUMNS)})
VALUES ({", ".join(["%s"] * len(FACT_COLUMNS))})
ON CONFLICT (portfolio_id, codigo_institucion, codigo_iso_moneda, date, source) DO UPDATE SET
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

    _validate_columns(stg_df, STG_COLUMNS)
    n = _execute_row_by_row(conn, STG_UPSERT, stg_df, STG_COLUMNS, jsonb_column="raw_payload")
    logger.info(f"load_staging: upserted {n} rows into stg_positions_fms_cash")
    return n


def load_fact(conn: Connection, fact_df: pd.DataFrame) -> int:
    """Upsert into fact_positions_cash. Returns row count."""
    if fact_df.empty:
        logger.info("load_fact: empty DataFrame, nothing to write")
        return 0

    _validate_columns(fact_df, FACT_COLUMNS)
    _validate_not_null(fact_df, FACT_NOT_NULL_COLUMNS)
    n = _execute_row_by_row(conn, FACT_UPSERT, fact_df, FACT_COLUMNS)
    logger.info(f"load_fact: upserted {n} rows into fact_positions_cash")
    return n


def _validate_columns(df: pd.DataFrame, expected: list[str]) -> None:
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing expected columns: {missing}")


def _validate_not_null(df: pd.DataFrame, columns: list[str]) -> None:
    """
    Raise a clear error if any NOT NULL fact column contains nulls, naming the
    column and a sample of offending (currency) values — so a source-origin
    null (e.g. a row missing SaldoContable/MontoTotalSoles) fails loudly here
    instead of as an opaque psycopg NotNullViolation partway through the row loop.
    """
    for col in columns:
        null_mask = df[col].isna()
        if null_mask.any():
            n = int(null_mask.sum())
            sample = df.loc[null_mask, "codigo_iso_moneda"].head(5).tolist()
            raise ValueError(
                f"fact_positions_cash: {n} row(s) have NULL {col} (NOT NULL). "
                f"Sample codigo_iso_moneda: {sample}"
            )


def _execute_row_by_row(
    conn: Connection,
    sql: str,
    df: pd.DataFrame,
    columns: list[str],
    jsonb_column: str = None,
) -> int:
    """
    Iterate the DataFrame row-by-row and execute one INSERT per row.
    NaN/NaT converted to None. jsonb_column values wrapped in Jsonb.
    """
    with conn.cursor() as cur:
        for i, row in df.iterrows():
            params = _row_to_params(row, columns, jsonb_column)
            try:
                cur.execute(sql, params)
            except Exception:
                logger.error(f"insert failed for DataFrame row {i}: {dict(row[columns])}")
                raise
    return len(df)


def _row_to_params(row: pd.Series, columns: list[str], jsonb_column: str = None) -> tuple:
    """Convert a DataFrame row to a psycopg-ready parameter tuple."""
    out = []
    for col in columns:
        v = row[col]
        if pd.isna(v):
            out.append(None)
        elif col == jsonb_column:
            out.append(Jsonb(v))
        else:
            out.append(v.item() if hasattr(v, "item") else v)
    return tuple(out)
