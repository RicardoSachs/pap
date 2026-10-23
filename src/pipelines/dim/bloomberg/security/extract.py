# src/pipelines/dim/bloomberg/security/extract.py
# ---------------------------------------------------------------
# Bloomberg security-attribute extraction: BDP reference calls in chunks
# of BDP_CHUNK securities (long-format), plus staging load/read helpers.
#
# Every request leaves a SENTINEL row in stg_security_bloomberg
# (field '_REQUESTED', value 'answered' | 'no_data') for each parsekyable
# asked, whether or not Bloomberg answered. That is what lets
# queries.get_securities_to_enrich tell "never asked" from "asked, not
# recognised" and stop re-asking the latter every week. Readers exclude
# the sentinel field.
# ---------------------------------------------------------------

import logging
import pandas as pd
from datetime import datetime

from src.db.connection import get_connection
from src.db.queries import get_backfill_pending_series
from src.vendors.bloomberg import data_request, fetch_reference_request

logger = logging.getLogger(__name__)

# Securities per BDP request. The one-time pass over the SBS universe is
# thousands of ISINs; one request that size is where the terminal API
# starts failing or truncating. Reference requests are cheap per chunk.
BDP_CHUNK = 250
SENTINEL_FIELD = '_REQUESTED'


def extract_security_attributes(
    securities: list[dict],
    fields: list[str],
) -> pd.DataFrame:
    """
    Single Bloomberg BDP call for all securities and all fields.
    Returns long-format DataFrame:
        [parsekyable, field, value, loaded_at]
    """

    parsekyables = [
        s['parsekyable']
        for s in securities
        if s.get('parsekyable')
    ]

    if not parsekyables:
        logger.warning('No parsekyables resolved — nothing to extract.')
        return pd.DataFrame(columns=['parsekyable', 'field', 'value', 'loaded_at'])

    missing = [s['procode'] for s in securities if not s.get('parsekyable')]
    if missing:
        logger.warning(f'{len(missing)} securities have no parsekyable: {missing}')

    chunks = _chunks(parsekyables, BDP_CHUNK)
    logger.info(
        f'Requesting {len(fields)} fields for {len(parsekyables)} parsekyables '
        f'via BDP in {len(chunks)} request(s) of <= {BDP_CHUNK}.'
    )

    loaded_at = datetime.now().isoformat(timespec='seconds')
    frames = []
    for i, chunk in enumerate(chunks, 1):
        try:
            raw_df = fetch_reference_request(
                data_request(securities=chunk, fields=fields)
            )
        except Exception as e:
            logger.error(f'BDP request {i}/{len(chunks)} failed: {e}', exc_info=True)
            continue
        if raw_df is None or raw_df.empty or 'id' not in raw_df.columns:
            logger.info(f'BDP request {i}/{len(chunks)}: no data returned.')
            continue
        long_df = (
            raw_df.rename(columns={'id': 'parsekyable'})
            .melt(id_vars='parsekyable', var_name='field', value_name='value')
        )
        long_df['loaded_at'] = loaded_at
        frames.append(long_df[
            long_df['value'].notna()
            & (long_df['value'] != '')
            & (long_df['value'] != 'nan')
        ])

    if not frames:
        return pd.DataFrame(columns=['parsekyable', 'field', 'value', 'loaded_at'])
    return pd.concat(frames, ignore_index=True)


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def sentinel_rows(requested: list[str], answered: set[str], loaded_at: str) -> pd.DataFrame:
    """
    One '_REQUESTED' staging row per parsekyable asked this run, valued
    'answered' when Bloomberg returned at least one field for it and
    'no_data' otherwise. Same columns as the extract frame.
    """
    return pd.DataFrame({
        'parsekyable': requested,
        'field': SENTINEL_FIELD,
        'value': ['answered' if p in answered else 'no_data' for p in requested],
        'loaded_at': loaded_at,
    })


def load_stg_security_bloomberg(conn, df: pd.DataFrame) -> None:
    """
    Writes long-format extract result to stg_security_bloomberg.
    UNIQUE constraint on (parsekyable, field, loaded_at) means
    re-runs within the same second are silently ignored.
    All historical loads are retained for audit and re-resolution.
    """
    inserted = 0

    for _, row in df.iterrows():
        cur = conn.execute(
            """
            INSERT INTO stg_security_bloomberg (parsekyable, field, value, loaded_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (parsekyable, field, loaded_at) DO NOTHING
            """,
            (row['parsekyable'], row['field'], row['value'], row['loaded_at']),
        )
        if cur.rowcount > 0:
            inserted += 1

    logger.info(f'stg_security_bloomberg: {inserted} rows staged.')


def read_latest_stg_security_bloomberg(conn, parsekyables: list[str] | None = None) -> pd.DataFrame:
    """
    Reads the most recent load per (parsekyable, field) from staging,
    excluding the request sentinel. Scoped to `parsekyables` when given:
    a run transforms only what it just asked about, so an old staged
    MARKET_STATUS is not re-applied to every entity on every run.
    """
    query = """
        SELECT parsekyable, field, value
        FROM stg_security_bloomberg s1
        WHERE field <> %(sentinel)s
          AND (%(all)s OR parsekyable = ANY(%(keys)s))
          AND loaded_at = (
            SELECT MAX(loaded_at)
            FROM stg_security_bloomberg s2
            WHERE s2.parsekyable = s1.parsekyable
              AND s2.field = s1.field
        )
    """
    cur = conn.execute(query, {
        'sentinel': SENTINEL_FIELD,
        'all': parsekyables is None,
        'keys': list(parsekyables or []),
    })
    rows = cur.fetchall()
    return pd.DataFrame(rows)
