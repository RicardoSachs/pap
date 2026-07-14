
# Incremental series onboarding
# Reuses bootstrap loaders - bootstrap is just onboard on empty DB.
# All seeds loaded upfront by caller and passed as arguments
# for consistency with bootstrap.py pattern.

import logging
from itertools import groupby
from operator import itemgetter

from src.db.connection import get_connection
from src.db.bootstrap import (
    load_dim_entity,
    load_dim_entity_identifiers,
    load_dim_security_skeleton,
    load_series_registry,
    run_dim_enrichment
)
from src.db.queries import get_backfill_pending_series
from src.shared.seed_loader import load_series_seed, load_identifiers_seed

logger = logging.getLogger(__name__)

def run_onboard(
    enrich: bool = False,
    enrich_vendor: str = None,
    enrich_domain: str = None
) -> None:
    '''
    Incremental onboarding: registers new series from seeds.

    Steps:
        1. Load all seeds upfront
        2. Upsert dim_entity for new tickers
        3. Upsert dim_entity_identifiers for new identifiers
        4. Insert dim_security / dim_macro skeletons for new entities
        5. Insert new series_registry rows (preserves existing status)
        6. Upsert source priority rules
        7. Optionally run dim enrichment for new entities

    ON CONFLICT DO NOTHING in series_registry preserves status of
    existing rows - safe to re-run after any series.csv change.

    Does NOT trigger fact backfill - call run_backfill_pending()
    separately or pass --backfill to the entry point script.

    :param enrich: Enrich while onboarding
    :type enrich: bool
    :param enrich_vendor: Vendor to enrich
    :type enrich_vendor: str
    :param enrich_domain: Domain to enrich
    :type enrich_domain: str
    '''
    logger.info('=== Onboarding started ===')

    # Load all seeds upfron - passed as arguments to loaders
    series_df = load_series_seed()
    identifiers_df = load_identifiers_seed()

    logger.info(
        f'Seeds loaded: {len(series_df)} series, '
        f'{len(identifiers_df)} identifiers.'
    )

    with get_connection() as conn:
        entity_map = load_dim_entity(conn, series_df)

    with get_connection() as conn:
        load_dim_entity_identifiers(conn, identifiers_df, entity_map)
    
    with get_connection() as conn:
        load_dim_security_skeleton(conn, series_df, entity_map)

    with get_connection() as conn:
        load_series_registry(conn, series_df, entity_map)

    logger.info('=== Onboarding complete ===')

    if enrich:
        logger.info('--- Running dim enrichment ---')
        run_dim_enrichment(vendor=enrich_vendor, domain=enrich_domain)

def run_backfill_pending(
    domain: str = None,
    source: str = None,
) -> None:
    '''
    Triggers fact backfill pipelines for all backfill-pending series.
    Groups by domain + source to minimise pipeline invocations.
    Optionally filtered by domain and/or source.
    '''
    with get_connection() as conn:
        pending = get_backfill_pending_series(conn, domain=domain, source=source)

    if not pending:
        logger.info('No backfill-pending series found.')
        return
    
    logger.info(f'Found {len(pending)} backfill-pending series.')

    pending_sorted = sorted(pending, key=itemgetter('domain', 'source', 'frequency'))

    for (grp_domain, grp_source), group in groupby(
        pending_sorted, key=itemgetter('domain', 'source')
    ):
        series_list = list(group)
        logger.info(
            f'Backfilling {len(series_list)} series: '
            f'domain={grp_domain} source={grp_source}'
        )
        _dispatch_backfill(grp_domain, grp_source, series_list)

def _get_fact_pipeplines() -> list[dict]:
    '''
    Registry of all fact pipelines.
    One entry per domain/source combination

    frrquency_aware=True: pipeline run() requires a frequency argument
    and is dispatched once per frequency group within the series list.
    frequency_aware=False: pipeline run() receives the full series list
    and handles any frequency variation internally.

    Add new entries here as new domain/source combinations are added.
    _dispatch_backfill() never needs to change.
    '''
    return [
        {
            'domain': 'prices',
            'source': 'bloomberg',
            'frequency_aware': False,
            'run': _lazy_run('src.pipelines.prices.bloomberg.run')

        }
    ]

def _lazy_run(module_path: str):
    '''
    Returns a callable that lazily imports and runs module.run(**kwargs).
    Avoids importing all pipeline modules at onboard load time.
    Accepts kwargs so the same wrapper works for both frequency-aware
    and non-frequency-aware pipelines.
    '''
    def runner(**kwargs):
        import importlib
        mod = importlib.import_module(module_path)
        mod.run(**kwargs)
    return runner

def _dispatch_backfill(domain: str, source: str, series_list: list[dict]) -> None:
    '''
    Routes to the correct fact pipeline via the registry.
    For frequency_aware pipelines. splits series_list by frequency
    and dispatches once per group.
    For non-frequency-aware pipelines, passes the full list.
    '''
    from datetime import date, timedelta
    run_date = date.today() - timedelta(days=1)

    pipeline = next(
        (
            p for p in _get_fact_pipeplines()
            if p['domain'] == domain and p['source'] == source
        ),
        None
    )

    if not pipeline:
        logger.warning(
            f'No backfill handler for domain={domain} source={source}. '
            f'Add an entry to _get_fact_pipelines() in onboard.py'
        )
        return
    
    try:
        if pipeline['frequency_aware']:
            freq_sorted = sorted(series_list, key=itemgetter('frequency'))
            for freq, grp in groupby(freq_sorted, key=itemgetter('frequency')):
                freq_list = list(grp)
                logger.info(
                    f'Dispatching frequency={freq} '
                    f'({len(freq_list)} series) to {domain}/{source}.'
                )
                pipeline['run'](
                    run_date=run_date,
                    frequency = freq,
                    series_override=series_list
                )
        else:
            pipeline['run'](
                run_date=run_date,
                series_override=series_list,
            )
    
    except Exception as e:
        logger.error(
            f'Backfill failed for domain={domain} source={source}: {e}',
            exc_info=True
        )

if __name__ == '__main__':
    with get_connection() as conn:
        print(get_backfill_pending_series(conn))
