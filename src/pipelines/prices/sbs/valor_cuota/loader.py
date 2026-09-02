# src/pipelines/prices/sbs/valor_cuota/loader.py
# ---------------------------------------------------------------
# Loads transformed valor cuota rows into fact_prices.
#
# Default is ON CONFLICT DO NOTHING: re-running never duplicates and
# never overwrites. refresh=True switches to DO UPDATE for the case
# where the SBS restates a published figure - overwriting corrects
# numbers, and in long format there is no way for it to erase one
# (a missing value is a row that never reaches the loader).
# ---------------------------------------------------------------

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def load_facts(conn, df: pd.DataFrame, refresh: bool = False) -> tuple[int, int]:
    """Returns (loaded, skipped_or_updated)."""
    if df.empty:
        return 0, 0
    if refresh:
        stmt = """
            INSERT INTO fact_prices (series_id, date, price, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (series_id, date) DO UPDATE SET
                price = EXCLUDED.price,
                source = EXCLUDED.source
        """
    else:
        stmt = """
            INSERT INTO fact_prices (series_id, date, price, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (series_id, date) DO NOTHING
        """
    loaded = other = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            stmt,
            (int(row["series_id"]), row["date"],
             float(row["value"]), row["source"]),
        )
        if cur.rowcount > 0:
            loaded += 1
        else:
            other += 1
    logger.info(
        f"fact_prices (valor_cuota): {loaded} "
        f"{'written' if refresh else 'loaded'}, {other} skipped.")
    return loaded, other
