# src/pipelines/dim/bloomberg/security/loaders/dim_security_fund.py
# ---------------------------------------------------------------
# Loader: upserts fund-extension attributes into dim_security_fund.

import logging
import pandas as pd

logger = logging.getLogger(__name__)

def load_dim_security_fund(conn, df: pd.DataFrame) -> None:
    """
    Upserts fund extension attributes.
    Skip rows where security_id cannot be resolved from entity_id.
    
    :param conn: Connection object
    :param df: Staging bloomberg table
    :type df: pd.DataFrame
    """
    if df.empty:
        logger.info('dim_security_fund: nothing to load.')
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
            INSERT INTO dim_security_fund (
                security_id, fund_type, asset_class, geography, objective
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (security_id) DO UPDATE SET
                fund_type   = COALESCE(EXCLUDED.fund_type, dim_security_fund.fund_type),
                asset_class = COALESCE(EXCLUDED.asset_class, dim_security_fund.asset_class),
                geography   = COALESCE(EXCLUDED.geography, dim_security_fund.geography),
                objective   = COALESCE(EXCLUDED.objective, dim_security_fund.objective),
                updated_at  = NOW()
            """,
            (
                sec['security_id'],
                row.get('fund_type'),
                row.get('asset_class'),
                row.get('geography'),
                row.get('objective'),
            ),
        )
        updated += 1
    logger.info(f'dim_security_fund: {updated} rows upserted.')
