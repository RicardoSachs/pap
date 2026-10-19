# tests/prices/sbs/valor_cuota/test_scheduled.py
# ---------------------------------------------------------------
# The scheduler job acquire_spp: which day it expects to find published.
#
# The SBS publishes the valor cuota with a two-reporting-day lag. The job
# fires at 16:00 and again at 16:30 and 17:00; before opening Chrome every
# attempt asks whether the book already holds that day. The question
# starts with knowing the day, on the SBS reporting calendar (NYSE or
# Lima open): pinned here. No DB.
# ---------------------------------------------------------------

import datetime as dt

from src.pipelines.prices.sbs.valor_cuota.run import expected_date


def test_midweek_is_two_reporting_days_back():
    # Wednesday 2026-09-23 -> Monday 2026-09-21
    assert expected_date(dt.date(2026, 9, 23)) == dt.date(2026, 9, 21)


def test_monday_and_tuesday_skip_the_weekend():
    # Monday 09-21 -> Thursday 09-17; Tuesday 09-22 -> Friday 09-18
    assert expected_date(dt.date(2026, 9, 21)) == dt.date(2026, 9, 17)
    assert expected_date(dt.date(2026, 9, 22)) == dt.date(2026, 9, 18)


def test_weekend_counts_from_friday():
    # Saturday 09-26 -> Thursday 09-24 (Friday and Thursday are the two
    # reporting days back)
    assert expected_date(dt.date(2026, 9, 26)) == dt.date(2026, 9, 24)


def test_a_holiday_on_both_exchanges_is_not_a_reporting_day():
    # 2026-01-01 closes NYSE and Lima: Friday 01-02 expects Tuesday 12-30,
    # not 12-31 as weekday arithmetic would say. Without this the three
    # attempts would open Chrome for a day the SBS never publishes.
    assert expected_date(dt.date(2026, 1, 2)) == dt.date(2025, 12, 30)


def test_a_holiday_on_one_exchange_still_reports():
    # 2026-10-08 (Combate de Angamos) closes Lima but not NYSE: the SBS
    # reports it, so Monday 10-12 expects Thursday 10-08.
    assert expected_date(dt.date(2026, 10, 12)) == dt.date(2026, 10, 8)
