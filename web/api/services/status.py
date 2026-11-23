# web/api/services/status.py
# ---------------------------------------------------------------------------
# Status service : is the warehouse being fed? Three reads, one verdict each.
#
#   feeds       vw_pipeline_health (schema 46) gives the newest date per
#               feed; this module adds the verdict, because "late" needs the
#               SBS reporting calendar (NYSE or XLIM open) and that lives in
#               Python. lag_days = reporting days between the feed's newest
#               date and the one it should hold by now.
#                 ok       holds the expected date
#                 pending  one reporting day behind - today's run has not
#                          happened yet, or exactly one run was missed
#                 thin     current, but the newest date has under half the
#                          rows of the previous one (partial load)
#                 late     two or more reporting days behind, or no rows in
#                          the view's 45-day window
#                 unscheduled  no scheduler job feeds it: shown, not judged
#   jobs        the latest job_runs row per (job, machine), last 14 days.
#   schedulers  scheduler_heartbeat; silent for 10 minutes = down.
#
# Every item carries `level` (green / amber / red / grey) so the page does
# not repeat this mapping; `overall` is the worst level present.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

# Reporting days back from today that each scheduled feed should hold.
# 1 = the previous reporting day; the SBS publishes the valor cuota at t-2.
# A feed missing here (prices_model, prices_manual, ...) is 'unscheduled'.
EXPECTED_LAG = {
    "positions_securities": 1, "positions_deposits": 1, "positions_cash": 1,
    "positions_forwards": 1, "positions_net_receivables": 1,
    "positions_valuation": 1, "contribution": 1,
    "prices_bloomberg": 1, "prices_sbs": 1, "prices_sbs_spp": 2,
}

LEVEL = {
    "ok": "green",
    "pending": "amber", "thin": "amber", "running": "amber",
    "late": "red", "error": "red", "stuck": "red", "down": "red",
    "unscheduled": "grey",
}
_SEVERITY = ["grey", "green", "amber", "red"]

STUCK_AFTER = timedelta(hours=6)    # a 'running' row older than this died mid-job


def classify_feed(lag_days: int | None, rows_last: int | None, rows_prev: int | None) -> str:
    """Verdict for a scheduled feed. lag_days None = no rows in the window."""
    if lag_days is None or lag_days >= 2:
        return "late"
    if lag_days == 1:
        # ponytail: cannot tell "today's run not due yet" from "one run
        # missed"; compare against the job's deadline if that matters.
        return "pending"
    if rows_prev and rows_last is not None and rows_last < 0.5 * rows_prev:
        return "thin"
    return "ok"


def classify_job(status: str, started_at: datetime, now: datetime) -> str:
    if status == "success":
        return "ok"
    if status == "running":
        return "stuck" if now - started_at > STUCK_AFTER else "running"
    return "error"


def worst(levels: list[str]) -> str:
    return max(levels, key=_SEVERITY.index, default="grey")


def _expected_dates(today: date) -> dict[int, date]:
    """{reporting days back: date} for every lag in EXPECTED_LAG."""
    from src.calendars.calendar_sbs import prev_reporting_day
    out, d = {}, today
    for lag in range(1, max(EXPECTED_LAG.values()) + 1):
        d = prev_reporting_day(d)
        out[lag] = d
    return out


def _lag_days(last_date: date | None, expected: date) -> int | None:
    from src.calendars.calendar_sbs import reporting_days_in_range
    if last_date is None:
        return None
    if last_date >= expected:
        return 0
    return len(reporting_days_in_range(last_date + timedelta(days=1), expected))


def get_status(today: date | None = None) -> dict:
    today = today or date.today()
    now = datetime.now(timezone.utc)
    expected = _expected_dates(today)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM vw_pipeline_health ORDER BY domain, feed")
        feeds = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT DISTINCT ON (job_id, machine_id)
                      job_id, machine_id, run_date, status, started_at, finished_at, error
               FROM job_runs
               WHERE started_at >= now() - interval '14 days'
               ORDER BY job_id, machine_id, started_at DESC"""
        )
        jobs = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT machine_id, started_at, last_seen, registered_jobs,
                      now() - last_seen < interval '10 minutes' AS alive
               FROM scheduler_heartbeat ORDER BY machine_id"""
        )
        schedulers = [dict(r) for r in cur.fetchall()]

    for f in feeds:
        lag = EXPECTED_LAG.get(f["feed"])
        if lag is None:
            f.update(expected_date=None, lag_days=None, status="unscheduled")
        else:
            f["expected_date"] = expected[lag]
            f["lag_days"] = _lag_days(f["last_date"], expected[lag])
            f["status"] = classify_feed(f["lag_days"], f["rows_last_date"], f["rows_prev_date"])
        f["level"] = LEVEL[f["status"]]

    for j in jobs:
        j["status"] = classify_job(j["status"], j["started_at"], now)
        j["level"] = LEVEL[j["status"]]

    for s in schedulers:
        s["status"] = "ok" if s.pop("alive") else "down"
        s["level"] = LEVEL[s["status"]]

    return {
        "as_of": now,
        "today": today,
        "overall": worst([x["level"] for x in feeds + jobs + schedulers]),
        "feeds": feeds,
        "jobs": jobs,
        "schedulers": schedulers,
    }
