# tests/web/test_status.py
# ---------------------------------------------------------------
# The verdicts of the Status page: what turns a feed or a job amber
# or red. Pure functions, no DB and no calendar.
# ---------------------------------------------------------------

import datetime as dt

import pytest

from web.api.services.status import (EXPECTED_LAG, LEVEL, classify_feed,
                                     classify_job, worst)


@pytest.mark.parametrize("lag, rows_last, rows_prev, expected", [
    (0, 100, 100, "ok"),
    (0, 100, None, "ok"),        # first day ever loaded: nothing to compare
    (0, 49, 100, "thin"),        # partial load of the newest date
    (0, 50, 100, "ok"),
    (1, 100, 100, "pending"),    # today's run not in yet
    (1, 10, 100, "pending"),     # behind wins over thin
    (2, 100, 100, "late"),
    (None, None, None, "late"),  # nothing in the 45-day window
])
def test_classify_feed(lag, rows_last, rows_prev, expected):
    assert classify_feed(lag, rows_last, rows_prev) == expected


def test_classify_job():
    now = dt.datetime(2026, 11, 23, 12, 0, tzinfo=dt.timezone.utc)
    hour = dt.timedelta(hours=1)
    assert classify_job("success", now - 30 * hour, now) == "ok"
    assert classify_job("error", now - hour, now) == "error"
    assert classify_job("running", now - hour, now) == "running"
    assert classify_job("running", now - 7 * hour, now) == "stuck"


def test_worst_level_and_every_status_has_one():
    assert worst(["green", "grey", "amber"]) == "amber"
    assert worst(["green", "red", "amber"]) == "red"
    assert worst([]) == "grey"
    for status in ("ok", "pending", "thin", "late", "unscheduled",
                   "running", "stuck", "error", "down"):
        assert status in LEVEL
    assert set(EXPECTED_LAG.values()) <= {1, 2}
