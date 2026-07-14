
# pipelines/prices/bloomberg/loader.py
# ---------------------------------------------------------------
# Loads transformed price data into fact_prices.
# Upserts on (series_id, date) - safe to re-run.
# Returns counts for logging in run.py
# --------------------------------------------------------------

import logging
import pandas as pd

logger = logging.getLogger(__name__)

def load_prices(conn, df: pd.DataFrame) -> tuple[int, int]:
    '''
    Upserts transformed price rows into fact_prices.
    PRIMARY KEY (series_id, date) means duplicate lodas
    are silently ignored (ON CONFLICT DO NOTHING)
    
    Returns:
        (loaded, skipped) row counts.
    '''
    if df.empty:
        logger.info('fact_prices: nothing to load.')
        return 0, 0
    
    loaded = skipped = 0
    
    for _, row in df.iterrows():
        cur = conn.execute(
            '''
            INSERT INTO fact_prices (series_id, date, price, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (series_id, date) DO NOTHING
            ''',
            (
                int(row['series_id']),
                row['date'],
                float(row['value']),
                row['source']
            )
        )
        if cur.rowcount > 0:
            loaded += 1
        else:
            skipped += 1

    logger.info(f'fact_prices: {loaded} loaded, {skipped} skipped (duplicates).')
    return loaded, skipped
