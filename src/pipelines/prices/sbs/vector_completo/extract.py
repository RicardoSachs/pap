# src/pipelines/prices/sbs/vector_completo/extract.py
import logging
from datetime import date
import pandas as pd
from src.scrapers.sbs import find_latest_file

logger = logging.getLogger(__name__)
SBS_SUBDIR = "vector_completo"

RAW_COLUMNS = {
    "C&Oacute;DIGO SBS": "codigo_sbs", "ISIN": "isin", "NEM&Oacute;NICO": "nemonico",
    "TIPO INSTRUMENTO": "tipo_instrumento", "EMISOR": "emisor",
    "MONEDA": "moneda", "PRECIO": "precio", "VARIACI&Oacute;N": "variacion",
}


def read_raw(run_date: date) -> pd.DataFrame:
    """
    Reads and normalises the raw .xls file for run_date.
    Returns clean DataFrame without reference_date or loaded_at.
    Called by both run.py (for registration) and load_stg (for staging).
    Returns empty DataFrame if file not found.
    """
    path = find_latest_file(SBS_SUBDIR, run_date)
    if path is None:
        logger.warning(f"vector_completo: no file found for {run_date}.")
        return pd.DataFrame()
    logger.info(f"Reading {path.name}")
    try:
        raw = pd.read_csv(path, encoding = 'latin-1', sep = '\t')
    except Exception as e:
        logger.error(f"Failed to read {path.name}: {e}", exc_info=True)
        return pd.DataFrame()
    raw = raw.rename(columns=RAW_COLUMNS)
    for col in RAW_COLUMNS.values():
        if col not in raw.columns:
            raw[col] = None
    raw = raw[list(RAW_COLUMNS.values())].copy().dropna(how="all")
    # Canonical codigo_sbs is DASHLESS (the FMS format). SBS files publish
    # it with dash separators (01-1000-01-12B29); strip at the ingestion
    # boundary so the dashed form never enters staging, the registry, or
    # dim_entity_identifiers.
    raw["codigo_sbs"] = raw["codigo_sbs"].map(
        lambda v: v.replace("-", "") if isinstance(v, str) else v
    )
    logger.info(f"vector_completo: {len(raw)} rows read.")
    return raw


def load_stg(conn, df: pd.DataFrame, run_date: date) -> int:
    """
    Stages raw DataFrame into stg_prices_sbs_vector_completo.
    Adds reference_date and loaded_at at staging time.
    """
    if df.empty:
        return 0
    reference_date = run_date.isoformat()
    loaded_at = pd.Timestamp.now().isoformat(timespec="seconds")
    inserted = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            """
            INSERT INTO stg_prices_sbs_vector_completo
                (codigo_sbs, isin, nemonico, tipo_instrumento, emisor,
                 moneda, precio, variacion, date, loaded_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (codigo_sbs, date, loaded_at) DO NOTHING
            """,
            (_s(row, "codigo_sbs"), _s(row, "isin"), _s(row, "nemonico"),
             _s(row, "tipo_instrumento"), _s(row, "emisor"), _s(row, "moneda"),
             _f(row.get("precio")), _f(row.get("variacion")),
             reference_date, loaded_at),
        )
        if cur.rowcount > 0:
            inserted += 1
    logger.info(f"stg_prices_sbs_vector_completo: {inserted} rows staged.")
    return inserted


def _f(val):
    try:
        return float(val) if val is not None and str(val).strip() not in ("", "nan") else None
    except (ValueError, TypeError):
        return None


def _s(row, col):
    v = row.get(col)
    return str(v).strip() if v is not None and str(v).strip() not in ("", "nan") else None
