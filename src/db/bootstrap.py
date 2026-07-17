# src/db/bootstrap.py
# ---------------------------------------------------------------
# Database bootstrap: creates the metadata/tracking tables and loads the
# dimension and series-registry seeds into an empty PostgreSQL database.
# Bootstrap is onboard on an empty DB (see onboard.py).

import logging
from typing import Optional

import pandas as pd
from psycopg import Connection

from src.db.connection import get_connection
from src.db.queries import get_or_create_entity_id, upsert_entity_identifier #, get_entity_id
from src.shared.paths import SCHEMA_DIR
from src.shared.seed_loader import load_series_seed, load_identifiers_seed

logger = logging.getLogger(__name__)

# DB creation -----

def create_db() -> None:
    """
    Initializes metadata tracking table in PostgreSQL.

    Notes:
    - Foreign keys are enforced by default in PG (no PRAGMA needed).
    - WAL is the default journal mode in PG (no PRAGMA needed).
    - synchronous/fsync is configured in postgresql.conf, not per-connection.
    - The database itself must already exist (created via CREATE DATABASE
      or `createdb` CLI before running this function).
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS _metadata (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        cur.execute("""
            INSERT INTO _metadata (key, value)
            VALUES ('db_initialized', 'true')
            ON CONFLICT (key) DO NOTHING;
        """)


# Schema -----

def create_schema(conn: Connection) -> None:
    """
    Executes all SQL files in schema/ in filename order.
    Files are numbered (01_, 02_, ...) to enforce FK dependency order.

    """
    sql_files = sorted(SCHEMA_DIR.glob('*.sql'))
    if not sql_files:
        raise FileNotFoundError(f'No SQL files found in {SCHEMA_DIR}')
    
    cur = conn.cursor()
    for sql_file in sql_files:
        logger.info(f'Executing schema file: {sql_file.name}')
        sql = sql_file.read_text()
        cur.execute(sql)

    logger.info(f'Schema created from {len(sql_files)} files.')

# Pass 1: Skeleton loaders (from seeds) ----------

# Dim entity -----

def load_dim_entity(
    conn: Connection,
    series_df: pd.DataFrame,
) -> dict[tuple, int]:
    """
    Inserts unique (procode, entity_type) pairs into dim_entity.
    Returns a mapping {(procode, entity_type): entity_id} for downstream use.
    """
    unique_entities = (
        series_df[['procode', 'entity_type', 'name']]
        .drop_duplicates(subset=['procode', 'entity_type'])
    )

    

    entity_map = {}
    inserted = 0

    for _, row in unique_entities.iterrows():
        entity_id = get_or_create_entity_id(
            conn,
            procode=row['procode'],
            entity_type=row['entity_type'],
            name=row.get('name'),
        )
        entity_map[(row['procode'], row['entity_type'])] = entity_id
        inserted += 1

    logger.info(f'dim_entity: {inserted} entities resolved.')
    return entity_map



def load_dim_entity_identifiers(
    conn: Connection,
    identifiers_df: pd.DataFrame,
    entity_map: dict[tuple, int],
) -> None:
    """
    Populates dim_entity_identifiers from seeds/identifiers.csv.
    One row per identifier – no sparse columns.
    Called after load_dim_entity so entity_map is available.
    """
    inserted = skipped = 0

    for _, row in identifiers_df.iterrows():
        entity_id = entity_map.get((row['procode'], row['entity_type']))
        if not entity_id:
            logger.warning(
                f'No entity_id for ({row["procode"]}, {row["entity_type"]}) '
                f'in identifiers.csv – skipping {row["id_type"]}'
            )
            skipped += 1
            continue
        upsert_entity_identifier(
            conn,
            entity_id=entity_id,
            id_type=row['id_type'],
            id_value=str(row['id_value']).strip(),
            source=row['source'],
            is_primary=bool(row.get('is_primary', False)),
        )
        inserted += 1

    logger.info(f'dim_entity_identifiers: {inserted} inserted, {skipped} skipped.')

# Dim security -----

def load_dim_security_skeleton(
    conn: Connection,
    series_df: pd.DataFrame,
    entity_map: dict[tuple, int],
) -> None:
    """
    Inserts minimal dim_security rows for entity_type = "security".
    Only columns available from series.csv: security_type.
    All vendor-sourced attributes (sector, exchange, etc.) are left NULL
    and filled in later by the dim enrichment pipeline.

    Uses INSERT … ON CONFLICT DO NOTHING for idempotency (SCD Type 1).

    """

    security_df = (
        series_df[series_df['entity_type'] == 'security']
        .drop_duplicates(subset=['procode', 'entity_type'])
    )

    cur = conn.cursor()
    inserted = 0
    for _, row in security_df.iterrows():
        entity_id = entity_map.get((row['procode'], 'security'))
        if not entity_id:
            logger.warning(f'No entity_id for security {row["procode"]}, skipping.')
            continue

        cur.execute(
            """
            INSERT INTO dim_security (entity_id, security_type)
            VALUES (%s, %s)
            ON CONFLICT (entity_id) DO NOTHING

            """,
            (entity_id, row.get('security_type'))
        )
        inserted += 1
    logger.info(f'dim_security skeleton: {inserted} rows inserted.')

def load_series_registry(
    conn: Connection,
    series_df: pd.DataFrame,
    entity_map: dict[tuple, int]
) -> None:
    """
    Inserts new series into series_registry.
    ON CONFLICT DO NOTHING preserves status of existing rows –
    safe to re-run without overwriting operational state.

    """

    cur = conn.cursor()
    inserted = skipped = 0

    for _, row in series_df.iterrows():
        entity_id = entity_map.get((row['procode'], row['entity_type']))
        if not entity_id:
            logger.warning(
                f'No entity_id for ({row["procode"]}, {row["entity_type"]}), '
                f'skipping series {row["field"]} / {row["source"]}'
            )
            continue
        cur.execute(
            """
            INSERT INTO series_registry (
                entity_id, field, domain, source, frequency,
                default_start_date, status,
                release_pattern, release_lag_days,
                allow_revisions, revision_lookback
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entity_id, field, source) DO NOTHING

            """,
            (
                entity_id,
                row['field'],
                row['domain'],
                row['source'],
                row['frequency'],
                row['default_start_date'].date()
                    if hasattr(row['default_start_date'], 'date')
                    else row['default_start_date'],
                row.get('status', 'backfill-pending'),
                row.get('release_pattern'),
                row.get('release_lag_days'),
                bool(row.get('allow_revisions', False)),
                row.get('revision_lookback'),
            )
        )
        if cur.rowcount > 0:
            inserted += 1
        else:
            skipped += 1
    logger.info(f'series_registry: {inserted} inserted, {skipped} already existed.')

# Pass 2: Dim enrichment dispatch ----------

def run_dim_enrichment(
    vendor: Optional[str] = None,
    domain: Optional[str] = None,
) -> None:

    """
    Dispatches dim enrichment pipelines per vendor × domain combination.
    Each pipeline extracts vendor attributes to stg_* then resolves
    into full dim_security / dim_macro rows.
    Optionally filtered by vendor and/or domain.

    """
    pipelines = _get_enrichment_pipelines(vendor=vendor, domain=domain)

    if not pipelines:
        logger.warning(
            f'No enrichment pipelines found for vendor={vendor} domain={domain}'
        )
        return
    
    for pip in pipelines:
        logger.info(
            f'Running dim enrichment: vendor={pip["vendor"]} domain={pip["domain"]}'
        )
        try:
            pip['run']()
        except Exception as e:
            logger.error(
                f'Dim enrichment failed vendor={pip["vendor"]} '
                f'domain={pip["domain"]}: {e}',
                exc_info=True
            )

def _get_enrichment_pipelines(
    vendor: Optional[str] = None,
    domain: Optional[str] = None,
) -> list:
    """
    Registry of all dim enrichment pipelines.
    Add new entries here as new vendor/domain combinations are added.

    """
    all_pipelines = [
        {
            'vendor': 'bloomberg',
            'domain': 'security',
            'run': _lazy_run('src.pipelines.dim.bloomberg.security.run'),
        }
    ]
    return [
        p for p in all_pipelines
        if (vendor is None or p['vendor'] == vendor)
        and (domain is None or p['domain'] == domain)
    ]

def _lazy_run(module_path: str):
    """Returns a zero-argument callable that imports and runs module.run() lazily."""
    def runner():
        import importlib
        mod = importlib.import_module(module_path)
        mod.run()
    return runner

# Master bootstrap ----------

def run_bootstrap(
    enrich: bool = False,
    enrich_vendor: str = None,
    enrich_domain: str = None,
    run_backfill: bool = False,
    backfill_domain: str = None,
    backfill_source: str = None
) -> None:
    """
    Full bootstrap sequence:

        1. Create schema
        2. Load dim_entity (unique procode/entity_type from series.csv)
        3. Load dim_entity_identifiers (from identifiers.csv - one row per id)
        4. Load dim_security skeleton (security_type only - vendor atts via enrichment)
        5. Load dim_macro
        6. Load series_registry (one row per procode/field/source)
        7. Load source priority
        8. Dim enrichment (opt-in) (vendor extract to stg to dim full attributes)
        9. Fact backfill (opt-in) (prices, fundamentals, macro)

    All steps are idempotent - safe to re-run.
    Steps 8 and 9 are opt-in via flags allowing bootstrap to run
    in stages (schema + seeds first, enrich and backfill later)
    
    """
    logger.info('=== Bootstrap started ===')

    series_df = load_series_seed()
    identifiers_df = load_identifiers_seed()
    logger.info(f'Loaded {len(series_df)} rows from series.csv')

    create_db()

    # FIXME: rationale is a SQLite remnant - psycopg has no executescript, and
    #   get_connection() commits on clean exit regardless. The isolated
    #   connection per step is harmless, but this justification is wrong.
    # Step 1: schema - isolated connection due to executescript implicit COMMIT
    logger.info('--- Step 1: Creating schema ---')
    with get_connection() as conn:
        create_schema(conn)

    # Step 2: dim_entity - one row per unique procode/entity_type
    logger.info('--- Step 2: Loading dim_entity ---')
    with get_connection() as conn:
        entity_map = load_dim_entity(conn, series_df)
    
    # Step 3: identifiers - one row per identifier from identifiers.csv
    logger.info('--- Step 3: Loading dim_entity_identifiers---')
    with get_connection() as conn:
        load_dim_entity_identifiers(conn, identifiers_df, entity_map)

    # Step 4: dim skeletons
    logger.info('--- Step 4: Loading dim_security and dim_macro skeletons ---')
    with get_connection() as conn:
        load_dim_security_skeleton(conn, series_df, entity_map)

    # Step 5: series_registry
    logger.info('--- Step 5: Loading series_registry ---')
    with get_connection() as conn:
        load_series_registry(conn, series_df, entity_map)

    # Step 6: source priority
    # logger.info('--- Step 6: Loading source priority ---')
    # with get_connection() as conn:
    #     pass
     
    logger.info('=== Seed loading complete ===')

    # Step 8: dim enrichment (opt-in)
    if enrich:
        logger.info('--- Step 7: Running dim enrichment ---')
        run_dim_enrichment(vendor=enrich_vendor, domain=enrich_domain)

    # Step 9: fact backfill (opt-in)
    if run_backfill:
        logger.info('--- Step 8: Running fact backfill ---')
        from src.db.onboard import run_backfill_pending
        run_backfill_pending(domain=backfill_domain, source=backfill_source)

    logger.info('=== Bootstrap complete ===')

# Run if main
if __name__ == "__main__":
    from src.shared.logging import setup_logging
    setup_logging('bootstrap_pg')
    run_bootstrap(enrich=False,
                  run_backfill=False)
