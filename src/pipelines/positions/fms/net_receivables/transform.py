# src/pipelines/positions/fms/net_receivables/transform.py
# ---------------------------------------------------------------
# Two pure DataFrame transforms:
#
# transform_for_staging(raw_df, batch_id) -> stg-shaped DataFrame
#   - Renames PascalCase FMS columns to snake_case staging columns
#   - Carries the `date` column already stamped by extract.py (this feed is
#     point-in-time: the date is the as-of parameter, not a source field, so
#     it is NOT derived from an int here)
#   - Splits Tier 1 (typed columns) from Tier 2 (raw_payload; empty here)
#
# transform_for_fact(stg_df, portfolios) -> fact-shaped DataFrame
#   - Resolves codigo_fondo -> portfolio_id via dim_portfolio lookup
#   - Selects both legs (monto_cobrar, monto_pagar); source='fms' constant.
#     Net = monto_cobrar - monto_pagar is derived downstream, not here.
#
# Both are pure functions. No DB access. Called by run.py.
# ---------------------------------------------------------------

import logging
from decimal import Decimal

import pandas as pd

logger = logging.getLogger(__name__)


# Tier 1 columns: FMS PascalCase -> stg_positions_fms_net_receivables snake_case
STAGING_COLUMN_MAP = {
    "CodigoFondo":      "codigo_fondo",
    "CodigoIsoMoneda":  "codigo_iso_moneda",
    "MontoCobrar":      "monto_cobrar",
    "MontoPagar":       "monto_pagar",
}

# The source is aggregated per (fund, currency); no forensic detail to keep.
TIER_2_COLUMNS: list[str] = []

# Columns added by extract.py (not vendor columns) — expected, and not payload.
_EXTRACT_STAMPED = {"date"}


def transform_for_staging(raw_df: pd.DataFrame, batch_id: str) -> pd.DataFrame:
    """
    Normalize a raw FMS net-receivables DataFrame to staging shape.

    Returns a DataFrame matching stg_positions_fms_net_receivables columns:
    batch_id, date, codigo_fondo, codigo_iso_moneda, monto_cobrar,
    monto_pagar, raw_payload (dict, JSON-serializable).

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
    stg["date"] = raw_df["date"].values          # stamped by extract (already a date)
    stg["raw_payload"] = raw_df.apply(_build_raw_payload, axis=1)

    logger.info(f"transform_for_staging: {len(stg)} rows shaped for stg_positions_fms_net_receivables")
    return stg


def transform_for_fact(stg_df: pd.DataFrame, portfolios: pd.DataFrame) -> pd.DataFrame:
    """
    Convert staging-shaped DataFrame to fact-shaped DataFrame.

    portfolios: DataFrame with (procode, portfolio_id) columns, filtered
    to dim_portfolio where source='fms'. Loaded once per run and passed in.

    Rows whose codigo_fondo can't be resolved to a portfolio_id are dropped
    with a WARNING.

    Returns a DataFrame matching fact_positions_net_receivables columns.
    """
    if stg_df.empty:
        return pd.DataFrame()

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
        "codigo_iso_moneda",
        "date",
        "monto_cobrar",
        "monto_pagar",
    ]].copy()
    fact["source"] = "fms"

    logger.info(f"transform_for_fact: {len(fact)} rows shaped for fact_positions_net_receivables")
    return fact


def _validate_expected_columns(raw_df: pd.DataFrame) -> None:
    expected = set(STAGING_COLUMN_MAP.keys()) | set(TIER_2_COLUMNS) | _EXTRACT_STAMPED
    actual = set(raw_df.columns)
    missing = expected - actual
    unexpected = actual - expected
    if missing:
        raise ValueError(f"FMS net_receivables query missing expected columns: {sorted(missing)}")
    if unexpected:
        logger.warning(
            f"FMS net_receivables returned unexpected columns (will land in raw_payload): "
            f"{sorted(unexpected)}"
        )


def _build_raw_payload(row: pd.Series) -> dict:
    """Build the raw_payload JSONB dict from Tier 2 columns of one row."""
    payload = {}
    for col in TIER_2_COLUMNS:
        if col in row.index:
            payload[col] = _to_json_value(row[col])
    # Catch any unexpected columns too (but not Tier 1 or extract-stamped ones)
    for col in row.index:
        if (col not in STAGING_COLUMN_MAP
                and col not in TIER_2_COLUMNS
                and col not in _EXTRACT_STAMPED):
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
