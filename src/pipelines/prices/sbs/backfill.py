# src/pipelines/prices/sbs/backfill.py
# ---------------------------------------------------------------
# Set-based backfill engine for SBS price pipelines.
#
# The daily incremental run() files stay Bloomberg-shaped (per-series
# classification) because at one day of data that cost is invisible.
# This module is the FILE-shaped path for historical ranges: the raw
# file IS the complete truth for its date, so no per-series/per-day
# machinery is needed. Five phases, each set-based:
#
#   1. Stage      - read each raw file once, bulk COPY into the
#                   existing stg_* table (dates already staged are
#                   skipped unless force=True).
#   2. Register   - ONE discover_and_register() call on the distinct
#                   instruments across the whole staged range (the
#                   registry's Pass 0 cost is paid once, not per day).
#   3. Load facts - one INSERT ... SELECT per field, joining stg ->
#                   dim_entity_identifiers (codigo_sbs) ->
#                   series_registry, entirely inside Postgres.
#                   ON CONFLICT (series_id, date) DO NOTHING.
#   4. Metadata   - one UPDATE series_registry sweep: last_loaded_date
#                   from MAX(date), backfill-pending -> active.
#   5. Dims       - one fill-only UPDATE dim_security (types that
#                   carry instrument attributes).
#
# Everything is driven by BackfillSpec entries whose FACT_FIELD_MAPs
# are imported from each pipeline's transform module - one source of
# truth, so the SQL path cannot drift from the Python path.
#
# Staging dedupes intra-file duplicate instruments per date (the
# row-by-row path relied on ON CONFLICT for this; COPY cannot).
# Fact SELECTs use DISTINCT ON (..., date) ORDER BY loaded_at DESC so
# re-staged dates (force=True) resolve to the latest load.
#
# Known quirk preserved: vector_completo maps variacion -> CHG_PRICE
# but the registry only registers PX_LAST for that file type, so
# CHG_PRICE loads 0 rows. The per-field counts in the summary make
# this visible instead of silent.
# ---------------------------------------------------------------

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Optional

import pandas as pd
from psycopg import sql

from src.db.connection import get_connection
from src.pipelines.prices.sbs.registry import discover_and_register, FILE_TYPE_FIELDS
from src.pipelines.prices.sbs.vector_completo.extract import read_raw as _extract_vector_completo
from src.pipelines.prices.sbs.rf_local.extract import extract as _extract_rf_local
from src.pipelines.prices.sbs.rf_exterior.extract import extract as _extract_rf_exterior
from src.pipelines.prices.sbs.tipo_cambio.extract import extract as _extract_tipo_cambio
from src.pipelines.prices.sbs.dividendos.extract import extract as _extract_dividendos
from src.pipelines.prices.sbs.vector_completo.transform import FACT_FIELD_MAP as _FIELDS_VECTOR_COMPLETO
from src.pipelines.prices.sbs.rf_local.transform import FACT_FIELD_MAP as _FIELDS_RF_LOCAL
from src.pipelines.prices.sbs.rf_exterior.transform import FACT_FIELD_MAP as _FIELDS_RF_EXTERIOR
from src.pipelines.prices.sbs.tipo_cambio.transform import FACT_FIELD_MAP as _FIELDS_TIPO_CAMBIO
from src.pipelines.prices.sbs.dividendos.transform import FACT_FIELD_MAP as _FIELDS_DIVIDENDOS

logger = logging.getLogger(__name__)

# Columns discover_and_register() requires for security-type files;
# specs missing any of them get a None column added (e.g. dividendos
# staging has no tipo_instrumento).
_SECURITY_REGISTRATION_COLUMNS = ["codigo_sbs", "isin", "tipo_instrumento", "emisor", "moneda"]
_FX_REGISTRATION_COLUMNS = ["moneda_nocional", "moneda_contraparte", "fuente"]


@dataclass(frozen=True)
class BackfillSpec:
    file_type: str
    stg_table: str
    extract: Callable[[date], pd.DataFrame]
    # Ordered stg columns (excluding date/loaded_at, which the engine adds)
    # mapped to a coercer kind: 's' string, 'f' float, 'd' date.
    stg_columns: dict[str, str]
    # stg columns identifying one instrument (dedupe key, DISTINCT ON key).
    key_columns: list[str]
    # SQL expression over subquery alias `s` producing the codigo_sbs
    # id_value stored by the registry (constant, code-owned - not user input).
    key_sql: str
    # stg column -> series_registry.field (imported from transform modules).
    field_map: dict[str, str]
    registration_columns: list[str]
    # Fill-only dim_security update: {dim_security col -> stg col}, or None.
    dim_update: Optional[dict[str, str]]
    # Whether float coercion should treat ',' as the decimal separator
    # (matches each extract module's own _f semantics).
    comma_decimals: bool


SPECS: dict[str, BackfillSpec] = {
    "vector_completo": BackfillSpec(
        file_type="vector_completo",
        stg_table="stg_prices_sbs_vector_completo",
        extract=_extract_vector_completo,
        stg_columns={
            "codigo_sbs": "s", "isin": "s", "nemonico": "s",
            "tipo_instrumento": "s", "emisor": "s", "moneda": "s",
            "precio": "f", "variacion": "f",
        },
        key_columns=["codigo_sbs"],
        key_sql="s.codigo_sbs",
        field_map=_FIELDS_VECTOR_COMPLETO,
        registration_columns=_SECURITY_REGISTRATION_COLUMNS,
        dim_update={"security_type": "tipo_instrumento"},
        comma_decimals=False,
    ),
    "rf_local": BackfillSpec(
        file_type="rf_local",
        stg_table="stg_prices_sbs_rf_local",
        extract=_extract_rf_local,
        stg_columns={
            "codigo_sbs": "s", "isin": "s", "nemonico": "s",
            "tipo_instrumento": "s", "emisor": "s", "moneda": "s",
            "valor_facial": "f", "origen_precio": "s",
            "fecha_emision": "d", "fecha_vencimiento": "d",
            "tasa_cupon": "f", "margen_libor": "f", "rating": "s",
            "ultimo_cupon": "d", "proximo_cupon": "d",
            "precio_limpio_monto": "f", "precio_limpio_pct": "f",
            "precio_sucio_monto": "f", "precio_sucio_pct": "f",
            "interes_corrido_monto": "f", "tir": "f", "spreads": "f",
            "tir_sin_opciones": "f", "duracion": "f",
            "variacion_precio_limpio": "f", "variacion_precio_sucio": "f",
            "variacion_tir": "f",
        },
        key_columns=["codigo_sbs"],
        key_sql="s.codigo_sbs",
        field_map=_FIELDS_RF_LOCAL,
        registration_columns=_SECURITY_REGISTRATION_COLUMNS,
        dim_update={"security_type": "tipo_instrumento", "currency": "moneda"},
        comma_decimals=True,
    ),
    "rf_exterior": BackfillSpec(
        file_type="rf_exterior",
        stg_table="stg_prices_sbs_rf_exterior",
        extract=_extract_rf_exterior,
        stg_columns={
            "codigo_sbs": "s", "isin": "s",
            "tipo_instrumento": "s", "emisor": "s", "moneda": "s",
            "valor_facial": "f", "origen_precio": "s",
            "fecha_emision": "d", "fecha_vencimiento": "d",
            "tasa_cupon": "f", "ultimo_cupon": "d", "proximo_cupon": "d",
            "precio_limpio_monto": "f", "precio_limpio_pct": "f",
            "precio_sucio_monto": "f", "precio_sucio_pct": "f",
            "interes_corrido_monto": "f", "variacion_precio_sucio": "f",
        },
        key_columns=["codigo_sbs"],
        key_sql="s.codigo_sbs",
        field_map=_FIELDS_RF_EXTERIOR,
        registration_columns=_SECURITY_REGISTRATION_COLUMNS,
        dim_update={"security_type": "tipo_instrumento", "currency": "moneda"},
        comma_decimals=True,
    ),
    "tipo_cambio": BackfillSpec(
        file_type="tipo_cambio",
        stg_table="stg_prices_sbs_tipo_cambio",
        extract=_extract_tipo_cambio,
        stg_columns={
            "moneda_nocional": "s", "moneda_contraparte": "s", "fuente": "s",
            "bid_original": "f", "ask_original": "f",
            "pen_bid": "f", "pen_ask": "f",
            "var_bid": "f", "var_ask": "f",
        },
        key_columns=["moneda_nocional", "moneda_contraparte", "fuente"],
        key_sql="'FX_' || s.moneda_nocional || '_' || s.moneda_contraparte || '_' || s.fuente",
        field_map=_FIELDS_TIPO_CAMBIO,
        registration_columns=_FX_REGISTRATION_COLUMNS,
        dim_update=None,
        comma_decimals=True,
    ),
    "dividendos": BackfillSpec(
        file_type="dividendos",
        stg_table="stg_prices_sbs_dividendos",
        extract=_extract_dividendos,
        stg_columns={
            "fecha_vector": "d", "codigo_sbs": "s", "isin": "s",
            "nemonico": "s", "emisor": "s", "moneda": "s",
            "factor_ajuste": "f", "tipo_entrega": "s",
        },
        key_columns=["codigo_sbs"],
        key_sql="s.codigo_sbs",
        field_map=_FIELDS_DIVIDENDOS,
        registration_columns=_SECURITY_REGISTRATION_COLUMNS,
        dim_update=None,
        comma_decimals=True,
    ),
}


# ---------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------

def run_backfill(
    file_type: str,
    dates: list[date],
    force: bool = False,
) -> dict:
    """
    Set-based backfill of one file type over the given dates
    (discovered from raw filenames by the caller - exact-date files,
    so extract() never falls back to a stale earlier file).

    Registration, fact load, metadata and dim sweeps always run over
    the full [min(dates), max(dates)] span - they are idempotent and
    cheap, and re-running them heals partially loaded history even
    when no new dates needed staging.

    Returns a summary dict for logging by the caller.
    """
    spec = SPECS[file_type]
    if not dates:
        logger.info(f"backfill [{file_type}]: no dates to process.")
        return {"file_type": file_type, "staged_rows": 0, "staged_dates": 0}

    dates = sorted(set(dates))
    span_start, span_end = dates[0], dates[-1]
    logger.info(
        f"=== backfill [{file_type}] | {len(dates)} dates "
        f"({span_start} to {span_end}) | force={force} ==="
    )

    # Phase 1: stage missing dates
    with get_connection() as conn:
        staged_already = _staged_dates(conn, spec, span_start, span_end)
    to_stage = dates if force else [d for d in dates if d not in staged_already]
    if len(dates) - len(to_stage):
        logger.info(
            f"backfill [{file_type}]: skipping {len(dates) - len(to_stage)} "
            f"dates already staged (force=False)."
        )
    staged_rows = _stage(spec, to_stage)

    # Phase 2: register once from the distinct instruments in the span
    new_series = _register_from_stg(spec, span_start, span_end)

    # Phase 3: facts - one INSERT..SELECT per field
    fact_counts = _load_facts(spec, span_start, span_end)

    # Phase 4: series_registry sweep
    series_touched = _sweep_metadata(spec)

    # Phase 5: dim_security fill-only sweep
    dims_touched = _sweep_dims(spec, span_start, span_end) if spec.dim_update else 0

    summary = {
        "file_type": file_type,
        "staged_dates": len(to_stage),
        "staged_rows": staged_rows,
        "new_series_registered": new_series,
        "fact_rows_by_field": fact_counts,
        "fact_rows_total": sum(fact_counts.values()),
        "series_metadata_updated": series_touched,
        "dim_rows_filled": dims_touched,
    }
    logger.info(f"backfill [{file_type}] summary: {summary}")
    return summary


# ---------------------------------------------------------------
# Phase 1: staging (bulk COPY)
# ---------------------------------------------------------------

def _staged_dates(conn, spec: BackfillSpec, start: date, end: date) -> set[date]:
    cur = conn.execute(
        sql.SQL("SELECT DISTINCT date FROM {} WHERE date BETWEEN %s AND %s")
        .format(sql.Identifier(spec.stg_table)),
        (start, end),
    )
    return {r["date"] for r in cur.fetchall()}


def _stage(spec: BackfillSpec, dates_to_stage: list[date]) -> int:
    """
    Extracts each date's raw file and bulk-COPYs all rows into staging
    in one pass. Intra-file duplicate instruments are dropped (COPY has
    no ON CONFLICT; the PK includes loaded_at so cross-run duplicates
    are impossible anyway - each run gets a fresh loaded_at).
    """
    if not dates_to_stage:
        return 0

    loaded_at = datetime.now(timezone.utc)
    columns = list(spec.stg_columns) + ["date", "loaded_at"]
    rows: list[tuple] = []

    for run_date in dates_to_stage:
        raw = spec.extract(run_date)
        if raw.empty:
            logger.warning(f"backfill [{spec.file_type}]: no rows for {run_date}.")
            continue
        before = len(raw)
        raw = raw.drop_duplicates(subset=spec.key_columns, keep="first")
        if len(raw) < before:
            logger.warning(
                f"backfill [{spec.file_type}]: {run_date} dropped "
                f"{before - len(raw)} intra-file duplicate rows."
            )
        for _, r in raw.iterrows():
            rows.append(
                tuple(
                    _coerce(r.get(col), kind, spec.comma_decimals)
                    for col, kind in spec.stg_columns.items()
                )
                + (run_date, loaded_at)
            )

    if not rows:
        logger.warning(f"backfill [{spec.file_type}]: nothing to stage.")
        return 0

    copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(spec.stg_table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            with cur.copy(copy_sql) as copy:
                for row in rows:
                    copy.write_row(row)

    logger.info(
        f"backfill [{spec.file_type}]: staged {len(rows)} rows "
        f"across {len(dates_to_stage)} dates."
    )
    return len(rows)


def _coerce(val, kind: str, comma_decimals: bool):
    """Mirror of the extract modules' _s/_f/_d coercers, for COPY."""
    if val is None or (isinstance(val, float) and pd.isna(val)) or pd.isna(val):
        return None
    if kind == "s":
        s = str(val).strip()
        return s if s and s.lower() not in ("nan", "none") else None
    if kind == "f":
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if not s or s.lower() in ("nan", "none"):
            return None
        if comma_decimals:
            s = s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    if kind == "d":
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        s = str(val).strip()
        if not s or s.lower() in ("nan", "nat", "none"):
            return None
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    raise ValueError(f"unknown coercer kind: {kind}")


# ---------------------------------------------------------------
# Phase 2: registration (once per span)
# ---------------------------------------------------------------

def _register_from_stg(spec: BackfillSpec, start: date, end: date) -> int:
    """
    Builds the distinct-instrument frame from staging (already typed)
    and hands it to the existing discover_and_register() - identity
    creation stays in the one place that owns it. run_date=start so
    default_start_date covers the whole backfilled span.
    """
    key_idents = sql.SQL(", ").join(map(sql.Identifier, spec.key_columns))
    query = sql.SQL(
        "SELECT DISTINCT ON ({keys}) * FROM {stg} "
        "WHERE date BETWEEN %s AND %s ORDER BY {keys}, date DESC, loaded_at DESC"
    ).format(keys=key_idents, stg=sql.Identifier(spec.stg_table))

    with get_connection() as conn:
        rows = conn.execute(query, (start, end)).fetchall()

    if not rows:
        logger.info(f"backfill [{spec.file_type}]: no instruments in span to register.")
        return 0

    df = pd.DataFrame(rows)
    for col in spec.registration_columns:
        if col not in df.columns:
            df[col] = None

    return discover_and_register(df, spec.file_type, run_date=start)


# ---------------------------------------------------------------
# Phase 3: fact load (one INSERT..SELECT per field)
# ---------------------------------------------------------------

def _load_facts(spec: BackfillSpec, start: date, end: date) -> dict[str, int]:
    key_idents = sql.SQL(", ").join(map(sql.Identifier, spec.key_columns))
    counts: dict[str, int] = {}

    with get_connection() as conn:
        for stg_col, field in spec.field_map.items():
            stmt = sql.SQL("""
                INSERT INTO fact_prices (series_id, date, price, source)
                SELECT sr.series_id, s.date, s.{col}, 'sbs'
                FROM (
                    SELECT DISTINCT ON ({keys}, date) *
                    FROM {stg}
                    WHERE date BETWEEN %(start)s AND %(end)s
                    ORDER BY {keys}, date, loaded_at DESC
                ) s
                JOIN dim_entity_identifiers di
                  ON  di.id_type  = 'codigo_sbs'
                  AND di.source   = 'sbs'
                  AND di.id_value = {key_sql}
                JOIN series_registry sr
                  ON  sr.entity_id = di.entity_id
                  AND sr.field     = %(field)s
                  AND sr.source    = 'sbs'
                WHERE s.{col} IS NOT NULL
                ON CONFLICT (series_id, date) DO NOTHING
            """).format(
                col=sql.Identifier(stg_col),
                keys=key_idents,
                stg=sql.Identifier(spec.stg_table),
                key_sql=sql.SQL(spec.key_sql),
            )
            cur = conn.execute(stmt, {"start": start, "end": end, "field": field})
            counts[field] = cur.rowcount
            logger.info(f"backfill [{spec.file_type}]: {field}: {cur.rowcount} fact rows inserted.")

    return counts


# ---------------------------------------------------------------
# Phase 4: series_registry metadata sweep
# ---------------------------------------------------------------

def _sweep_metadata(spec: BackfillSpec) -> int:
    """
    One statement: last_loaded_date from the authoritative MAX(date) in
    fact_prices, run bookkeeping, and the backfill-pending -> active
    flip the per-day path never performed in file-driven mode.
    """
    fields = FILE_TYPE_FIELDS[spec.file_type]
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE series_registry sr
            SET last_loaded_date = agg.max_date,
                last_run_at      = NOW(),
                last_run_status  = 'success',
                status           = CASE WHEN sr.status = 'backfill-pending'
                                        THEN 'active' ELSE sr.status END,
                updated_at       = NOW()
            FROM (
                SELECT series_id, MAX(date) AS max_date
                FROM fact_prices
                WHERE source = 'sbs'
                GROUP BY series_id
            ) agg
            WHERE sr.series_id = agg.series_id
              AND sr.source    = 'sbs'
              AND sr.field     = ANY(%s)
            """,
            (fields,),
        )
        touched = cur.rowcount
    logger.info(f"backfill [{spec.file_type}]: metadata swept for {touched} series.")
    return touched


# ---------------------------------------------------------------
# Phase 5: dim_security fill-only sweep
# ---------------------------------------------------------------

def _sweep_dims(spec: BackfillSpec, start: date, end: date) -> int:
    """
    Set-based equivalent of each pipeline's load_dims(): fill NULL
    dim_security attributes from the latest staged row per instrument.
    COALESCE keeps existing values - enrichment stays authoritative.
    """
    key_idents = sql.SQL(", ").join(map(sql.Identifier, spec.key_columns))
    set_clause = sql.SQL(", ").join(
        sql.SQL("{dim} = COALESCE(ds.{dim}, s.{stg})").format(
            dim=sql.Identifier(dim_col), stg=sql.Identifier(stg_col)
        )
        for dim_col, stg_col in spec.dim_update.items()
    )
    null_guard = sql.SQL(" OR ").join(
        sql.SQL("ds.{dim} IS NULL").format(dim=sql.Identifier(dim_col))
        for dim_col in spec.dim_update
    )

    stmt = sql.SQL("""
        UPDATE dim_security ds
        SET {set_clause}, updated_at = NOW()
        FROM (
            SELECT DISTINCT ON ({keys}) *
            FROM {stg}
            WHERE date BETWEEN %(start)s AND %(end)s
            ORDER BY {keys}, date DESC, loaded_at DESC
        ) s
        JOIN dim_entity_identifiers di
          ON  di.id_type  = 'codigo_sbs'
          AND di.source   = 'sbs'
          AND di.id_value = {key_sql}
        WHERE ds.entity_id = di.entity_id
          AND ({null_guard})
    """).format(
        set_clause=set_clause,
        keys=key_idents,
        stg=sql.Identifier(spec.stg_table),
        key_sql=sql.SQL(spec.key_sql),
        null_guard=null_guard,
    )

    with get_connection() as conn:
        cur = conn.execute(stmt, {"start": start, "end": end})
        touched = cur.rowcount
    logger.info(f"backfill [{spec.file_type}]: dim_security filled for {touched} rows.")
    return touched
