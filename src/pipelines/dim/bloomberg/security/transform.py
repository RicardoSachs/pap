
import logging
import pandas as pd

from src.db.connection import get_connection
from src.db.queries import resolve_entity_id_from_identifier
from src.pipelines.dim.bloomberg.security.loaders.series_status import (
    MARKET_STATUS_MAP,
    EXCH_MARKET_STATUS_MAP,
    _FALLBACK_TRIGGER,
    _clean
)

logger = logging.getLogger(__name__)

# Maps Bloomberg field names to dim_security columns
SHARED_FIELD_MAP = {
    'TICKER':'ticker',
    'NAME':'name',
    'SHORT_NAME':'short_name',
    'SECURITY_NAME':'security_name',
    'ID_BB_SEC_NUM_DES':'sec_num_des',
    'CRNCY':'currency',
    'COUNTRY':'country',
    'EXCH_CODE':'exchange',
    'MARKET_SECTOR_DES':'market_sector',
    'SECURITY_TYP':'security_type',
    'MARKET_STATUS':'market_status',
    'EXCH_MARKET_STATUS':'exch_market_status'
}

# Maps Bloomberg field names to dim_security_equity columns
EQUITY_FIELD_MAP = {
    'INDUSTRY_SECTOR':'sector'
}

# Maps Bloomberg field names to dim_security_fund columns
FUND_FIELD_MAP = {
    'FUND_TYP':'fund_type',
    'FUND_ASSET_CLASS_FOCUS':'asset_class',
    'FUND_GEO_FOCUS':'geography',
    'FUND_OBJECTIVE_LONG':'objective'
}

# Identifier fields to upsert into dim_entity_identifiers
IDENTIFIER_FIELD_MAP = {
    'ID_ISIN': ('isin', 'internal'),
    'PARSEKYABLE_DES': ('parsekyable', 'bloomberg')
}

def transform_security_attributes(
    stg_df: pd.DataFrame,
    conn
) -> dict[str, pd.DataFrame]:
    '''
    Pivots long-format staging data to wide per ticker,
    resolves entity_id for each ticker,
    maps Bloomberg field names to dim column names,
    splits into target-shaped DataFrames per dim table.

    Returns dict keyed by target table name:
        dim_security, dim_security_equity,
        dim_security_fund, dim_entity_identifiers
    
    :param stg_df: Staging (long) dataframe
    :type stg_df: pd.DataFrame
    :param conn: Connection object
    :return: Description
    :rtype: dict[str, DataFrame]
    '''
    if stg_df.empty:
        logger.warning('Staging DataFrame is empty - nothing to transform')
        return {}
    
    # Pivot to wide: index=parsekyable, columns=field
    wide_df = stg_df.pivot_table(
        index='parsekyable',
        columns='field',
        values='value',
        aggfunc='last'
    ).reset_index()

    logger.info(f'Transforming {len(wide_df)} securities from staging.')

    # Resolve entity_id for each ticker
    wide_df['entity_id'] = wide_df['parsekyable'].apply(
        lambda t: resolve_entity_id_from_identifier(
            conn, id_type='parsekyable', id_value=t, source='bloomberg'
        )
    )

    unresolved_df = wide_df[wide_df['entity_id'].isna()]
    if not unresolved_df.empty:
        logger.warning(
            f'{len(unresolved_df)} tickers could not be resolved to entity_id: '
            f'{unresolved_df["parsekyable"].tolist()}'
        )
    wide_df = wide_df[wide_df['entity_id'].notna()].copy()
    wide_df['entity_id'] = wide_df['entity_id'].astype(int)

    return {
        'dim_security': _map_shared(wide_df),
        'dim_security_equity': _map_equity(wide_df),
        'dim_security_fund': _map_fund(wide_df),
        'dim_entity_identifiers': _map_identifiers(wide_df),
        'series_status_updates': _extract_series_status_updates(wide_df)
    }

def _map_shared(wide_df: pd.DataFrame) -> pd.DataFrame:
    '''
    Maps Bloomberg fields to dim_security columns.
    Only includes rows where entity_id is resolved.
    Returns: [entity_id, ticker, name, short_name,
    security_name, sec_num_des, currency, country, 
    exchange, market_sector, security_type]
    
    :param wide_df: Raw wide DataFrame
    :type wide_df: pd.DataFrame
    :return: Description
    :rtype: DataFrame
    '''
    rows = []
    for _, row in wide_df.iterrows():
        mapped = {'entity_id': row['entity_id']}
        for bbg_field, col in SHARED_FIELD_MAP.items():
            val = row.get(bbg_field)
            if pd.notna(val) and str(val).strip():
                mapped[col] = str(val).strip()
            else:
                mapped[col] = None
        rows.append(mapped)
    return pd.DataFrame(rows)

def _map_equity(wide_df: pd.DataFrame) -> pd.DataFrame:
    '''
    Maps Bloomberg fields to dim_security_equity columns.
    Only includes rows where security_type indicates equity.
    Returns: [entity_id, sector]
    
    :param wide_df: Raw wide DataFrame
    :type wide_df: pd.DataFrame
    :return: Description
    :rtype: DataFrame
    '''
    equity_types = {'Common Stock', 'ADR'}
    equity_df = wide_df[
        wide_df.get('SECURITY_TYP', pd.Series(dtype=str)).isin(equity_types)
    ].copy() if 'SECURITY_TYP' in wide_df.columns else wide_df.copy()

    rows = []
    for _, row in equity_df.iterrows():
        mapped = {'entity_id': row['entity_id']}
        for bbg_field, col in EQUITY_FIELD_MAP.items():
            val = row.get(bbg_field)
            if pd.notna(val) and str(val).strip():
                mapped[col] = str(val).strip()
            else:
                mapped[col] = None
        rows.append(mapped)
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def _map_fund(wide_df: pd.DataFrame) -> pd.DataFrame:
    '''
    Maps Bloomberg fields to dim_security_fund columns.
    Only includes rows where security_type indicates a fund.
    Returns: [entity_id, fund_type, asset_class, geography, objective]
    
    :param wide_df: Raw wide DataFrame
    :type wide_df: pd.DataFrame
    :return: Description
    :rtype: DataFrame
    '''
    fund_types = {'ETP', 'Open-End Fund', 'Closed-End Fund'}
    fund_df = wide_df[
        wide_df.get('SECURITY_TYP', pd.Series(dtype=str)).isin(fund_types)
    ].copy() if 'SECURITY_TYP' in wide_df.columns else wide_df.copy()

    rows = []
    for _, row in fund_df.iterrows():
        mapped = {'entity_id': row['entity_id']}
        for bbg_field, col in FUND_FIELD_MAP.items():
            val = row.get(bbg_field)
            if pd.notna(val) and str(val).strip():
                mapped[col] = str(val).strip()
            else:
                mapped[col] = None
        rows.append(mapped)
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def _map_identifiers(wide_df: pd.DataFrame) -> pd.DataFrame:
    '''
    Extract identifier fields from staged data into a long-format
    DataFrame ready for upsert into dim_entity_identifiers.
    Returns: [entity_id, id_type, id_value, source, is_primary]
    
    :param wide_df: Raw wide DataFrame
    :type wide_df: pd.DataFrame
    :return: Description
    :rtype: DataFrame
    '''
    rows = []
    for _, row in wide_df.iterrows():
        for bbg_field, (id_type, source) in IDENTIFIER_FIELD_MAP.items():
            val = row.get(bbg_field)
            if pd.notna(val) and str(val).strip() and str(val) != 'nan':
                rows.append({
                    'entity_id': row['entity_id'],
                    'id_type': id_type,
                    'id_value': str(val).strip(),
                    'source': source,
                    'is_primary': True
                })
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def _extract_series_status_updates(wide_df: pd.DataFrame) -> pd.DataFrame:
    """
    Resolves series_registry status from MARKET_STATUS and
    EXCH_MARKET_STATUS columns in the pivoted BDP response.

    Resolution logic:
      1. MARKET_STATUS present and not in _FALLBACK_TRIGGER
         -> use MARKET_STATUS_MAP (authoritative)
      2. MARKET_STATUS missing or in _FALLBACK_TRIGGER (e.g. PRNA)
         -> fall back to EXCH_MARKET_STATUS_MAP
         -> covers futures, FX, and PRNA cases
      3. Both missing or unrecognised
         -> skip row, log warning, leave status unchanged

    Returns DataFrame:
        [entity_id, bloomberg_status, registry_status, resolved_from]
    """
    rows = []

    for _, row in wide_df.iterrows():
        mkt_status  = _clean(row.get("MARKET_STATUS"))
        exch_status = _clean(row.get("EXCH_MARKET_STATUS"))

        registry_status = None
        resolved_from   = None

        # Step 1: try MARKET_STATUS
        if mkt_status and mkt_status not in _FALLBACK_TRIGGER:
            registry_status = MARKET_STATUS_MAP.get(mkt_status)
            if registry_status:
                resolved_from = "MARKET_STATUS"

        # Step 2: fall back to EXCH_MARKET_STATUS
        if registry_status is None and exch_status:
            registry_status = EXCH_MARKET_STATUS_MAP.get(exch_status)
            if registry_status:
                resolved_from = "EXCH_MARKET_STATUS"

        # Step 3: both missing or unrecognised
        if registry_status is None:
            logger.warning(
                f"entity_id={row['entity_id']}: could not resolve status "
                f"from MARKET_STATUS={mkt_status!r} / "
                f"EXCH_MARKET_STATUS={exch_status!r}. Status unchanged."
            )
            continue

        rows.append({
            "entity_id":        row["entity_id"],
            "bloomberg_status": mkt_status or exch_status,
            "registry_status":  registry_status,
            "resolved_from":    resolved_from,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["entity_id", "bloomberg_status",
                 "registry_status", "resolved_from"]
    )
