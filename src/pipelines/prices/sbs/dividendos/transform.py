
# src/pipelines/prices/sbs/dividendos/transform.py
# ---------------------------------------------------------------
# Transforms stg_prices_sbs_dividendos into:
#   - facts: dividend adjustment factors -> fact_prices
#   - dims:  empty (no bond attribute updates from dividends)
#
# FILE_TYPE_FIELDS: ["DIV_ADJ_FACTOR"]
# ---------------------------------------------------------------

import logging
from datetime import date
import pandas as pd

logger = logging.getLogger(__name__)

FACT_FIELD_MAP = {
    "factor_ajuste": "DIV_ADJ_FACTOR",
}


def transform(
    stg_df: pd.DataFrame,
    securities: list[dict],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Maps stg rows to (facts_df, empty dims_df).

    facts_df: [series_id, date, value, source]
    dims_df:  empty DataFrame (no dim updates for dividends)
    """
    if stg_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    series_map = {
        (s["codigo_sbs"], s["field"]): s["series_id"]
        for s in securities
        if s.get("codigo_sbs")
    }

    fact_rows = []

    for _, row in stg_df.iterrows():
        codigo = row.get("codigo_sbs")
        if not codigo:
            continue

        for stg_col, field_name in FACT_FIELD_MAP.items():
            sid = series_map.get((codigo, field_name))
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

    logger.info(f"dividendos transform: {len(facts_df)} fact rows.")
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
