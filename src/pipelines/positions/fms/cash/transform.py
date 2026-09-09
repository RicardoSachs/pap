# src/pipelines/positions/fms/cash/transform.py
# ---------------------------------------------------------------
# Two pure DataFrame transforms:
#
# transform_for_staging(raw_df, batch_id) -> stg-shaped DataFrame
#   - Renames PascalCase FMS columns to snake_case staging columns
#   - Converts id_secuencial_fecha_reporte (int yyyymmdd) to date DATE
#   - Splits Tier 1 (typed columns) from Tier 2 (raw_payload JSONB dict)
#
# transform_for_fact(stg_df, portfolios) -> fact-shaped DataFrame
#   - Resolves codigo_fondo -> portfolio_id via dim_portfolio lookup
#   - Selects the fact columns; materializes source='fms' constant
#
# Cash is a balance per currency: no legs, no MTM, no maturity, no
# codigo_sbs. Simpler than the forwards transform.
#
# Both are pure functions. No DB access. Called by run.py.
# ---------------------------------------------------------------

import logging
from datetime import date
from decimal import Decimal

import pandas as pd

logger = logging.getLogger(__name__)


# Tier 1 columns: FMS PascalCase -> stg_positions_fms_cash snake_case
STAGING_COLUMN_MAP = {
    "IdSecuencialFechaReporte": "id_secuencial_fecha_reporte",
    "CodigoFondo":              "codigo_fondo",
    "IdEntidad":                "codigo_institucion",
    "CodigoIsoMoneda":          "codigo_iso_moneda",
    "CodigoInstrumento":        "codigo_instrumento",   # account id, grain key
    "Institucion":              "nombre_institucion",
    "SaldoContable":            "saldo_contable",
    "MontoTotalSoles":          "monto_total_soles",
    "TasaInteres":              "tasa_interes",
    "InteresAcumulado":         "interes_acumulado",
}

# Tier 2: emitted by cash.sql but preserved verbatim in raw_payload JSONB.
# Enumerated so they don't trip the "unexpected column" warning; any further
# unlisted column still lands in raw_payload (with a warning).
TIER_2_COLUMNS: list[str] = ["MontoTotalOriginal"]

# Staging grain (matches the stg/fact PKs). transform_for_staging RAISES if
# two source rows collapse onto one grain key - the row-by-row upsert would
# otherwise silently keep only the last row (exactly how the multi-account
# under-reporting went unnoticed before codigo_instrumento joined the grain).
STG_GRAIN = [
    "codigo_fondo", "codigo_institucion", "codigo_iso_moneda",
    "codigo_instrumento", "date",
]


def transform_for_staging(raw_df: pd.DataFrame, batch_id: str) -> pd.DataFrame:
    """
    Normalize a raw FMS cash DataFrame to staging shape.

    Returns a DataFrame matching stg_positions_fms_cash columns:
    batch_id, id_secuencial_fecha_reporte, date, codigo_fondo,
    codigo_institucion, codigo_iso_moneda, nombre_institucion,
    saldo_contable, monto_total_soles, tasa_interes, interes_acumulado,
    raw_payload (dict, JSON-serializable).

    Empty DataFrame in => empty DataFrame out.
    """
    if raw_df.empty:
        return pd.DataFrame()

    _validate_expected_columns(raw_df)

    stg = pd.DataFrame({
        stg_col: raw_df[fms_col]
        for fms_col, stg_col in STAGING_COLUMN_MAP.items()
    })

    stg["batch_id"] = batch_id
    stg["date"] = stg["id_secuencial_fecha_reporte"].map(_yyyymmdd_to_date)
    stg["raw_payload"] = raw_df.apply(_build_raw_payload, axis=1)

    # Grain guard: fail loud if the source violates the assumed uniqueness -
    # the upsert would silently collapse duplicates to the last row.
    dupes = stg[stg.duplicated(subset=STG_GRAIN, keep=False)]
    if not dupes.empty:
        sample = dupes[STG_GRAIN].drop_duplicates().head(5).to_dict("records")
        raise ValueError(
            f"stg_positions_fms_cash grain violated: {len(dupes)} rows share "
            f"{len(sample) if len(sample) < 5 else '>=5'} grain key(s) - the upsert "
            f"would silently drop accounts. Sample keys: {sample}. "
            f"The grain needs another discriminating column."
        )

    logger.info(f"transform_for_staging: {len(stg)} rows shaped for stg_positions_fms_cash")
    return stg


def transform_for_fact(stg_df: pd.DataFrame, portfolios: pd.DataFrame) -> pd.DataFrame:
    """
    Convert staging-shaped DataFrame to fact-shaped DataFrame.

    portfolios: DataFrame with (procode, portfolio_id) columns, filtered
    to dim_portfolio where source='fms'. Loaded once per run and passed in.

    Rows whose codigo_fondo can't be resolved to a portfolio_id are
    dropped with a WARNING - ops decides whether to register the missing
    portfolio and re-run --from-stg, or ignore.

    Returns a DataFrame matching fact_positions_cash columns.
    """
    if stg_df.empty:
        return pd.DataFrame()

    # Portfolio resolution
    pmap = dict(zip(portfolios["procode"], portfolios["portfolio_id"]))
    resolved = stg_df["codigo_fondo"].map(pmap)
    unresolved_mask = resolved.isna()
    if unresolved_mask.any():
        missing = stg_df.loc[unresolved_mask, "codigo_fondo"].unique().tolist()
        logger.warning(
            f"transform_for_fact: dropping {int(unresolved_mask.sum())} rows with "
            f"unresolved codigo_fondo: {missing}"
        )
    stg_df = stg_df.loc[~unresolved_mask].copy()
    stg_df["portfolio_id"] = resolved.loc[~unresolved_mask].astype(int)

    fact = stg_df[[
        "portfolio_id",
        "codigo_institucion",
        "codigo_iso_moneda",
        "codigo_instrumento",
        "date",
        "nombre_institucion",
        "saldo_contable",
        "monto_total_soles",
        "tasa_interes",
        "interes_acumulado",
    ]].copy()
    fact["source"] = "fms"

    logger.info(f"transform_for_fact: {len(fact)} rows shaped for fact_positions_cash")
    return fact


def _validate_expected_columns(raw_df: pd.DataFrame) -> None:
    expected = set(STAGING_COLUMN_MAP.keys()) | set(TIER_2_COLUMNS)
    actual = set(raw_df.columns)
    missing = expected - actual
    unexpected = actual - expected
    if missing:
        raise ValueError(f"FMS cash query missing expected columns: {sorted(missing)}")
    if unexpected:
        logger.warning(
            f"FMS cash query returned unexpected columns (will land in raw_payload): "
            f"{sorted(unexpected)}"
        )


def _build_raw_payload(row: pd.Series) -> dict:
    """
    Build the raw_payload JSONB dict from Tier 2 columns of one row.
    Values are coerced to JSON-serializable primitives.
    """
    payload = {}
    for col in TIER_2_COLUMNS:
        if col in row.index:
            payload[col] = _to_json_value(row[col])
    # Catch any unexpected columns too
    for col in row.index:
        if col not in STAGING_COLUMN_MAP and col not in TIER_2_COLUMNS:
            payload[col] = _to_json_value(row[col])
    return payload


def _to_json_value(v):
    """Coerce a pandas cell value to a JSON-serializable primitive."""
    if pd.isna(v):
        return None
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):  # date/datetime
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def _yyyymmdd_to_date(v) -> date | None:
    """Convert an int like 20260622 to date(2026, 6, 22)."""
    if v is None or pd.isna(v):
        return None
    n = int(v)
    return date(n // 10000, (n // 100) % 100, n % 100)
