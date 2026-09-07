# src/pipelines/prices/sbs/dividendos/extract.py
import logging
from datetime import date, datetime
import pandas as pd
from src.scrapers.sbs import find_latest_file

logger = logging.getLogger(__name__)
SBS_SUBDIR = "dividendos"

RAW_COLUMNS = {
    "FECHA VECTOR": "fecha_vector", "C&Oacute;DIGO SBS": "codigo_sbs", "ISIN": "isin", 
    "NEM&Oacute;NICO": "nemonico", "EMISOR": "emisor", "MONEDA": "moneda", 
    "FACTOR DE AJUSTE": "factor_ajuste", "TIPO DE ENTREGA DE DERECHO": "tipo_entrega",
}
DATE_COLS = ["fecha_vector", "date"]


def extract(run_date: date) -> pd.DataFrame:
    path = find_latest_file(SBS_SUBDIR, run_date)
    if path is None:
        logger.warning(f"dividendos: no file found for {run_date}.")
        return pd.DataFrame()
    logger.info(f"Reading {path.name}")
    try:
        raw = pd.read_csv(path, encoding='latin-1', sep='\t')
    except Exception as e:
        logger.error(f"Failed to read {path.name}: {e}", exc_info=True)
        return pd.DataFrame()
    raw = raw.rename(columns=RAW_COLUMNS)
    for col in RAW_COLUMNS.values():
        if col not in raw.columns:
            raw[col] = None
    raw = raw[list(dict.fromkeys(RAW_COLUMNS.values()))].copy().dropna(how="all")
    # Canonical codigo_sbs is DASHLESS (the FMS format) - strip the SBS
    # dash separators at the ingestion boundary.
    raw["codigo_sbs"] = raw["codigo_sbs"].map(
        lambda v: v.replace("-", "") if isinstance(v, str) else v
    )
    raw["tipo_instrumento"] = None

    # fecha_vector → date
    if "fecha_vector" in raw.columns:
        raw["fecha_vector"] = pd.to_datetime(raw["fecha_vector"], errors="coerce", dayfirst=True).dt.date
        raw["fecha_vector"] = raw["fecha_vector"].where(raw["fecha_vector"].notna(), None)

    # Drop rows with no codigo_sbs — can't stage without PK
    raw = raw[raw["codigo_sbs"].notna() & (raw["codigo_sbs"].astype(str).str.strip() != "")]

    raw["date"] = run_date
    raw["loaded_at"] = datetime.now()
    logger.info(f"dividendos: {len(raw)} rows extracted.")
    return raw


def load_stg(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    inserted = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            """
            INSERT INTO stg_prices_sbs_dividendos (
                fecha_vector, codigo_sbs, isin, nemonico,
                emisor, moneda, factor_ajuste, tipo_entrega,
                date, loaded_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (codigo_sbs, date, loaded_at) DO NOTHING
            """,
            (
                _d(row.get("fecha_vector")),
                _s(row, "codigo_sbs"),
                _s(row, "isin"),
                _s(row, "nemonico"),
                _s(row, "emisor"),
                _s(row, "moneda"),
                _f(row.get("factor_ajuste")),
                _s(row, "tipo_entrega"),
                row["date"],
                row["loaded_at"],
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
    logger.info(f"stg_prices_sbs_dividendos: {inserted} rows staged.")
    return inserted


def _f(val):
    """Coerce to float or None. Handles comma decimal separators."""
    try:
        if val is None:
            return None
        s = str(val).strip()
        if s in ("", "nan", "None", "none"):
            return None
        s = s.replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return None


def _s(row, col):
    """Coerce to stripped string or None."""
    v = row.get(col)
    return str(v).strip() if v is not None and str(v).strip() not in ("", "nan") else None


def _d(val):
    """Coerce to date or None."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if s in ("", "nan", "NaT", "None", "none"):
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None
