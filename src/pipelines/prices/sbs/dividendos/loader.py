
# src/pipelines/prices/sbs/dividendos/loader.py
# ---------------------------------------------------------------
# Loads transformed dividendos data into fact_prices.
# No dim_security updates for dividends.
# ---------------------------------------------------------------

import logging
import pandas as pd

logger = logging.getLogger(__name__)


def load_facts(conn, df: pd.DataFrame) -> tuple[int, int]:
    """
    Inserts transformed dividendos rows into fact_prices.
    ON CONFLICT (series_id, date) DO NOTHING for idempotency.
    """
    if df.empty:
        return 0, 0
    loaded = skipped = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            """
            INSERT INTO fact_prices (series_id, date, price, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (series_id, date) DO NOTHING
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
    logger.info(f"fact_prices (dividendos): {loaded} loaded, {skipped} skipped.")
    return loaded, skipped


def load_dims(conn, df: pd.DataFrame) -> None:
    """No-op for dividends. Included for interface consistency."""
    pass
