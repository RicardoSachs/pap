
# pipelines/prices/bloomberg/transform.py
# ---------------------------------------------------------------
# Transforms staged Bloomberg price data into fact_prices shape.
# Resolves parsekyable -> series_id via the securities list
# already in memory from run.py - no extra DB queries needed.
# Casts value to REAL and validates before loading.
# --------------------------------------------------------------

import logging
import pandas as pd

logger = logging.getLogger(__name__)

def transform_prices(
    raw_df: pd.DataFrame,
    securities: list[dict],
) -> pd.DataFrame:
    '''
    Transforms long-format Bloomberg price data for loading into fact_prices.

    Maps parsekyable -> series_id using the securities list from run.py.
    One series_id per (parsekyable, field) combination - the securities
    list already encodes this mapping via series_id + field_attributes.

    Returns DataFrame with columns:
        [series_id, date, value, source]
    
    :param raw_df: "Raw" long-format Bloomberg DataFrame
    :type raw_df: pd.DataFrame
    :param securities: Securities dict list
    :type securities: list[dict]
    :return: DataFrame for fact_prices
    :rtype: DataFrame
    '''
    if raw_df.empty:
        logger.warning('Raw DataFrame is empty - nothing to transform.')
        return pd.DataFrame(columns=['series_id', 'date', 'value', 'source'])
    
    # Build lookup: (bloomberg_ticker, field) -> series_id
    parsekyable_field_map = {
        (s['parsekyable'], s['field']): s['series_id']
        for s in securities
        if s.get('parsekyable')
    }

    df = raw_df.copy()

    # Map to series_id
    df['series_id'] = df.apply(
        lambda r: parsekyable_field_map.get((r['parsekyable'], r['field'])),
        axis=1
    )

    unresolved = df[df['series_id'].isna()]
    if not unresolved.empty:
        logger.warning(
            f'{len(unresolved)} rows could not be mapped to a series_id '
            f'(unknown parsekyable/field combinations) and will be dropped.'
        )
    df = df[df['series_id'].notna()].copy()
    df['series_id'] = df['series_id'].astype(int)

    # Cast value to numeric - drop non-parseable rows
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    invalid = df['value'].isna().sum()
    if invalid:
        logger.warning(f'{invalid} rows had non-numeric values and will be dropped.')
    df = df[df['value'].notna()].copy()

    # Add source
    df['source'] = 'bloomberg'

    # Validate date format YYYY-MM-DD
    df = df[df['date'].str.match(r'^\d{4}-\d{2}-\d{2}$', na=False)]

    result = df[['series_id', 'date', 'value', 'source']].drop_duplicates(
        subset=['series_id', 'date']
    )

    logger.info(f'Transform complete: {len(result)} rows ready for loading.')
    return result
