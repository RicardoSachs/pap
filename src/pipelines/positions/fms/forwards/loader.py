# src/pipelines/positions/fms/forwards/loader.py
# ---------------------------------------------------------------
# Two writers, each idempotent via ON CONFLICT DO UPDATE.
#
# load_staging(conn, stg_df)
#   Writes to stg_positions_fms_forwards. PK is
#   (codigo_fondo, codigo_sbs, date). Rerunning the same batch
#   replaces existing rows for that batch. raw_payload is
#   serialized to JSON via psycopg's Jsonb adapter.
#
# load_fact(conn, fact_df)
#   Writes to fact_positions_forwards. PK is
#   (portfolio_id, codigo_sbs, date, source). Restatements land
#   cleanly - matches the fact_positions upsert-DO-UPDATE policy.
#
# The row-by-row upsert primitives and validators are shared across
# feeds in src/pipelines/positions/fms/_common.py; only the per-feed
# SQL and column lists live here.
#
# Both accept an already-open connection (caller controls the
# transaction); empty DataFrames are no-ops.
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
    "batch_id", "id_secuencial_fecha_proceso", "date",
    "codigo_fondo", "codigo_sbs",
    "codigo_iso_moneda_nocional", "codigo_iso_moneda_contraparte",
    "valor_nocional", "tipo_cambio_spot", "nocional_soles",
    "moneda_compra", "moneda_venta",
    "raw_payload",
]

STG_UPSERT = f"""
INSERT INTO stg_positions_fms_forwards ({", ".join(STG_COLUMNS)})
VALUES ({", ".join(["%s"] * len(STG_COLUMNS))})
ON CONFLICT (codigo_fondo, codigo_sbs, date) DO UPDATE SET
    batch_id                      = EXCLUDED.batch_id,
    loaded_at                     = CURRENT_TIMESTAMP,
    id_secuencial_fecha_proceso   = EXCLUDED.id_secuencial_fecha_proceso,
    codigo_iso_moneda_nocional    = EXCLUDED.codigo_iso_moneda_nocional,
    codigo_iso_moneda_contraparte = EXCLUDED.codigo_iso_moneda_contraparte,
    valor_nocional                = EXCLUDED.valor_nocional,
    tipo_cambio_spot              = EXCLUDED.tipo_cambio_spot,
    nocional_soles                = EXCLUDED.nocional_soles,
    moneda_compra                 = EXCLUDED.moneda_compra,
    moneda_venta                  = EXCLUDED.moneda_venta,
    raw_payload                   = EXCLUDED.raw_payload
"""


FACT_COLUMNS = [
    "portfolio_id", "codigo_sbs", "date", "source",
    "codigo_iso_moneda_nocional",
    "valor_nocional", "tipo_cambio_spot", "nocional_soles",
    "moneda_compra", "moneda_venta",
    "fecha_vencimiento", "precio_forward", "valor_strike", "mtm_soles",
]

# Columns fact_positions_forwards declares NOT NULL (see 27_fact_positions_forwards.sql).
# A null here is a data problem (usually a missing FMS field, e.g. a stale
# TipoCambioSpot with no MonedaCambio fallback) — caught before the row-by-row
# INSERT so the error names the column + codigo_sbs instead of surfacing as an
# opaque psycopg NotNullViolation mid-loop.
FACT_NOT_NULL_COLUMNS = [
    "portfolio_id", "codigo_sbs", "date", "source",
    "codigo_iso_moneda_nocional",
    "valor_nocional", "tipo_cambio_spot", "nocional_soles",
    "moneda_compra", "moneda_venta",
]

FACT_UPSERT = f"""
INSERT INTO fact_positions_forwards ({", ".join(FACT_COLUMNS)})
VALUES ({", ".join(["%s"] * len(FACT_COLUMNS))})
ON CONFLICT (portfolio_id, codigo_sbs, date, source) DO UPDATE SET
    codigo_iso_moneda_nocional = EXCLUDED.codigo_iso_moneda_nocional,
    valor_nocional             = EXCLUDED.valor_nocional,
    tipo_cambio_spot           = EXCLUDED.tipo_cambio_spot,
    nocional_soles             = EXCLUDED.nocional_soles,
    moneda_compra              = EXCLUDED.moneda_compra,
    moneda_venta               = EXCLUDED.moneda_venta,
    fecha_vencimiento          = EXCLUDED.fecha_vencimiento,
    precio_forward             = EXCLUDED.precio_forward,
    valor_strike               = EXCLUDED.valor_strike,
    mtm_soles                  = EXCLUDED.mtm_soles,
    loaded_at                  = CURRENT_TIMESTAMP
"""


def load_staging(conn: Connection, stg_df: pd.DataFrame) -> int:
    """Upsert into stg_positions_fms_forwards. Returns row count."""
    if stg_df.empty:
        logger.info("load_staging: empty DataFrame, nothing to write")
        return 0

    validate_columns(stg_df, STG_COLUMNS)
    n = execute_row_by_row(conn, STG_UPSERT, stg_df, STG_COLUMNS, jsonb_column="raw_payload")
    logger.info(f"load_staging: upserted {n} rows into stg_positions_fms_forwards")
    return n


def load_fact(conn: Connection, fact_df: pd.DataFrame) -> int:
    """Upsert into fact_positions_forwards. Returns row count."""
    if fact_df.empty:
        logger.info("load_fact: empty DataFrame, nothing to write")
        return 0

    validate_columns(fact_df, FACT_COLUMNS)
    validate_not_null(fact_df, FACT_NOT_NULL_COLUMNS,
                      table="fact_positions_forwards", id_col="codigo_sbs")
    n = execute_row_by_row(conn, FACT_UPSERT, fact_df, FACT_COLUMNS)
    logger.info(f"load_fact: upserted {n} rows into fact_positions_forwards")
    return n
