# src/pipelines/prices/sbs/tipo_cambio/extract.py
import logging
from datetime import date, datetime
import pandas as pd
from src.scrapers.sbs import find_latest_file

logger = logging.getLogger(__name__)
SBS_SUBDIR = "tc"

RAW_COLUMNS = {
    "FECHA": "fecha",
    "MONEDA NOCIONAL": "moneda_nocional",
    "MONEDA CONTRAPARTE": "moneda_contraparte",
    "FUENTE": "fuente",
    "BID ORIGINAL": "bid_original",
    "ASK ORIGINAL": "ask_original",
    "PEN BID": "pen_bid",
    "PEN ASK": "pen_ask",
    "VAR BID": "var_bid",
    "VAR ASK": "var_ask",
}


def extract(run_date: date) -> pd.DataFrame:
    path = find_latest_file(SBS_SUBDIR, run_date)
    if path is None:
        logger.warning(f"tipo_cambio: no file found for {run_date}.")
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

    # Drop rows missing PK columns
    raw = raw[
        raw["moneda_nocional"].notna() & (raw["moneda_nocional"].astype(str).str.strip() != "") &
        raw["moneda_contraparte"].notna() & (raw["moneda_contraparte"].astype(str).str.strip() != "") &
        raw["fuente"].notna() & (raw["fuente"].astype(str).str.strip() != "")
    ]

    # Drop the FECHA column from file — we use run_date instead
    raw = raw.drop(columns=["fecha"], errors="ignore")

    raw["date"] = run_date
    raw["loaded_at"] = datetime.now()
    logger.info(f"tipo_cambio: {len(raw)} rows extracted.")
    return raw


def load_stg(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    inserted = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            """
            INSERT INTO stg_prices_sbs_tipo_cambio (
                moneda_nocional, moneda_contraparte, fuente,
                bid_original, ask_original,
                pen_bid, pen_ask,
                var_bid, var_ask,
                date, loaded_at
            ) VALUES (
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s
            )
            ON CONFLICT (moneda_nocional, moneda_contraparte, fuente, date, loaded_at) DO NOTHING
            """,
            (
                _s(row, "moneda_nocional"),
                _s(row, "moneda_contraparte"),
                _s(row, "fuente"),
                _f(row.get("bid_original")),
                _f(row.get("ask_original")),
                _f(row.get("pen_bid")),
                _f(row.get("pen_ask")),
                _f(row.get("var_bid")),
                _f(row.get("var_ask")),
                row["date"],
                row["loaded_at"],
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
    logger.info(f"stg_prices_sbs_tipo_cambio: {inserted} rows staged.")
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
