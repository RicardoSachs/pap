# tests/web/test_fiscal_year.py
# ---------------------------------------------------------------
# The fiscal-year window (FY), which runs 31/10 to 31/10.
#
# What is tested is not the arithmetic but the boundary: 31/10 belongs
# to the fiscal year that ENDS on it, and that day is at the same time
# the base of the next one. Getting it wrong returns a zero return on
# the very day of the annual close, which is when it is looked at most.
# No DB.
# ---------------------------------------------------------------

import datetime as dt

import pytest

from web.api.services.spp import fiscal_year_start, gaps, reference_dates


@pytest.mark.parametrize("today, expected_start", [
    # Mid fiscal year: it started on 31/10 of the previous year.
    (dt.date(2026, 9, 15), dt.date(2025, 11, 1)),
    (dt.date(2026, 1, 2),  dt.date(2025, 11, 1)),
    # The day of the close still belongs to the year that ends.
    (dt.date(2026, 10, 31), dt.date(2025, 11, 1)),
    # The next day is already the new fiscal year.
    (dt.date(2026, 11, 1), dt.date(2026, 11, 1)),
    (dt.date(2026, 12, 31), dt.date(2026, 11, 1)),
])
def test_fiscal_year_start(today, expected_start):
    assert fiscal_year_start(today) == expected_start


def test_the_base_is_the_close_of_october_31():
    """The base is a TRADING day, not the calendar 31/10."""
    dates = [dt.date(2025, 10, 29), dt.date(2025, 10, 30), dt.date(2025, 10, 31),
             dt.date(2025, 11, 3), dt.date(2026, 9, 14), dt.date(2026, 9, 15)]
    ref = reference_dates(dates, dt.date(2026, 9, 15))
    assert ref["fy"] == dt.date(2025, 10, 31)


def test_when_the_31st_does_not_trade_the_base_is_octobers_last_close():
    """2026: 31/10 is a Saturday. The base falls back to Friday the 30th."""
    dates = [dt.date(2026, 10, 29), dt.date(2026, 10, 30),
             dt.date(2026, 11, 2), dt.date(2026, 11, 3)]
    ref = reference_dates(dates, dt.date(2026, 11, 3))
    assert ref["fy"] == dt.date(2026, 10, 30)


def test_the_close_day_is_not_measured_against_itself():
    """
    Standing on 31/10, the base has to be the PREVIOUS 31/10. Taking the
    same day would make the fiscal year read 0.00% on the one day its
    result is complete.
    """
    dates = [dt.date(2025, 10, 31), dt.date(2026, 6, 1), dt.date(2026, 10, 31)]
    ref = reference_dates(dates, dt.date(2026, 10, 31))
    assert ref["fy"] == dt.date(2025, 10, 31)


def test_without_enough_history_the_base_is_none():
    """No close before 31/10 means no window, and that is said with None."""
    dates = [dt.date(2026, 6, 1), dt.date(2026, 9, 15)]
    ref = reference_dates(dates, dt.date(2026, 9, 15))
    assert ref["fy"] is None


def test_reference_dates_use_the_last_close_of_the_prior_period():
    dates = [dt.date(2026, 1, 30), dt.date(2026, 2, 27), dt.date(2026, 3, 2),
             dt.date(2026, 3, 3), dt.date(2026, 3, 4)]
    ref = reference_dates(dates, dt.date(2026, 3, 4))
    assert ref["t1"] == dt.date(2026, 3, 3)
    assert ref["month"] == dt.date(2026, 2, 27)      # MTD base: last close of February
    assert ref["month1"] == dt.date(2026, 1, 30)
    assert ref["year"] is None                        # nothing before 2026-01-01
    assert ref["t5"] is None


def test_gaps_skip_short_holiday_blocks():
    # 2026-03-05 (Thu) to 2026-03-06 (Fri) missing: a two-day block, not a gap.
    # 2026-03-16 (Mon) to 2026-03-18 (Wed) missing: three business days, a gap.
    dates = [dt.date(2026, 3, 2), dt.date(2026, 3, 3), dt.date(2026, 3, 4),
             dt.date(2026, 3, 9), dt.date(2026, 3, 10), dt.date(2026, 3, 11),
             dt.date(2026, 3, 12), dt.date(2026, 3, 13), dt.date(2026, 3, 19)]
    assert gaps(dates) == [{"from": "2026-03-16", "to": "2026-03-18", "days": 3}]
    assert gaps(dates, minimum=2) == [
        {"from": "2026-03-05", "to": "2026-03-06", "days": 2},
        {"from": "2026-03-16", "to": "2026-03-18", "days": 3}]
