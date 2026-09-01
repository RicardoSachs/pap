# src/pipelines/positions/fms/net_receivables/extract.py
# ---------------------------------------------------------------
# Executes the FMS net-receivables query and returns a raw DataFrame with
# vendor-native (PascalCase) column names + a stamped `date`.
#
# POINT-IN-TIME, per day: unlike cash/forwards (one set-based range query),
# the net-receivables query reconstructs the OPEN balance AS OF a single day.
# So this loops over the XLIM (Lima) business days in [start_date, end_date],
# runs the query once per day (the as-of date bound to both ? placeholders),
# and stamps that day onto the rows as `date`. All days are concatenated into
# one DataFrame for the transform.
#
# Range size validation lives here: reject ranges wider than MAX_RANGE_DAYS
# unless force=True.
# ---------------------------------------------------------------

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from src.vendors.fms import get_fms_connection
from src.calendars.calendar_xlim import business_days_in_range

logger = logging.getLogger(__name__)

QUERY_PATH = Path(__file__).parent / "queries" / "net_receivables.sql"
MAX_RANGE_DAYS = 90


def extract(start_date: date, end_date: date, force: bool = False) -> pd.DataFrame:
    """
    Pull FMS net receivables for each XLIM business day in the inclusive range.

    Returns a DataFrame with vendor-native (PascalCase) column names plus a
    `date` column stamped per day. Empty DataFrame if no business days or no
    rows in range.

    Raises ValueError if end_date < start_date, or if the range exceeds
    MAX_RANGE_DAYS and force=False.
    """
    if end_date < start_date:
        raise ValueError(f"end_date {end_date} < start_date {start_date}")

    span_days = (end_date - start_date).days
    if span_days > MAX_RANGE_DAYS and not force:
        raise ValueError(
            f"date range {span_days} days exceeds MAX_RANGE_DAYS={MAX_RANGE_DAYS}. "
            f"pass force=True to override."
        )

    days = business_days_in_range(start_date, end_date)
    if not days:
        logger.warning(f"no XLIM business days in {start_date}..{end_date}; nothing to extract")
        return pd.DataFrame()

    sql = QUERY_PATH.read_text(encoding="utf-8")
    logger.info(
        f"executing FMS net_receivables query for {len(days)} business day(s): "
        f"{days[0]}..{days[-1]}"
    )

    frames = []
    with get_fms_connection() as conn:
        cur = conn.cursor()
        for d in days:
            d_int = _date_to_yyyymmdd(d)
            cur.execute(sql, (d_int, d_int))          # same as-of date, bound twice
            columns = [c[0] for c in cur.description] if cur.description else []
            rows = cur.fetchall()
            if not rows:
                continue
            df_day = pd.DataFrame.from_records(rows, columns=columns)
            df_day["date"] = d                        # stamp the as-of day
            frames.append(df_day)

    if not frames:
        logger.warning(f"FMS net_receivables returned zero rows across {len(days)} day(s)")
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    logger.info(f"FMS net_receivables extract: {len(df)} rows across {len(days)} day(s)")
    return df


def _date_to_yyyymmdd(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day
