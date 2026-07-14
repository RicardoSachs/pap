
# src/pipelines/prices/sbs/rf_exterior/extract.py
import logging
from datetime import date, datetime
import pandas as pd
from src.scrapers.sbs import find_latest_file

logger = logging.getLogger(__name__)
SBS_SUBDIR = "rfe"

# Hex-decoded keys guarantee byte-perfect match with SBS file headers
# RAW_COLUMNS = {
#     c.strip(): v for c, v in [
#         (bytes.fromhex("43264f61637574653b4449474f20534253").decode("latin-1"), "codigo_sbs"),
#         ("ISIN", "isin"),
#         ("TIPO DE INSTRUMENTO", "tipo_instrumento"),
#         ("EMISOR", "emisor"),
#         ("MONEDA", "moneda"),
#         ("VALOR FACIAL", "valor_facial"),
#         ("ORIGEN DEL PRECIO", "origen_precio"),
#         ("PRECIO LIMPIO (MONTO)", "precio_limpio_monto"),
#         ("PRECIO LIMPIO (%)", "precio_limpio_pct"),
#         ("PRECIO SUCIO (MONTO)", "precio_sucio_monto"),
#         ("PRECIO SUCIO (%)", "precio_sucio_pct"),
#         (bytes.fromhex("494e544552264561637574653b5320434f525249444f20284d4f4e544f29").decode("latin-1"), "interes_corrido_monto"),
#         (bytes.fromhex("464543484120454d495349264f61637574653b4e").decode("latin-1"), "fecha_emision"),
#         ("FECHA VENCIMIENTO", "fecha_vencimiento"),
#         (bytes.fromhex("5441534120435550264f61637574653b4e").decode("latin-1"), "tasa_cupon"),
#         (bytes.fromhex("265561637574653b4c54494d4f20435550264f61637574653b4e").decode("latin-1"), "ultimo_cupon"),
#         (bytes.fromhex("5052264f61637574653b58494d4f20435550264f61637574653b4e").decode("latin-1"), "proximo_cupon"),
#         (bytes.fromhex("56415249414349264f61637574653b4e2050524543494f20535543494f").decode("latin-1"), "variacion_precio_sucio"),
#     ]
# }
# DATE_COLS = ["fecha_emision", "fecha_vencimiento", "ultimo_cupon", "proximo_cupon"]

RAW_COLUMNS = {
    "C&Oacute;DIGO SBS": "codigo_sbs", "ISIN": "isin",
    "TIPO DE INSTRUMENTO": "tipo_instrumento", "EMISOR": "emisor", "MONEDA": "moneda",
    "VALOR FACIAL": "valor_facial", "ORIGEN DEL PRECIO": "origen_precio",
    "FECHA EMISI&Oacute;N": "fecha_emision", "FECHA VENCIMIENTO": "fecha_vencimiento",
    "TASA CUP&Oacute;N": "tasa_cupon", "&Uacute;LTIMO CUP&Oacute;N": "ultimo_cupon",
    "PR&Oacute;XIMO CUP&Oacute;N": "proximo_cupon", "PRECIO LIMPIO (MONTO)": "precio_limpio_monto",
    "PRECIO LIMPIO (%)": "precio_limpio_pct", "PRECIO SUCIO (MONTO)": "precio_sucio_monto", 
    "PRECIO SUCIO (%)": "precio_sucio_pct", "INTER&Eacute;S CORRIDO (MONTO)": "interes_corrido_monto",
    "VARIACI&Oacute;N PRECIO SUCIO": "variacion_precio_sucio",
}
DATE_COLS = ["fecha_emision", "fecha_vencimiento", "ultimo_cupon", "proximo_cupon"]


def extract(run_date: date) -> pd.DataFrame:
    path = find_latest_file(SBS_SUBDIR, run_date)
    if path is None:
        logger.warning(f"rf_exterior: no file found for {run_date}.")
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
    for col in DATE_COLS:
        if col in raw.columns:
            raw[col] = pd.to_datetime(raw[col], errors="coerce", dayfirst=True).dt.date
            raw[col] = raw[col].where(raw[col].notna(), None)
    raw["date"] = run_date
    raw["loaded_at"] = datetime.now()

    # Drop rows with no codigo_sbs — can't stage without PK
    raw = raw[raw["codigo_sbs"].notna() & (raw["codigo_sbs"].astype(str).str.strip() != "")]

    logger.info(f"rf_exterior: {len(raw)} rows extracted.")
    return raw


def load_stg(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    inserted = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            """
            INSERT INTO stg_prices_sbs_rf_exterior (
                codigo_sbs, isin, tipo_instrumento, emisor, moneda,
                valor_facial, origen_precio, fecha_emision, fecha_vencimiento,
                tasa_cupon, ultimo_cupon, proximo_cupon,
                precio_limpio_monto, precio_limpio_pct,
                precio_sucio_monto, precio_sucio_pct,
                interes_corrido_monto, variacion_precio_sucio,
                date, loaded_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s
            )
            ON CONFLICT (codigo_sbs, date, loaded_at) DO NOTHING
            """,
            (
                _s(row, "codigo_sbs"),
                _s(row, "isin"),
                _s(row, "tipo_instrumento"),
                _s(row, "emisor"),
                _s(row, "moneda"),
                _f(row.get("valor_facial")),
                _s(row, "origen_precio"),
                _d(row.get("fecha_emision")),
                _d(row.get("fecha_vencimiento")),
                _f(row.get("tasa_cupon")),
                _d(row.get("ultimo_cupon")),
                _d(row.get("proximo_cupon")),
                _f(row.get("precio_limpio_monto")),
                _f(row.get("precio_limpio_pct")),
                _f(row.get("precio_sucio_monto")),
                _f(row.get("precio_sucio_pct")),
                _f(row.get("interes_corrido_monto")),
                _f(row.get("variacion_precio_sucio")),
                row["date"],
                row["loaded_at"],
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
    logger.info(f"stg_prices_sbs_rf_exterior: {inserted} rows staged.")
    return inserted



def _f(val):
    """Coerce to float or None. Handles comma decimal separators."""
    try:
        if val is None:
            return None
        s = str(val).strip()
        if s in ("", "nan", "None", "none"):
            return None
        s = s.replace(",", ".")  # Handle Spanish decimal comma
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
