
import logging
import pandas as pd

from src.shared.config_loader import load_pipelines
from src.db.connection import get_connection
from src.db.queries import get_backfill_pending_series, get_registered_securities
from src.pipelines.dim.bloomberg.security.extract import (
    extract_security_attributes,
    load_stg_security_bloomberg,
    read_latest_stg_security_bloomberg
)
from src.pipelines.dim.bloomberg.security.transform import transform_security_attributes
from src.pipelines.dim.bloomberg.security.loaders.dim_security import load_dim_security
from src.pipelines.dim.bloomberg.security.loaders.dim_security_equity import load_dim_security_equity
from src.pipelines.dim.bloomberg.security.loaders.dim_security_fund import load_dim_security_fund
from src.pipelines.dim.bloomberg.security.loaders.dim_entity_identifiers import load_identifiers_from_enrichment
from src.pipelines.dim.bloomberg.security.loaders.series_status import load_series_status_from_enrichment

logger = logging.getLogger(__name__)

def run() -> None:
    '''
    Full dim enrichment run for Bloomberg securities.

    Steps:
        1. Resolve all active bloomberg securities from series_registry
           across all relevant domains (prices, fundamentals)
        2. Extract all fields in one BDP call
        3. Stage raw response to stg_security_bloomberg
        4. Transform: pivot, resolve entity_id, split by target table
        5. Load each dim table - each loader filters by security type
        6. Load identifiers discovered during enrichment
    '''
    logger.info('=== Dim enrichment: bloomberg/security started ===')

    cfg = load_pipelines()['pipelines']['dim']['bloomberg']['security']
    
    fields = []
    for l in cfg.values():
        fields += l
    
    # Step 1: Resolve all registered bloomberg securities across domains
    # dim enrichment is domain-agnostic - same security appears in
    # prices and fundamentals but needs one dim row
    with get_connection() as conn:
        securities = get_registered_securities(conn)
        securities = [s for s in securities if s['parsekyable']]

    # Deduplicate by entity_id - one dim row per security regardless
    # of how many series it appears in
    seen = set()
    unique_securities = []
    for s in securities:
        if s['entity_id'] not in seen:
            seen.add(s['entity_id'])
            unique_securities.append(s)

    if not unique_securities:
        logger.warning('No active bloomberg securities found. Skipping enrichment.')
        return
    
    logger.info(f'Enriching {len(unique_securities)} unique securities.')

    # Step 2: Extract
    raw_df = extract_security_attributes(unique_securities, fields)

    if raw_df.empty:
        logger.warning('Extract returned no data.')
        return
    
    # Step 3: Stage
    with get_connection() as conn:
        load_stg_security_bloomberg(conn, raw_df)

    # Step 4: Transform - reads latest from stg, resolves entity_id    
    with get_connection() as conn:
        stg_df = read_latest_stg_security_bloomberg(conn)
        transformed_dict = transform_security_attributes(stg_df, conn)

    if not transformed_dict:
        logger.warning('Transform returned no data.')
        return
    
    # Steps 5-6: Load each target table in FK dependency order
    # dim_security first (parent), then extension tables (children)
    with get_connection() as conn:
        load_dim_security(conn, transformed_dict.get('dim_security', []))

    with get_connection() as conn:
        load_dim_security_equity(conn, transformed_dict.get('dim_security_equity', []))
        load_dim_security_fund(conn, transformed_dict.get('dim_security_fund', []))

    with get_connection() as conn:
        load_identifiers_from_enrichment(conn, transformed_dict.get('dim_entity_identifiers', []))

    with get_connection() as conn:
        load_series_status_from_enrichment(conn, transformed_dict.get('series_status_updates', [])) # TODO

    logger.info('=== Dim enrichment: bloomberg/security complete ===')

if __name__ == '__main__':
    from src.shared.logging import setup_logging
    setup_logging('dim_bloomberg_security')
    run()
