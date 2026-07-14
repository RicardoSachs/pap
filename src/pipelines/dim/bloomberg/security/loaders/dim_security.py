
import logging
import pandas as pd


logger = logging.getLogger(__name__)

def load_dim_security(conn, df: pd.DataFrame) -> None:
    '''
    Upserts shared security attributes into dim_security.
    Matches on entity_id SCD Type 1 - overwrites in place.
    
    :param conn: Description
    :param df: Description
    :type df: pd.DataFrame
    '''
    if df.empty:
        logger.info('dim_security: nothing to load')
        return
    
    updated = 0
    for _, row in df.iterrows():
        conn.execute(
            '''
            INSERT INTO dim_security (
                entity_id,
                ticker,
                name,
                short_name,
                security_name,
                sec_num_des,
                currency,
                country,
                exchange,
                market_sector,
                security_type
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entity_id) DO UPDATE SET
                ticker        = COALESCE(EXCLUDED.ticker, dim_security.ticker),
                name          = COALESCE(EXCLUDED.name, dim_security.name),
                short_name    = COALESCE(EXCLUDED.short_name, dim_security.short_name),
                security_name = COALESCE(EXCLUDED.security_name, dim_security.security_name),
                sec_num_des   = COALESCE(EXCLUDED.sec_num_des, dim_security.sec_num_des),
                currency      = COALESCE(EXCLUDED.currency, dim_security.currency),
                country       = COALESCE(EXCLUDED.country, dim_security.country),
                exchange      = COALESCE(EXCLUDED.exchange, dim_security.exchange),
                market_sector = COALESCE(EXCLUDED.market_sector, dim_security.market_sector),
                security_type = COALESCE(EXCLUDED.security_type, dim_security.security_type),
                updated_at    = NOW()
            ''',
            (
                row['entity_id'],
                row['ticker'],
                row['name'],
                row['short_name'],
                row['security_name'],
                row['sec_num_des'],
                row['currency'],
                row['country'],
                row['exchange'],
                row['market_sector'],
                row['security_type']
            )
        )
        updated += 1
    logger.info(f'dim_security: {updated} rows upserted.')

