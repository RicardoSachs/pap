# src/db/onboard.py
# ---------------------------------------------------------------
# Incremental series onboarding
# Reuses bootstrap loaders - bootstrap is just onboard on empty DB.
# All seeds loaded upfront by caller and passed as arguments
# for consistency with bootstrap.py pattern.

import logging
import re
from datetime import date
from itertools import groupby
from operator import itemgetter

import pandas as pd

from src.db.connection import get_connection
from src.db.bootstrap import (
    load_dim_entity,
    load_dim_entity_identifiers,
    load_dim_security_skeleton,
    load_series_registry,
    run_dim_enrichment
)
from src.db.queries import (
    get_backfill_pending_series,
    get_entity_id,
    resolve_entity_id_from_identifier,
)
from src.shared.seed_loader import load_series_seed, load_identifiers_seed

logger = logging.getLogger(__name__)

def run_onboard(
    enrich: bool = False,
    enrich_vendor: str = None,
    enrich_domain: str = None
) -> None:
    """
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
    """
    logger.info('=== Onboarding started ===')

    # Load all seeds upfron - passed as arguments to loaders
    series_df = load_series_seed()
    identifiers_df = load_identifiers_seed()

    logger.info(
        f'Seeds loaded: {len(series_df)} series, '
        f'{len(identifiers_df)} identifiers.'
    )

    with get_connection() as conn:
        entity_map = load_dim_entity(conn, series_df, identifiers_df)

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
    """
    Triggers fact backfill pipelines for all backfill-pending series.
    Groups by domain + source to minimise pipeline invocations.
    Optionally filtered by domain and/or source.
    """
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
    """
    Registry of all fact pipelines.
    One entry per domain/source combination

    frrquency_aware=True: pipeline run() requires a frequency argument
    and is dispatched once per frequency group within the series list.
    frequency_aware=False: pipeline run() receives the full series list
    and handles any frequency variation internally.

    Add new entries here as new domain/source combinations are added.
    _dispatch_backfill() never needs to change.
    """
    return [
        {
            'domain': 'prices',
            'source': 'bloomberg',
            'frequency_aware': False,
            'run': _lazy_run('src.pipelines.prices.bloomberg.run')

        }
    ]

def _lazy_run(module_path: str):
    """
    Returns a callable that lazily imports and runs module.run(**kwargs).
    Avoids importing all pipeline modules at onboard load time.
    Accepts kwargs so the same wrapper works for both frequency-aware
    and non-frequency-aware pipelines.
    """
    def runner(**kwargs):
        import importlib
        mod = importlib.import_module(module_path)
        mod.run(**kwargs)
    return runner

def _dispatch_backfill(domain: str, source: str, series_list: list[dict]) -> None:
    """
    Routes to the correct fact pipeline via the registry.
    For frequency_aware pipelines. splits series_list by frequency
    and dispatches once per group.
    For non-frequency-aware pipelines, passes the full list.
    """
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

# ---- One series at a time, from the tablero -----------------------
# The Benchmarks module registers a Bloomberg ticker a basket needs
# without the seed CSV round trip: the same four loaders run on a
# one-row frame, so the rows come out exactly as onboard_series.py
# would write them from series.csv / identifiers.csv. The series is
# born 'backfill-pending' and nothing here talks to Bloomberg: the
# terminal machine's backfill run (run_prices.py --source bloomberg
# --backfill) fetches the history and flips it to 'active', and the
# daily prices_bloomberg job keeps it current from then on.

ENTITY_TYPES = ('security', 'index', 'fund')
PROCODE_PATTERN = re.compile(r'[A-Z0-9][A-Z0-9_.\-]*')
ISIN_PATTERN = re.compile(r'[A-Z]{2}[A-Z0-9]{9}[0-9]')


class SeriesConflict(ValueError):
    """The identifier already names a DIFFERENT entity."""


def normalize_series_spec(spec: dict, today: date | None = None) -> dict:
    """
    Validates and normalizes one Bloomberg series as the tablero sends it:
    {'procode', 'name', 'parsekyable', 'default_start_date',
     'entity_type'?, 'security_type'?, 'isin'?}.
    Raises ValueError naming the field. Pure - no database.
    """
    today = today or date.today()
    procode = str(spec.get('procode') or '').strip().upper()
    if not PROCODE_PATTERN.fullmatch(procode):
        raise ValueError(
            "procode: letters, digits, '_', '.' or '-', no spaces (e.g. SPY_US).")
    name = ' '.join(str(spec.get('name') or '').split())
    if not name:
        raise ValueError('name: cannot be blank.')
    parsekyable = ' '.join(str(spec.get('parsekyable') or '').split())
    if not parsekyable:
        raise ValueError(
            "parsekyable: the Bloomberg ticker is required (e.g. 'SPY US Equity').")
    entity_type = str(spec.get('entity_type') or 'security').strip().lower()
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type: one of {', '.join(ENTITY_TYPES)}.")
    start = spec.get('default_start_date')
    if isinstance(start, str):
        try:
            start = date.fromisoformat(start.strip())
        except ValueError:
            raise ValueError('default_start_date: YYYY-MM-DD.') from None
    if not isinstance(start, date):
        raise ValueError('default_start_date: the first date to fetch is required.')
    if start > today:
        raise ValueError('default_start_date: cannot be in the future.')
    security_type = ' '.join(str(spec.get('security_type') or '').split()) or None
    isin = str(spec.get('isin') or '').strip().upper() or None
    if isin and not ISIN_PATTERN.fullmatch(isin):
        raise ValueError(
            'isin: 12 characters - two letters, nine alphanumerics, a check digit.')
    return {
        'procode': procode, 'name': name, 'parsekyable': parsekyable,
        'entity_type': entity_type, 'default_start_date': start,
        'security_type': security_type, 'isin': isin,
    }


def register_series(conn, spec: dict, source: str = 'bloomberg') -> dict:
    """
    Registers ONE priced series through the bootstrap loaders: the entity
    (adopting an SBS-discovered one when the ISIN matches, as the seeds
    do), its identifiers (the parsekyable under `source`, the ISIN under
    'internal' when given), the dim_security skeleton and the
    series_registry row - PX_LAST / prices / daily / 'backfill-pending'.
    PX_LAST because the Bloomberg extract requests that field alone.

    Idempotent: an existing series is reported (created=False), never
    duplicated, and its status is left alone. Refuses with SeriesConflict
    a parsekyable that already names a different entity, so two procodes
    can never fetch the same ticker.

    Returns {'series_id', 'entity_id', 'procode', 'parsekyable', 'created'}.
    """
    s = normalize_series_spec(spec)
    key = (s['procode'], s['entity_type'])

    owner = resolve_entity_id_from_identifier(
        conn, 'parsekyable', s['parsekyable'], source)
    mine = get_entity_id(conn, s['procode'], s['entity_type'])
    if owner is not None and owner != mine:
        cur = conn.cursor()
        cur.execute('SELECT procode FROM dim_entity WHERE entity_id = %s', (owner,))
        raise SeriesConflict(
            f"{s['parsekyable']} is already registered as "
            f"{cur.fetchone()['procode']}.")

    series_df = pd.DataFrame([{
        'procode': s['procode'], 'entity_type': s['entity_type'], 'name': s['name'],
        'field': 'PX_LAST', 'domain': 'prices', 'source': source, 'frequency': 'daily',
        'default_start_date': s['default_start_date'], 'status': 'backfill-pending',
        'security_type': s['security_type'], 'release_pattern': None,
        'release_lag_days': None, 'allow_revisions': False, 'revision_lookback': None,
    }])
    identifiers = [{'procode': s['procode'], 'entity_type': s['entity_type'],
                    'id_type': 'parsekyable', 'id_value': s['parsekyable'],
                    'source': source, 'is_primary': True}]
    if s['isin']:
        identifiers.append({'procode': s['procode'], 'entity_type': s['entity_type'],
                            'id_type': 'isin', 'id_value': s['isin'],
                            'source': 'internal', 'is_primary': True})
    identifiers_df = pd.DataFrame(identifiers)

    def series_id_of(entity_id: int):
        cur = conn.cursor()
        cur.execute(
            'SELECT series_id FROM series_registry '
            'WHERE entity_id = %s AND field = %s AND source = %s',
            (entity_id, 'PX_LAST', source))
        row = cur.fetchone()
        return row['series_id'] if row else None

    entity_map = load_dim_entity(conn, series_df, identifiers_df)
    entity_id = entity_map[key]
    existing = series_id_of(entity_id)
    load_dim_entity_identifiers(conn, identifiers_df, entity_map)
    load_dim_security_skeleton(conn, series_df, entity_map)
    load_series_registry(conn, series_df, entity_map)
    series_id = series_id_of(entity_id)
    logger.info(
        f"register_series: {s['procode']} ({s['parsekyable']}) -> series_id={series_id} "
        f"{'created' if existing is None else 'already registered'}")
    return {'series_id': series_id, 'entity_id': entity_id, 'procode': s['procode'],
            'parsekyable': s['parsekyable'], 'created': existing is None}


if __name__ == "__main__":
    with get_connection() as conn:
        print(get_backfill_pending_series(conn))
