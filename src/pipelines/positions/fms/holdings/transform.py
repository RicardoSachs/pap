# src/pipelines/positions/fms/holdings/transform.py
# ---------------------------------------------------------------
# Pure DataFrame transforms for the FMS holdings feed.
#
# transform_for_staging(raw_df, batch_id) -> stg-shaped DataFrame
#   - Renames PascalCase FMS columns to snake_case staging columns
#   - Converts id_secuencial_fecha_idi (int yyyymmdd) to date DATE
#   - Splits Tier 1 (typed) from Tier 2 (raw_payload; just Factor here)
#
# Three fact shapers fan the one staging frame out by type (codigo_sbs '60…'
# = deposit, else security):
#   transform_for_fact_securities(stg_df, portfolios, securities)
#       -> resolves codigo_fondo -> portfolio_id AND codigo_sbs ->
#          security_entity_id (entity-resolved); security measures + flows
#   transform_for_fact_deposits(stg_df, portfolios)
#       -> resolves codigo_fondo -> portfolio_id; derives fecha_vencimiento;
#          keyed on id_orden_inversion
#   transform_for_fact_valuation(stg_df, portfolios)
#       -> de-dupes to one row per (fund, date): valor_cuota (NAV) + valor_cartera (AUM)
#
# All pure functions. No DB access. Called by run.py.
# ---------------------------------------------------------------

import logging
from datetime import date
from decimal import Decimal

import pandas as pd

logger = logging.getLogger(__name__)

# codigo_sbs starting with this prefix is a deposit; everything else a security.
DEPOSIT_SBS_PREFIX = "60"


# Tier 1 columns: FMS PascalCase -> stg_positions_fms_holdings snake_case
STAGING_COLUMN_MAP = {
    "IdSecuencialFechaIDI":            "id_secuencial_fecha_idi",
    "CodigoFondo":                     "codigo_fondo",
    "IdOrdenInversion":                "id_orden_inversion",
    "CodigoSBS":                       "codigo_sbs",
    "CodigoIsoMoneda":                 "codigo_iso_moneda",
    "IndClase":                        "ind_clase",
    "ImportePEN":                      "importe_pen",
    "ValorCuota":                      "valor_cuota",
    "ValorCartera":                    "valor_cartera",
    "Cantidad":                        "cantidad",
    "PrecioPEN":                       "precio_pen",
    "CantidadAnterior":                "cantidad_anterior",
    "PrecioAnteriorPEN":               "precio_anterior_pen",
    "ImporteAnteriorPEN":              "importe_anterior_pen",
    "MontoInteresesVencimientoCupon":  "monto_intereses_vencimiento_cupon",
    "MontoOrdenesRenta":               "monto_ordenes_renta",
    "MontoAccionesLiberadas":          "monto_acciones_liberadas",
    "MontoDividendos":                 "monto_dividendos",
    "MontoRescates":                   "monto_rescates",
    "Tasa":                            "tasa",
    "DiasVigencia":                    "dias_vigencia",
    "IdSecuencialFechaVencimiento":    "id_secuencial_fecha_vencimiento",
}

TIER_2_COLUMNS = ["Factor"]

SECURITIES_FACT_COLUMNS = [
    "portfolio_id", "security_entity_id", "date", "source",
    "codigo_iso_moneda", "ind_clase",
    "importe_pen", "cantidad", "precio_pen",
    "cantidad_anterior", "precio_anterior_pen", "importe_anterior_pen",
    "monto_intereses_vencimiento_cupon", "monto_ordenes_renta",
    "monto_acciones_liberadas", "monto_dividendos", "monto_rescates",
]

DEPOSITS_FACT_COLUMNS = [
    "portfolio_id", "id_orden_inversion", "date", "source",
    "codigo_sbs", "codigo_iso_moneda",
    "importe_pen", "tasa", "dias_vigencia", "fecha_vencimiento",
]

VALUATION_FACT_COLUMNS = [
    "portfolio_id", "date", "source", "valor_cuota", "valor_cartera",
]


def is_deposit(codigo_sbs) -> bool:
    """A holding is a deposit iff its codigo_sbs starts with '60'."""
    return str(codigo_sbs).startswith(DEPOSIT_SBS_PREFIX)


def transform_for_staging(raw_df: pd.DataFrame, batch_id: str) -> pd.DataFrame:
    """Normalize a raw FMS holdings DataFrame to staging shape."""
    if raw_df.empty:
        return pd.DataFrame()

    _validate_expected_columns(raw_df)

    stg = pd.DataFrame({
        stg_col: raw_df[fms_col]
        for fms_col, stg_col in STAGING_COLUMN_MAP.items()
    })

    stg["batch_id"] = batch_id
    stg["date"] = stg["id_secuencial_fecha_idi"].map(_yyyymmdd_to_date)
    stg["raw_payload"] = raw_df.apply(_build_raw_payload, axis=1)

    logger.info(f"transform_for_staging: {len(stg)} rows shaped for stg_positions_fms_holdings")
    return stg


def transform_for_fact_securities(
    stg_df: pd.DataFrame,
    portfolios: pd.DataFrame,
    securities: pd.DataFrame,
) -> pd.DataFrame:
    """
    Security lines (codigo_sbs NOT '60…') -> fact_positions_securities.

    portfolios: (procode, portfolio_id). securities: (codigo_sbs,
    security_entity_id) from dim_entity_identifiers (id_type='sbs'). Rows whose
    fund OR security can't be resolved are dropped with a WARNING.
    """
    if stg_df.empty:
        return pd.DataFrame()

    sec = stg_df[~stg_df["codigo_sbs"].map(is_deposit)].copy()
    if sec.empty:
        return pd.DataFrame()

    pmap = dict(zip(portfolios["procode"], portfolios["portfolio_id"]))
    emap = dict(zip(securities["codigo_sbs"], securities["security_entity_id"]))
    sec["portfolio_id"] = sec["codigo_fondo"].map(pmap)
    sec["security_entity_id"] = sec["codigo_sbs"].map(emap)

    unresolved = sec["portfolio_id"].isna() | sec["security_entity_id"].isna()
    if unresolved.any():
        n_fund = int(sec["portfolio_id"].isna().sum())
        n_sec = int(sec["security_entity_id"].isna().sum())
        logger.warning(
            f"transform_for_fact_securities: dropping {int(unresolved.sum())} rows "
            f"(unresolved fund={n_fund}, unresolved security={n_sec})"
        )
    sec = sec.loc[~unresolved].copy()
    sec["portfolio_id"] = sec["portfolio_id"].astype(int)
    sec["security_entity_id"] = sec["security_entity_id"].astype(int)
    sec["source"] = "fms"

    fact = sec[SECURITIES_FACT_COLUMNS].copy()
    logger.info(f"transform_for_fact_securities: {len(fact)} rows for fact_positions_securities")
    return fact


def transform_for_fact_deposits(stg_df: pd.DataFrame, portfolios: pd.DataFrame) -> pd.DataFrame:
    """
    Deposit lines (codigo_sbs '60…') -> fact_positions_deposits, keyed on
    id_orden_inversion. Derives fecha_vencimiento from the source int.
    """
    if stg_df.empty:
        return pd.DataFrame()

    dep = stg_df[stg_df["codigo_sbs"].map(is_deposit)].copy()
    if dep.empty:
        return pd.DataFrame()

    pmap = dict(zip(portfolios["procode"], portfolios["portfolio_id"]))
    resolved = dep["codigo_fondo"].map(pmap)
    unresolved_mask = resolved.isna()
    if unresolved_mask.any():
        missing = dep.loc[unresolved_mask, "codigo_fondo"].unique().tolist()
        logger.warning(
            f"transform_for_fact_deposits: dropping {int(unresolved_mask.sum())} rows "
            f"with unresolved codigo_fondo: {missing}"
        )
    dep = dep.loc[~unresolved_mask].copy()
    dep["portfolio_id"] = resolved.loc[~unresolved_mask].astype(int)
    dep["fecha_vencimiento"] = dep["id_secuencial_fecha_vencimiento"].map(_yyyymmdd_to_date)
    dep["source"] = "fms"

    fact = dep[DEPOSITS_FACT_COLUMNS].copy()
    logger.info(f"transform_for_fact_deposits: {len(fact)} rows for fact_positions_deposits")
    return fact


def transform_for_fact_valuation(stg_df: pd.DataFrame, portfolios: pd.DataFrame) -> pd.DataFrame:
    """
    Fund-level NAV/AUM -> fact_portfolio_valuation. One row per (fund, date):
    valor_cuota/valor_cartera are constant across a fund's lines, so de-dupe.
    """
    if stg_df.empty:
        return pd.DataFrame()

    val = (
        stg_df[["codigo_fondo", "date", "valor_cuota", "valor_cartera"]]
        .drop_duplicates(subset=["codigo_fondo", "date"])
        .copy()
    )

    pmap = dict(zip(portfolios["procode"], portfolios["portfolio_id"]))
    resolved = val["codigo_fondo"].map(pmap)
    unresolved_mask = resolved.isna()
    if unresolved_mask.any():
        missing = val.loc[unresolved_mask, "codigo_fondo"].unique().tolist()
        logger.warning(
            f"transform_for_fact_valuation: dropping {int(unresolved_mask.sum())} fund-days "
            f"with unresolved codigo_fondo: {missing}"
        )
    val = val.loc[~unresolved_mask].copy()
    val["portfolio_id"] = resolved.loc[~unresolved_mask].astype(int)
    val["source"] = "fms"

    fact = val[VALUATION_FACT_COLUMNS].copy()
    logger.info(f"transform_for_fact_valuation: {len(fact)} rows for fact_portfolio_valuation")
    return fact


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _validate_expected_columns(raw_df: pd.DataFrame) -> None:
    expected = set(STAGING_COLUMN_MAP.keys()) | set(TIER_2_COLUMNS)
    actual = set(raw_df.columns)
    missing = expected - actual
    unexpected = actual - expected
    if missing:
        raise ValueError(f"FMS holdings query missing expected columns: {sorted(missing)}")
    if unexpected:
        logger.warning(
            f"FMS holdings returned unexpected columns (will land in raw_payload): "
            f"{sorted(unexpected)}"
        )


def _build_raw_payload(row: pd.Series) -> dict:
    payload = {}
    for col in TIER_2_COLUMNS:
        if col in row.index:
            payload[col] = _to_json_value(row[col])
    for col in row.index:
        if col not in STAGING_COLUMN_MAP and col not in TIER_2_COLUMNS:
            payload[col] = _to_json_value(row[col])
    return payload


def _to_json_value(v):
    if pd.isna(v):
        return None
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return v


def _yyyymmdd_to_date(v) -> date | None:
    if v is None or pd.isna(v):
        return None
    n = int(v)
    if n == 0:
        return None
    return date(n // 10000, (n // 100) % 100, n % 100)
