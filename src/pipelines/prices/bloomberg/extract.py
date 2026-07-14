
# src/pipelines/prices/bloomberg/extract.py
# --------------------------------------------------------------
# Extracts historical price data from Bloomberg via BDH
# Accepts a list fo securites each with their own start_date,
# batches them into a single Bloomberg call where possible,
# and writes raw response to stg_prices_bloomberg.
# --------------------------------------------------------------

import logging
from datetime import date, datetime

import pandas as pd

from src.vendors.bloomberg import data_request, fetch_historical_request

logger = logging.getLogger(__name__)

def extract_prices(
    securities: list[dict],
    end_date: date
) -> pd.DataFrame:
    '''
    Extracts historical prices from Bloomberg BDH.
    Each security has its own start_date determined by _classify
    in run.py (default_start_date for new, last_loaded + 1 for existing)

    Becuase start dates vary per security, we group by start_date
    and issue one BDH call pero group to minimise API round trips
    while respecting per-security date windows.
    
    :param securities: Securities list
    :type securities: list[dict]
    :param end_date: End date of data (inclusive)
    :type end_date: date
    :return: Long format Bloomberg DataFrame
    :rtype: DataFrame
    '''
    valid = [s for s in securities if s.get('parsekyable')]
    missing = [s['procode'] for s in securities if not s.get('parsekyable')]

    if missing:
        logger.warning(
            f'{len(missing)} securities have no parsekyable and will be skipped: '
            f'{missing}'
        )
    
    if not valid:
        logger.warning('No valid bloomberg parsekyables to extract.')
        return pd.DataFrame(
            columns=['parsekyable','field','date','value','loaded_at']
        )
    
    loaded_at = datetime.now().isoformat(timespec='seconds')
    all_frames = []

    # Group by (start_date, fields) to batch tickers with same window
    groups: dict[tuple, list] = {}
    for sec in valid:
        key = (
            sec['start_date'].isoformat()
            if isinstance(sec['start_date'], date)
            else sec['start_date'],
            tuple(sorted(sec.get('fields', ['PX_LAST'])))
        )
        groups.setdefault(key, []).append(sec)

    logger.info(
        f'Extracting prices for {len(valid)} securities '
        f'in {len(groups)} date-window groups.'
    )

    for (start_date_str, fields), group in groups.items():
        parsekyables = [s['parsekyable'] for s in group]
        start_date = date.fromisoformat(start_date_str)

        logger.info(
            f'BDH call: {len(parsekyables)} tickers | '
            f'fields={list(fields)} | '
            f'{start_date} to {end_date}'
        )

        try:
            raw_df = fetch_historical_request(
                data_request(
                    securities=parsekyables,
                    fields=list(fields),
                    start_date=str(start_date),
                    end_date=str(end_date)
                )
            )

            if raw_df.empty:
                logger.info(
                    f'BDH returned empty table for group start={start_date}, skipping.'
                )
                continue

            # raw expected: long format DataFrame

            long_df = _melt_to_long(raw_df, loaded_at)
            all_frames.append(long_df)

        except Exception as e:
            logger.error(
                f'BDH call failed for group start={start_date}: {e}',
                exc_info=True
            )
            continue
    
    if not all_frames:
        logger.warning('All BDH calls failed or returned no data')
        return pd.DataFrame(
            columns=['parsekyable','field','date','value','loaded_at']
        )
    
    result_df = pd.concat(all_frames, ignore_index=True)
    logger.info(f'Extracted {len(result_df)} price observations total.')
    return result_df

def _melt_to_long(raw_df: pd.DataFrame, loaded_at: str) -> pd.DataFrame:
    '''
    Normalises Bloomberg BDH response to long format.
    Handles both wide (date x fields per ticker) and 
    MultiIndex (date, ticker) x fields formats
    
    :param raw_df: Raw DataFrame BDH response
    :type raw_df: pd.DataFrame
    :param loaded_at: Loaded at date
    :type loaded_at: str
    :return: Long format BDH DataFrame
    :rtype: DataFrame
    '''
    if isinstance(raw_df.columns, pd.MultiIndex):
        # MultiIndex: columns are (field, ticker)
        raw_df = raw_df.stack(level=1).reset_index()
        raw_df.columns.name = None
        raw_df = raw_df.rename(columns={'level_0': 'date', 'level_1': 'parsekyable'})
        long_df = raw_df.melt(
            id_vars=['date','parsekyable'],
            var_name='field',
            value_name='value'
        )
    else:
        # Wide: index=date, columns=fields, single ticker passed
        raw_df = raw_df.rename(columns={'id': 'parsekyable'})
        long_df = raw_df.melt(
            id_vars=['date', 'parsekyable'],
            var_name='field',
            value_name='value'
        )
    long_df['date'] = pd.to_datetime(long_df['date']).dt.date.astype(str)
    long_df['value'] = long_df['value'].astype(str).str.strip()
    long_df['loaded_at'] = loaded_at

    # Drop nulls and empty strings
    long_df = long_df[
        long_df['value'].notna()
        & (long_df['value'] != '')
        & (long_df['value'].str.lower() != 'nan')
        & (long_df['value'].str.lower() != 'none')
    ]
    
    return long_df[['parsekyable','field','date','value','loaded_at']]

def load_stg_prices_bloomberg(conn, df: pd.DataFrame) -> None:
    '''
    Writes long-format extract result to stg_prices_bloomberg.
    UNIQUE constraint on (parsekyable, field, date, loaded_at)
    means re-runs within the same second are silently ignored.
    All historical loads retained for audit and re-processing.
    
    :param conn: Description
    :param df: Description
    :type df: pd.DataFrame
    '''
    inserted = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            '''
            INSERT INTO stg_prices_bloomberg
                (parsekyable, field, date, value, loaded_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (parsekyable, field, date, loaded_at)
            DO NOTHING
            ''',
            (
                row['parsekyable'],
                row['field'],
                row['date'],
                row['value'],
                row['loaded_at']
            )
        )
        if cur.rowcount > 0:
            inserted += 1

    logger.info(f'stg_prices_bloomberg: {inserted} rows staged.')
