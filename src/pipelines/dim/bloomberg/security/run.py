# src/pipelines/dim/bloomberg/security/run.py
# ---------------------------------------------------------------
# Orchestrates the Bloomberg security-dimension pipeline: extract
# attributes, transform, and load dim_security and its equity/fund/
# identifier extensions.
#
# Two selection modes (docs/BLOOMBERG_SBS.md):
#   'new'      (default, the Monday scheduler job) entities never asked
#              about, plus unrecognised ones past retry_days. After the
#              one-time pass over the SBS-discovered universe this is a
#              trickle of new instruments.
#   'refresh'  entities with a non-terminal Bloomberg series (the recently
#              held set). On demand: run_dim_enrichment.py --refresh. The
#              configured attributes change rarely; market status is the
#              exception and is covered here until a price-gap signal in
#              the daily Bloomberg run takes it over.
# Every request leaves a '_REQUESTED' sentinel in staging, answered or
# not, so 'new' never re-asks what Bloomberg already said it doesn't know.

import logging
from datetime import datetime

import pandas as pd

from src.shared.config_loader import load_pipelines
from src.db.connection import get_connection
from src.db.queries import get_securities_to_enrich
from src.pipelines.dim.bloomberg.security.extract import (
    extract_security_attributes,
    load_stg_security_bloomberg,
    read_latest_stg_security_bloomberg,
    sentinel_rows,
)
from src.pipelines.dim.bloomberg.security.transform import transform_security_attributes
from src.pipelines.dim.bloomberg.security.loaders.dim_security import load_dim_security
from src.pipelines.dim.bloomberg.security.loaders.dim_security_equity import load_dim_security_equity
from src.pipelines.dim.bloomberg.security.loaders.dim_security_fund import load_dim_security_fund
from src.pipelines.dim.bloomberg.security.loaders.dim_entity_identifiers import load_identifiers_from_enrichment
from src.pipelines.dim.bloomberg.security.loaders.series_status import load_series_status_from_enrichment

logger = logging.getLogger(__name__)

def run(mode: str = 'new', retry_days: int = 90) -> None:
    """
    Dim enrichment run for Bloomberg securities.

    Steps:
        1. Select securities per `mode` (see module banner)
        2. Extract all fields via chunked BDP calls
        3. Stage raw response + one request sentinel per security
        4. Transform (this run's securities only): pivot, resolve
           entity_id, split by target table
        5. Load each dim table - each loader filters by security type
        6. Load identifiers discovered during enrichment
    """
    logger.info(f'=== Dim enrichment: bloomberg/security started | mode={mode} ===')

    cfg = load_pipelines()['pipelines']['dim']['bloomberg']['security']

    fields = []
    for l in cfg.values():
        fields += l

    # Step 1: select per mode (every row has a current parsekyable)
    with get_connection() as conn:
        securities = get_securities_to_enrich(conn, mode=mode, retry_days=retry_days)

    # Deduplicate by entity_id - one dim row per security regardless
    # of how many series it appears in
    seen = set()
    unique_securities = []
    for s in securities:
        if s['entity_id'] not in seen:
            seen.add(s['entity_id'])
            unique_securities.append(s)

    if not unique_securities:
        logger.info(f'mode={mode}: nothing to enrich.')
        return

    logger.info(f'Enriching {len(unique_securities)} unique securities.')
    requested = [s['parsekyable'] for s in unique_securities]

    # Step 2: Extract
    raw_df = extract_security_attributes(unique_securities, fields)
    answered = set(raw_df['parsekyable']) if not raw_df.empty else set()
    logger.info(f'{len(answered)} of {len(requested)} securities answered by Bloomberg.')

    # Step 3: Stage - response rows plus the request sentinel for every
    # security asked, so unrecognised ones are not re-asked next week.
    loaded_at = datetime.now().isoformat(timespec='seconds')
    with get_connection() as conn:
        load_stg_security_bloomberg(
            conn, pd.concat([raw_df, sentinel_rows(requested, answered, loaded_at)],
                            ignore_index=True),
        )

    if raw_df.empty:
        logger.warning('Extract returned no data; sentinels staged, nothing to load.')
        return

    # Step 4: Transform - latest staged values for THIS run's securities
    with get_connection() as conn:
        stg_df = read_latest_stg_security_bloomberg(conn, parsekyables=requested)
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

if __name__ == "__main__":
    from src.shared.logging import setup_logging
    setup_logging('dim_bloomberg_security')
    run()
