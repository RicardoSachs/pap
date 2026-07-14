

from psycopg import sql
from psycopg import Connection as connection
from datetime import date
from typing import Optional
                                                                   # CHANGED: removed `import sqlite3`

# ── Entity ──────────────────────────────────────────────────────

def get_or_create_entity_id(
    conn: connection,
    procode: str,
    entity_type: str,
    name: Optional[str] = None,
) -> int:
    '''
    Returns entity_id for an existing (procode, entity_type) pair,
    or inserts a new row and returns the new entity_id.
    Always safe to call multiple times – idempotent.
    '''
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT entity_id
        FROM dim_entity
        WHERE procode = %s AND entity_type = %s
        ''',
        (procode, entity_type),
    )
    row = cur.fetchone()

    if row:
        return row['entity_id']

    cur.execute(
        '''
        INSERT INTO dim_entity (procode, entity_type, name)
        VALUES (%s, %s, %s)
        RETURNING entity_id
        ''',
        (procode, entity_type, name),
    )
    return cur.fetchone()['entity_id']


# ── Entity identifiers ─────────────────────────────────────────

def resolve_entity_id_from_identifier(
    conn: connection,
    id_type: str,
    id_value: str,
    source: Optional[str] = None,
) -> Optional[int]:
    '''
    Reverse lookup: given a vendor identifier value, returns entity_id.
    Optionally scoped by source for disambiguation.
    '''
    cur = conn.cursor()
    if source:
        cur.execute(
            '''
            SELECT entity_id FROM dim_entity_identifiers
            WHERE id_type = %s AND id_value = %s AND source = %s
            ''',
            (id_type, id_value, source),
        )
    else:
        cur.execute(
            '''
            SELECT entity_id FROM dim_entity_identifiers
            WHERE id_type = %s AND id_value = %s
            ''',
            (id_type, id_value),
        )

    row = cur.fetchone()
    return row['entity_id'] if row else None


def get_last_loaded_date(conn: connection, security_id: int, table: str):
    '''
    Returns the most recent date loaded for a given security_id.
    Uses psycopg2.sql.Identifier to safely inject the table name.
    '''
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            '''
            SELECT MAX(date) AS max_date
            FROM {tbl}
            WHERE security_id = %s
            '''
        ).format(tbl=sql.Identifier(table)),
        (security_id,),
    )
    return cur.fetchone()['max_date']


def upsert_entity_identifier(
    conn: connection,
    entity_id: int,
    id_type: str,
    id_value: str,
    source: str,
    is_primary: bool = False,
) -> None:
    '''
    Inserts or updates a single identifier mapping.
    Called by bootstrap seed loader and enrichment pipelines.
    '''
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO dim_entity_identifiers
            (entity_id, id_type, id_value, source, is_primary)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (entity_id, id_type, source) DO UPDATE SET
            id_value   = EXCLUDED.id_value,
            is_primary = EXCLUDED.is_primary
        ''',
        (entity_id, id_type, id_value, source, is_primary),
    )


# ── Series registry ────────────────────────────────────────────

def get_series_id():
    return


def get_active_series(
    conn: connection,
    domain: str,
    source: str,
    frequency: str,
) -> list[dict]:
    '''
    Primary runtime query for pipeline run.py files.
    Returns all active series for a domain/source/frequency combination.
    '''
    query = """
        SELECT
            sr.series_id,
            sr.entity_id,
            e.procode,
            e.name,
            sr.field,
            sr.domain,
            sr.source,
            sr.frequency,
            sr.default_start_date,
            sr.release_pattern,
            sr.allow_revisions,
            sr.revision_lookback,
            bbg.id_value        AS parsekyable,
            isin.id_value       AS isin,
            codigo_sbs.id_value AS codigo_sbs
        FROM series_registry sr
        JOIN dim_entity e ON sr.entity_id = e.entity_id
        LEFT JOIN dim_entity_identifiers bbg
            ON  bbg.entity_id = sr.entity_id
            AND bbg.id_type   = 'parsekyable'
            AND bbg.source    = 'bloomberg'
        LEFT JOIN dim_entity_identifiers isin
            ON  isin.entity_id = sr.entity_id
            AND isin.id_type   = 'isin'
            AND isin.source    = 'internal'
        LEFT JOIN dim_entity_identifiers codigo_sbs
            ON  codigo_sbs.entity_id = sr.entity_id
            AND codigo_sbs.id_type   = 'codigo_sbs'
            AND codigo_sbs.source    = 'sbs'
        WHERE sr.domain    = %s
          AND sr.source    = %s
          AND sr.frequency = %s
          AND sr.status    = 'active'
        ORDER BY sr.series_id
    """
    cur = conn.cursor()
    cur.execute(query, (domain, source, frequency))
    return cur.fetchall()


def get_backfill_pending_series(
    conn: connection,
    domain: Optional[str] = None,
    source: Optional[str] = None,
) -> list[dict]:
    '''
    Returns all backfill-pending series with resolved identifiers.
    Optionally filtered by domain and/or source.
    '''
    query = """
        SELECT
            sr.series_id,
            sr.entity_id,
            e.procode,
            e.name,
            sr.field,
            sr.domain,
            sr.source,
            sr.frequency,
            sr.default_start_date,
            sr.release_pattern,
            sr.allow_revisions,
            sr.revision_lookback,
            bbg.id_value        AS parsekyable,
            isin.id_value       AS isin,
            codigo_sbs.id_value AS codigo_sbs
        FROM series_registry sr
        JOIN dim_entity e ON sr.entity_id = e.entity_id
        LEFT JOIN dim_entity_identifiers bbg
            ON  bbg.entity_id = sr.entity_id
            AND bbg.id_type   = 'parsekyable'
            AND bbg.source    = 'bloomberg'
        LEFT JOIN dim_entity_identifiers isin
            ON  isin.entity_id = sr.entity_id
            AND isin.id_type   = 'isin'
            AND isin.source    = 'internal'
        LEFT JOIN dim_entity_identifiers codigo_sbs
            ON  codigo_sbs.entity_id = sr.entity_id
            AND codigo_sbs.id_type   = 'codigo_sbs'
            AND codigo_sbs.source    = 'sbs'
        WHERE sr.status = 'backfill-pending'
    """
    params: list = []
    if domain:
        query += ' AND sr.domain = %s'
        params.append(domain)
    if source:
        query += ' AND sr.source = %s'
        params.append(source)
    query += ' ORDER BY sr.series_id'

    cur = conn.cursor()
    cur.execute(query, params)
    return cur.fetchall()


def get_suspended_series(
    conn: connection,                                              # CHANGED: was untyped in some places
    domain: Optional[str] = None,
    source: Optional[str] = None,
) -> list[dict]:
    """
    Returns all series with status = suspended.
    """
    query = """
        SELECT
            sr.series_id,
            sr.entity_id,
            e.procode,
            e.name,
            sr.field,
            sr.source,
            sr.domain,
            sr.frequency,
            sr.updated_at       AS status_changed_at,
            bbg.id_value        AS parsekyable
        FROM series_registry sr
        JOIN dim_entity e
          ON sr.entity_id = e.entity_id
        LEFT JOIN dim_entity_identifiers bbg
            ON  bbg.entity_id = sr.entity_id
            AND bbg.id_type   = 'parsekyable'
            AND bbg.source    = 'bloomberg'
        WHERE sr.status = 'suspended'
    """
    params: list = []
    if domain:
        query += " AND sr.domain = %s"                             # CHANGED: ? → %s
        params.append(domain)
    if source:
        query += " AND sr.source = %s"                             # CHANGED: ? → %s
        params.append(source)
    query += " ORDER BY sr.updated_at DESC"

    cur = conn.cursor()                                            # CHANGED: conn.execute → cursor pattern
    cur.execute(query, params)                                     # CHANGED
    return cur.fetchall()                                          # CHANGED: removed [dict(r) for r in rows]


def get_inactive_series(
    conn: connection,                                              # CHANGED: added type hint
    domain: Optional[str] = None,
    source: Optional[str] = None,
) -> list[dict]:
    """
    Returns all series with status = inactive.
    """
    query = """
        SELECT
            sr.series_id,
            sr.entity_id,
            e.procode,
            e.name,
            sr.field,
            sr.source,
            sr.domain,
            sr.updated_at       AS inactivated_at,
            bbg.id_value        AS parsekyable
        FROM series_registry sr
        JOIN dim_entity e
          ON sr.entity_id = e.entity_id
        LEFT JOIN dim_entity_identifiers bbg
            ON  bbg.entity_id = sr.entity_id
            AND bbg.id_type   = 'parsekyable'
            AND bbg.source    = 'bloomberg'
        WHERE sr.status = 'inactive'
    """
    params: list = []
    if domain:
        query += " AND sr.domain = %s"                             # CHANGED: ? → %s
        params.append(domain)
    if source:
        query += " AND sr.source = %s"                             # CHANGED: ? → %s
        params.append(source)
    query += " ORDER BY sr.updated_at DESC"

    cur = conn.cursor()                                            # CHANGED
    cur.execute(query, params)                                     # CHANGED
    return cur.fetchall()                                          # CHANGED


def get_error_hold_series(
    conn: connection,                                              # CHANGED: added type hint
    domain: Optional[str] = None,
    source: Optional[str] = None,
) -> list[dict]:
    """
    Returns all series with status = error-hold.
    """
    query = """
        SELECT
            sr.series_id,
            sr.entity_id,
            e.procode,
            e.name,
            sr.field,
            sr.source,
            sr.domain,
            sr.last_run_at,
            sr.updated_at       AS error_at,
            bbg.id_value        AS parsekyable
        FROM series_registry sr
        JOIN dim_entity e
          ON sr.entity_id = e.entity_id
        LEFT JOIN dim_entity_identifiers bbg
            ON  bbg.entity_id = sr.entity_id
            AND bbg.id_type   = 'parsekyable'
            AND bbg.source    = 'bloomberg'
        WHERE sr.status = 'error-hold'
    """
    params: list = []
    if domain:
        query += " AND sr.domain = %s"                             # CHANGED: ? → %s
        params.append(domain)
    if source:
        query += " AND sr.source = %s"                             # CHANGED: ? → %s
        params.append(source)
    query += " ORDER BY sr.updated_at DESC"

    cur = conn.cursor()                                            # CHANGED
    cur.execute(query, params)                                     # CHANGED
    return cur.fetchall()                                          # CHANGED


def get_registered_securities(
    conn: connection,                                              # CHANGED: sqlite3.Connection → connection
) -> list[dict]:
    '''
    Returns all securities registered in dim_security regardless
    of series_registry status, domain, source or frequency.
    Used exclusively by dim enrichment pipelines.
    Each security appears once – deduplication is by entity_id.
    '''
    cur = conn.cursor()                                            # CHANGED
    cur.execute(                                                   # CHANGED
        """
        SELECT DISTINCT
            e.entity_id,
            e.procode,
            e.name,
            ds.security_type,
            bbg.id_value AS parsekyable
        FROM dim_entity e
        JOIN dim_security ds ON ds.entity_id = e.entity_id
        LEFT JOIN dim_entity_identifiers bbg
            ON  bbg.entity_id = e.entity_id
            AND bbg.id_type   = 'parsekyable'
            AND bbg.source    = 'bloomberg'
        WHERE e.entity_type = 'security'
        ORDER BY e.entity_id
        """
    )
    return cur.fetchall()                                          # CHANGED


def update_series_status(
    conn: connection,                                              # CHANGED: sqlite3.Connection → connection
    series_id: int,
    status: str,
) -> None:
    cur = conn.cursor()                                            # CHANGED
    cur.execute(                                                   # CHANGED
        '''
        UPDATE series_registry
        SET status     = %s,
            updated_at = NOW()
        WHERE series_id = %s
        ''',                                                       # CHANGED: ? → %s, datetime("now") → NOW()
        (status, series_id),
    )


def update_series_run_metadata(
    conn: connection,                                              # CHANGED: sqlite3.Connection → connection
    series_id: int,
    run_status: str,
    last_loaded_date: Optional[date] = None,
) -> None:
    '''
    Called by loaders after each pipeline run to track operational state.
    '''
    cur = conn.cursor()                                            # CHANGED
    cur.execute(                                                   # CHANGED
        '''
        UPDATE series_registry
        SET last_run_at       = NOW(),
            last_run_status   = %s,
            last_loaded_date  = COALESCE(%s, last_loaded_date),
            updated_at        = NOW()
        WHERE series_id = %s
        ''',                                                       # CHANGED: ? → %s, datetime("now") → NOW()
        (
            run_status,
            last_loaded_date,                                      # CHANGED: removed .isoformat() — psycopg2 handles date natively
            series_id,
        ),
    )


# ── Fact tables ─────────────────────────────────────────────────

def get_last_price_date(
    conn: connection,                                              # CHANGED: sqlite3.Connection → connection
    series_id: int,
) -> Optional[date]:
    cur = conn.cursor()                                            # CHANGED
    cur.execute(                                                   # CHANGED
        '''
        SELECT MAX(date) AS last_date
        FROM fact_prices
        WHERE series_id = %s
        ''',                                                       # CHANGED: ? → %s
        (series_id,),
    )
    row = cur.fetchone()                                           # CHANGED
    if row and row['last_date']:
        return row['last_date']                                    # CHANGED: removed date.fromisoformat() — psycopg2 returns date natively
    return None
