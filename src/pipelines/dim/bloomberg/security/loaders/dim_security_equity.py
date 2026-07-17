# src/pipelines/dim/bloomberg/security/loaders/dim_security_equity.py
# ---------------------------------------------------------------
# Loader: upserts equity-extension attributes into dim_security_equity.

import logging
import pandas as pd

logger = logging.getLogger(__name__)

def load_dim_security_equity(conn, df: pd.DataFrame) -> None:
    """
    Upserts equity extension attributes.
    Skip rows where security_id cannot be resolved from entity_id.
    
    :param conn: Connection object
    :param df: Staging bloomberg table
    :type df: pd.DataFrame
    """
    if df.empty:
        logger.info('dim_security_equity: nothing to load.')
        return
    
    updated = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            'SELECT security_id FROM dim_security WHERE entity_id = %s',
            (row['entity_id'],)
        )
        sec = cur.fetchone()
        if not sec:
            continue

        conn.execute(
            """
            INSERT INTO dim_security_equity (
                security_id, sector
            ) VALUES (%s, %s)
            ON CONFLICT (security_id) DO UPDATE SET
                sector = COALESCE(excluded.sector, sector),
                updated_at = NOW()
            """,
            (
                sec['security_id'],
                row.get('sector')
            )
        )
        updated += 1
    logger.info(f'dim_security_equity: {updated} rows upserted.')
