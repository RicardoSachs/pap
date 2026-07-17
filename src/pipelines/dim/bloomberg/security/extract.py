# src/pipelines/dim/bloomberg/security/extract.py
# ---------------------------------------------------------------
# Bloomberg security-attribute extraction: one BDP reference call for all
# securities and fields (long-format), plus staging load/read helpers.
# ---------------------------------------------------------------

import logging
import pandas as pd
from datetime import datetime

from src.db.connection import get_connection
from src.db.queries import get_backfill_pending_series
from src.vendors.bloomberg import data_request, fetch_reference_request

logger = logging.getLogger(__name__)


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

    logger.info(f'Requesting {len(fields)} fields for {len(parsekyables)} parsekyables via BDP.')

    raw_df = fetch_reference_request(
        data_request(securities=parsekyables, fields=fields)
    )

    loaded_at = datetime.now().isoformat(timespec='seconds')
    long_df = (
        raw_df.rename(columns={'id': 'parsekyable'})
        .melt(id_vars='parsekyable', var_name='field', value_name='value')
    )
    long_df['loaded_at'] = loaded_at
    long_df = long_df[
        long_df['value'].notna()
        & (long_df['value'] != '')
        & (long_df['value'] != 'nan')
    ]

    return long_df


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


def read_latest_stg_security_bloomberg(conn) -> pd.DataFrame:
    """
    Reads the most recent load per (parsekyable, field) from staging.
    Used by transform to always work from the latest Bloomberg response.
    """
    cur = conn.execute(
        """
        SELECT parsekyable, field, value
        FROM stg_security_bloomberg s1
        WHERE loaded_at = (
            SELECT MAX(loaded_at)
            FROM stg_security_bloomberg s2
            WHERE s2.parsekyable = s1.parsekyable
              AND s2.field = s1.field
        )
        """
    )
    rows = cur.fetchall()
    return pd.DataFrame(rows)
