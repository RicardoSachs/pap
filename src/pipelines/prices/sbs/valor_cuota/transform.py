# src/pipelines/prices/sbs/valor_cuota/transform.py
# ---------------------------------------------------------------
# Pure transform: staging rows -> fact_prices rows. No DB access.
#
# Each staged (afp, fondo, date) row fans out into up to three fact
# rows, one per metric with a value, resolved against series_registry
# through the (procode, field) map the caller provides.
#
# The wide-table problems the monitor had to solve (completar_vacios,
# empty cells clobbering data) do not exist here: in long format a
# missing metric is a row that is not inserted, and a later extraction
# that brings it is a plain INSERT on a new (series_id, date).
# ---------------------------------------------------------------

import logging

import pandas as pd

from src.pipelines.prices.sbs.valor_cuota.afps import METRICA_FIELD, SOURCE_SBS, procode

logger = logging.getLogger(__name__)

# staging column -> business metric name
STG_METRICA = {
    "valor_cuota": "valor_cuota",
    "cuotas": "cuotas",
    "fondo_soles": "fondo",
}

FACT_COLUMNS = ["series_id", "date", "value", "source"]


def transform(stg_df: pd.DataFrame,
              series_map: dict[tuple[str, str], dict]) -> pd.DataFrame:
    """
    Maps staging rows to fact rows [series_id, date, value, source].

    series_map: (procode, field) -> series row, from afps.series_map().
    Rows whose (afp, fondo) resolve to no registered series are dropped
    with a warning - config/afps.yaml is the contract, and a clave the
    registry does not know should have been caught at staging.
    """
    if stg_df.empty:
        return pd.DataFrame(columns=FACT_COLUMNS)

    fact_rows = []
    sin_serie: set[str] = set()

    for _, row in stg_df.iterrows():
        try:
            code = procode(row["afp"], int(row["fondo"]))
        except ValueError:
            sin_serie.add(f"{row['afp']}_f{row['fondo']}")
            continue
        for stg_col, metrica in STG_METRICA.items():
            val = row.get(stg_col)
            if val is None or pd.isna(val):
                continue
            serie = series_map.get((code, METRICA_FIELD[metrica]))
            if serie is None:
                sin_serie.add(f"{code}:{METRICA_FIELD[metrica]}")
                continue
            fact_rows.append({
                "series_id": serie["series_id"],
                "date": row["date"],
                "value": float(val),
                "source": SOURCE_SBS,
            })

    if sin_serie:
        logger.warning("valor_cuota transform: sin serie registrada para %s",
                       ", ".join(sorted(sin_serie)))

    facts_df = (pd.DataFrame(fact_rows) if fact_rows
                else pd.DataFrame(columns=FACT_COLUMNS))
    logger.info(f"valor_cuota transform: {len(facts_df)} fact rows.")
    return facts_df
