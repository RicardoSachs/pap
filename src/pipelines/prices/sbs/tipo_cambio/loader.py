# src/pipelines/prices/sbs/tipo_cambio/loader.py
# ---------------------------------------------------------------
# Loads transformed tipo_cambio data into fact_prices.
# No dim_security updates for FX instruments.
# ---------------------------------------------------------------

import logging
import pandas as pd

logger = logging.getLogger(__name__)


def load_facts(conn, df: pd.DataFrame) -> tuple[int, int]:
    """
    Inserts transformed tipo_cambio price rows into fact_prices.
    Upsert: a restated price replaces the stored one; unchanged rows
    are left untouched (counted as skipped).
    """
    if df.empty:
        return 0, 0
    loaded = skipped = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            """
            INSERT INTO fact_prices (series_id, date, price, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (series_id, date) DO UPDATE
                SET price = EXCLUDED.price, source = EXCLUDED.source
                WHERE fact_prices.price IS DISTINCT FROM EXCLUDED.price
            """,
            (
                int(row["series_id"]),
                row["date"],
                float(row["value"]),
                row["source"],
            ),
        )
        if cur.rowcount > 0:
            loaded += 1
        else:
            skipped += 1
    logger.info(f"fact_prices (tipo_cambio): {loaded} written, {skipped} unchanged.")
    return loaded, skipped


def load_dims(conn, df: pd.DataFrame) -> None:
    """No-op for FX. Included for interface consistency with other pipelines."""
    pass
