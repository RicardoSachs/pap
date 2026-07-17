# src/pipelines/prices/bloomberg/run.py
# ---------------------------------------------------------------
# Fact pipeline entry point for Bloomberg daily prices.
# Handles both incremental daily updates and backfill.
#
# Two entry modes:
#   1. Normal scheduler run: queries series_registry for active
#      series, determines start_date per series from last loaded.
#   2. Backfill / series_override: receives series list directly
#      from onboard._dispatch_backfill, uses default_start_date
#      for new series.
# 
# Classify step separates new series (no fact rows yet) from
# existing ones (incremental update from last loaded date).
# ---------------------------------------------------------------

import logging
from datetime import date, timedelta
from typing import Optional

from src.db.connection import get_connection
from src.db.queries import (
    get_active_series,
    get_last_price_date,
    update_series_run_metadata,
    update_series_status
)

from src.calendars.calendar_nyse import is_business_day
from src.pipelines.prices.bloomberg.extract import (
    extract_prices,
    load_stg_prices_bloomberg
)
from src.pipelines.prices.bloomberg.transform import transform_prices
from src.pipelines.prices.bloomberg.loader import load_prices

logger = logging.getLogger(__name__)

def run(
    run_date: Optional[date] = None,
    series_override: Optional[list[dict]] = None
) -> None:
    """
    Main entry point for Bloomberg prices pipeline.
    
    :param run_date: Date to run for. Defaults to today.
    :type run_date: Optional[date]
    :param series_override: If provided, skips get_active_series and proceses this list directly. Used by backfill dispatch in onboard._dispatch_backfill().
    :type series_override: Optional[list[dict]]
    """
    run_date = run_date or (date.today() - timedelta(days = 1))

    logger.info(
        f'=== prices/bloomberg run started | run_date={run_date} | '
        f"mode={'backfill' if series_override else 'incremental'} ==="
    )

    # Resolve series list
    if series_override is not None:
        securities = series_override
        logger.info(f'Series override: {len(securities)} series received.')
    else:
        with get_connection() as conn:
            securities = get_active_series(
                conn,
                domain='prices',
                source='bloomberg',
                frequency='daily'
            )
        logger.info(f'Active series from registry: {len(securities)}.')

    if not securities:
        logger.warning('No series to process. Exiting')
        return
    
    # Classify: determine start_date per series
    securities = _classify(securities, run_date)

    to_process = [s for s in securities if s.get('start_date')]
    skipped_count = len(securities) - len(to_process)

    if skipped_count:
        logger.info(f'{skipped_count} series already up to date.')
    
    if not to_process:
        logger.info('Nothing to process. Exiting.')
        return
    
    logger.info(
        f'Processing {len(to_process)} series '
        f'({sum(s["is_new"] for s in to_process)} new, '
        f'{sum(not s["is_new"] for s in to_process)} incremental).'
    )

    # Extract
    raw_df = extract_prices(
        securities=to_process,
        end_date=run_date
    )

    if raw_df.empty:
        logger.warning('Extract returned no data.')
        _mark_all(to_process, run_status='partial')
        return
    
    # Stage
    with get_connection() as conn:
        load_stg_prices_bloomberg(conn, raw_df)

    # Transform
    transformed = transform_prices(raw_df, to_process)

    if transformed.empty:
        logger.warning('Transform returned to data.')
        _mark_all(to_process, run_status='partial')
        return
    
    # Load
    with get_connection() as conn:
        loaded, skipped_rows = load_prices(conn, transformed)
    
    logger.info(f'Loaded {loaded} rows, skipped {skipped_rows} duplicates.')

    # Update series_registry metadata
    _update_metadata(to_process, transformed, run_status='success')

    # Flip status to active if backfill
    if series_override is not None:
        with get_connection() as conn:
            for sec in to_process:
                update_series_status(conn, sec['series_id'], 'active')
        logger.info(f'Flipped {len(to_process)} series to active.')

    logger.info('=== prices/bloomberg run complete ===')

# Clasiffy ----------
def _classify(
    securities: list[dict],
    run_date: date
) -> list[dict]:
    """
    Determines start_date per series by checking fact_prices.

    New series (no rows in fact_prices):
        start_date = default_start_Date
        is_new = True

    Existing series:
        start_date = last_loaded_date + 1 day
        is_new = False

    Already up to date:
        start_date = None (will be filtered out in run)
    
    :param securities: Securities list dict
    :type securities: list[dict]
    :param run_date: Run date
    :type run_date: date
    :return: Start date and is new list by security
    :rtype: list[dict]
    """
    classified = []
    
    with get_connection() as conn:
        for sec in securities:
            sec = dict(sec)
            last_date = get_last_price_date(conn, sec['series_id'])

            if last_date is None:
                sec['start_date'] = (
                    sec['default_start_date']
                    if isinstance(sec['default_start_date'], date)
                    else date.fromisoformat(sec['default_start_date'])
                )
                sec['is_new'] = True
            
            elif last_date >= run_date:
                sec['start_date'] = None
                sec['is_new'] = False

            else:
                sec['start_date'] = last_date + timedelta(days=1)
                sec['is_new'] = False
            
            classified.append(sec)
        
    return classified

# Metadata helpers ----------

def _update_metadata(
    securities: list[dict],
    transformed: object,
    run_status: str
) -> None:
    """
    Updates last_run_at, last_run_status, last_loaded_date
    in series_registry for each processed series.
    """
    with get_connection() as conn:
        for sec in securities:
            series_rows = transformed[
                transformed['series_id'] == sec['series_id']
            ]
            last_loaded = (
                date.fromisoformat(series_rows['date'].max())
                if not series_rows.empty
                else None
            )
            update_series_run_metadata(
                conn,
                series_id=sec['series_id'],
                run_status=run_status,
                last_loaded_date=last_loaded
            )

def _mark_all(
    securities: list[dict],
    run_status: str
) -> None:
    """
    Marks all series with run_status when pipeline exits early.
    """
    with get_connection() as conn:
        for sec in securities:
            update_series_run_metadata(
                conn,
                series_id=sec['series_id'],
                run_status=run_status
            )
