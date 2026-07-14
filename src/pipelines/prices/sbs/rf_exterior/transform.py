
# src/pipelines/prices/sbs/rf_exterior/transform.py
# ---------------------------------------------------------------
# Transforms stg_prices_sbs_rf_exterior into:
#   - facts: daily price observations -> fact_prices
#   - dims:  bond metadata -> dim_security (partial update)
#
# rf_exterior has 6 fact fields (vs 12 for rf_local):
#   PX_CLEAN_MNT, PX_CLEAN_PCT, PX_DIRTY_MNT, PX_DIRTY_PCT,
#   ACCRUED_INT, CHG_DIRTY
#
# No YTM, SPREAD, YTW, DURATION, CHG_CLEAN, CHG_YTM
# (those are only in rf_local).
# ---------------------------------------------------------------

import logging
from datetime import date
import pandas as pd

logger = logging.getLogger(__name__)

FACT_FIELD_MAP = {
    "precio_limpio_monto": "PX_CLEAN_MNT",
    "precio_limpio_pct": "PX_CLEAN_PCT",
    "precio_sucio_monto": "PX_DIRTY_MNT",
    "precio_sucio_pct": "PX_DIRTY_PCT",
    "interes_corrido_monto": "ACCRUED_INT",
    "variacion_precio_sucio": "CHG_DIRTY",
}

DIM_BOND_MAP = {
    "tipo_instrumento": "instrument_type",
    "emisor": "issuer",
    "moneda": "currency",
    "valor_facial": "face_value",
    "fecha_emision": "issue_date",
    "fecha_vencimiento": "maturity_date",
    "tasa_cupon": "coupon_rate",
    "ultimo_cupon": "last_coupon_date",
    "proximo_cupon": "next_coupon_date",
}


def transform(
    stg_df: pd.DataFrame,
    securities: list[dict],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Maps stg rows to (facts_df, dims_df).

    facts_df: [series_id, date, value, source]
    dims_df:  [entity_id, instrument_type, issuer, currency, ...]
    """
    if stg_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    series_map = {
        (s["codigo_sbs"], s["field"]): s["series_id"]
        for s in securities
        if s.get("codigo_sbs")
    }

    entity_map = {
        s["codigo_sbs"]: s["entity_id"]
        for s in securities
        if s.get("codigo_sbs")
    }

    fact_rows = []
    dim_rows = []

    for _, row in stg_df.iterrows():
        codigo = row.get("codigo_sbs")
        if not codigo:
            continue

        # Fact rows — one per field in FACT_FIELD_MAP
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

        # Dim row — bond attributes
        eid = entity_map.get(codigo)
        if eid:
            dim_row = {"entity_id": eid}
            for stg_col, dim_col in DIM_BOND_MAP.items():
                dim_row[dim_col] = row.get(stg_col)
            dim_rows.append(dim_row)

    facts_df = pd.DataFrame(fact_rows) if fact_rows else pd.DataFrame(
        columns=["series_id", "date", "value", "source"]
    )
    dims_df = (
        pd.DataFrame(dim_rows).drop_duplicates(subset=["entity_id"])
        if dim_rows else pd.DataFrame()
    )

    logger.info(
        f"rf_exterior transform: {len(facts_df)} fact rows, "
        f"{len(dims_df)} dim rows."
    )
    return facts_df, dims_df


def _f(val) -> float | None:
    """Coerce to float or None. Handles native floats and strings."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip()
        return float(s) if s not in ("", "nan", "None", "none") else None
    except (ValueError, TypeError):
        return None
