
import logging
import pandas as pd

from src.db.queries import upsert_entity_identifier

logger = logging.getLogger(__name__)

def load_identifiers_from_enrichment(conn, df: pd.DataFrame) -> None:
    '''
    Upserts long-format identifier DataFrame into dim_entity_identifiers.
    Called as a side effect of security enrichment - Bloomberg returns
    ISIN, CUSIP, SEDOL or others alongside attribute fields in the BDP call.
    
    :param conn: Connection object
    :param df: Description
    :type df: pd.DataFrame
    '''
    if df.empty:
        logger.info('dim_entity_identifiers: nothing to load from enrichment.')
        return
    
    inserted = 0
    for _, row in df.iterrows():
        upsert_entity_identifier(
            conn,
            entity_id=row['entity_id'],
            id_type=row['id_type'],
            id_value=row['id_value'],
            source=row['source'],
            is_primary=bool(row.get('is_primary', True))
        )
        inserted += 1
    logger.info(f'dim_entity_identifiers: {inserted} identifiers upserted from enrichment.')
