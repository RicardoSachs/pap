
# src/pipelines/prices/sbs/tipo_cambio/transform.py
# ---------------------------------------------------------------
# Transforms stg_prices_sbs_tipo_cambio into:
#   - facts: daily FX bid/ask observations -> fact_prices
#
# FILE_TYPE_FIELDS: PX_BID, PX_ASK, CHG_BID, CHG_ASK
#
# FX instruments are keyed by (moneda_nocional, moneda_contraparte, fuente)
# mapped to codigo_sbs = "FX_{mn}_{mc}_{fuente}" in the registry.
# ---------------------------------------------------------------

import logging
from datetime import date
import pandas as pd

logger = logging.getLogger(__name__)

FACT_FIELD_MAP = {
    "pen_bid": "PX_BID",
    "pen_ask": "PX_ASK",
    "var_bid": "CHG_BID",
    "var_ask": "CHG_ASK",
}


def transform(
    stg_df: pd.DataFrame,
    securities: list[dict],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Maps stg rows to (facts_df, empty dims_df).

    FX instruments have no dim_security updates — only fact_prices.

    facts_df: [series_id, date, value, source]
    dims_df:  empty DataFrame (no bond attributes for FX)
    """
    if stg_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Build lookup: (codigo_sbs, field) -> series_id
    series_map = {
        (s["codigo_sbs"], s["field"]): s["series_id"]
        for s in securities
        if s.get("codigo_sbs")
    }

    fact_rows = []

    for _, row in stg_df.iterrows():
        mn = _s_val(row.get("moneda_nocional"))
        mc = _s_val(row.get("moneda_contraparte"))
        fuente = _s_val(row.get("fuente"))
        if not mn or not mc or not fuente:
            continue

        # Build the same codigo_sbs that registry uses
        codigo_sbs = f"FX_{mn}_{mc}_{fuente}"

        for stg_col, field_name in FACT_FIELD_MAP.items():
            sid = series_map.get((codigo_sbs, field_name))
            if sid is None:
                continue
            val = _f(row.get(stg_col))
            if val is None:
                continue
            fact_rows.append({
                "series_id": sid,
                "date": row["date"],
                "value": val,
                "source": "sbs",
            })

    facts_df = pd.DataFrame(fact_rows) if fact_rows else pd.DataFrame(
        columns=["series_id", "date", "value", "source"]
    )

    logger.info(f"tipo_cambio transform: {len(facts_df)} fact rows.")
    return facts_df, pd.DataFrame()


def _f(val) -> float | None:
    """Coerce to float or None. Handles native floats and comma decimals."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip()
        if s in ("", "nan", "None", "none"):
            return None
        s = s.replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return None


def _s_val(val) -> str | None:
    """Coerce to stripped string or None."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("nan", "none") else None
