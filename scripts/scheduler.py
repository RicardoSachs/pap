# scripts/scheduler.py
# ---------------------------------------------------------------
# Unified scheduler for all machines. Replaces scheduler_central.py
# and scheduler_scraper.py.
#
# One script, capability-registered: which jobs this process runs
# is decided entirely by the machine_config flags —
#   bloomberg_enabled      -> prices_bloomberg, dim_enrichment
#   scraper_enabled        -> acquire_sbs (browser + image-pad beep)
#   sbs_ingestion_enabled  -> ingest_sbs (+ check_sbs when the
#                             scraper runs on a remote machine)
#   fms_enabled            -> positions_fms (four feeds, sequential)
# Fire times come from config/schedules.yaml — no cron values here.
#
# Observability (both tables in src/db/schema/37, 38):
#   - every job is wrapped by _tracked(): a job_runs row is inserted
#     at start ('running') and updated at end ('success'/'error').
#     Tracking failures never block the job itself.
#   - a heartbeat job upserts scheduler_heartbeat every 5 minutes so
#     "is the scheduler alive on machine X" is a SQL query.
#
# Daily chain (see schedules.yaml for the times):
#   acquire_sbs -> check_sbs -> ingest_sbs -> positions_fms ->
#   prices_bloomberg (17:30 America/New_York, DST-proof).
#
# Deployment: no admin rights, so no service. Register a user-level
# Windows Task Scheduler task per machine that launches
# scripts/bat/scheduler.bat at log on with restart-on-failure — see
# docs/SCHEDULER.md.
#
# Usage:
#   python scripts/scheduler.py
# ---------------------------------------------------------------

import functools
import logging
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.configs.machine_config import (
    bloomberg_enabled,
    fms_enabled,
    machine_id,
    sbs_ingestion_enabled,
    scraper_enabled,
    timezone,
)
from src.shared.config_loader import load_schedules
from src.shared.logging import setup_logging

setup_logging("scheduler")
logger = logging.getLogger(__name__)

TZ = timezone()
MACHINE = machine_id()
scheduler = BlockingScheduler(timezone=TZ)

_STARTED_AT: Optional[object] = None  # set in __main__, read by heartbeat


# ---- Job-run tracking ------------------------------------------

def _record_start(job_id: str) -> Optional[int]:
    """Inserts a 'running' job_runs row. Returns its id, or None if
    the DB is unreachable — tracking must never block the job."""
    try:
        from src.db.connection import get_connection
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO job_runs (job_id, machine_id) "
                "VALUES (%s, %s) RETURNING job_run_id",
                (job_id, MACHINE),
            )
            return cur.fetchone()["job_run_id"]
    except Exception as e:
        logger.warning(f"job_runs start tracking failed for {job_id}: {e}")
        return None


def _record_end(
    job_run_id: Optional[int],
    status: str,
    run_date: Optional[date] = None,
    error: Optional[str] = None,
) -> None:
    if job_run_id is None:
        return
    try:
        from src.db.connection import get_connection
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE job_runs SET status = %s, run_date = %s, "
                "finished_at = now(), error = %s WHERE job_run_id = %s",
                (status, run_date, error, job_run_id),
            )
    except Exception as e:
        logger.warning(f"job_runs end tracking failed for run {job_run_id}: {e}")


def _tracked(job_id: str, fn: Callable[[], Optional[date]]) -> Callable[[], None]:
    """Wraps a job so every execution lands in job_runs. The job
    returns the business date it processed (or None); exceptions are
    recorded and re-raised so APScheduler logs the failure too."""
    @functools.wraps(fn)
    def wrapper() -> None:
        job_run_id = _record_start(job_id)
        try:
            run_date = fn()
        except Exception as e:
            _record_end(job_run_id, "error", error=f"{type(e).__name__}: {e}")
            raise
        _record_end(job_run_id, "success", run_date=run_date)
    return wrapper


def job_heartbeat() -> None:
    """Upserts this machine's scheduler_heartbeat row. Untracked —
    it IS the tracking."""
    try:
        from src.db.connection import get_connection
        jobs = ",".join(sorted(j.id for j in scheduler.get_jobs() if j.id != "heartbeat"))
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO scheduler_heartbeat "
                "(machine_id, started_at, last_seen, registered_jobs) "
                "VALUES (%s, %s, now(), %s) "
                "ON CONFLICT (machine_id) DO UPDATE SET "
                "started_at = EXCLUDED.started_at, last_seen = now(), "
                "registered_jobs = EXCLUDED.registered_jobs",
                (MACHINE, _STARTED_AT, jobs),
            )
    except Exception as e:
        logger.warning(f"heartbeat upsert failed: {e}")


# ---- Beep helper (SBS image-pad login alert) -------------------

def _beep_until_stopped(stop_event: threading.Event) -> None:
    """Repeating beep until stop_event is set. Daemon thread — dies
    with the scheduler process. Checks the event every 100ms so it
    stops promptly when acquisition completes."""
    import winsound
    while not stop_event.is_set():
        winsound.Beep(880, 300)
        for _ in range(7):
            if stop_event.is_set():
                return
            time.sleep(0.1)


# ---- Job definitions -------------------------------------------

def job_prices_bloomberg() -> date:
    """Daily Bloomberg prices. run() itself skips NYSE holidays in
    incremental mode. Fires 17:30 America/New_York, so today's Lima
    date equals today's New York date."""
    logger.info("--- job: prices bloomberg ---")
    from src.pipelines.prices.bloomberg.run import run
    run_date = date.today()
    run(run_date=run_date)
    return run_date


def job_dim_enrichment() -> None:
    """Weekly Bloomberg dim enrichment. No calendar guard — runs
    Monday morning regardless of exchange."""
    logger.info("--- job: dim enrichment bloomberg ---")
    from src.db.bootstrap import run_dim_enrichment
    run_dim_enrichment(vendor="bloomberg", domain="security")
    return None


def job_acquire_sbs() -> Optional[date]:
    """Semi-automated SBS acquisition for the previous reporting day
    (Monday -> Friday, day after holiday -> last open day). Beeps
    until the operator completes the image-pad login. Files land on
    the network share for check_sbs/ingest_sbs."""
    from src.calendars.calendar_sbs import prev_reporting_day
    from src.scrapers.sbs import acquire_day, all_files_present

    run_date = prev_reporting_day(date.today())
    logger.info(f"--- job: acquire sbs | reporting day={run_date} ---")

    if all_files_present(run_date):
        logger.info(f"All SBS files already present for {run_date}. Skipping acquisition.")
        return run_date

    stop_event = threading.Event()
    beep_thread = threading.Thread(
        target=_beep_until_stopped,
        args=(stop_event,),
        daemon=True,
        name="sbs_beep",
    )
    beep_thread.start()
    logger.info("Beep started - browser opening, image pad login required.")

    try:
        results = acquire_day(run_date=run_date)
    finally:
        stop_event.set()
        beep_thread.join(timeout=1)
        logger.info("Beep stopped.")

    failed = [name for name, ok in results.items() if not ok]
    if failed:
        raise RuntimeError(
            f"SBS acquisition failed for {failed} on {run_date}. "
            f"Re-run manually: python scripts/acquire/acquire_sbs.py --date {run_date}"
        )
    logger.info(f"SBS acquisition complete: {len(results)} files for {run_date}.")
    return run_date


def job_check_sbs() -> date:
    """Verifies the previous reporting day's SBS files arrived on the
    network share (remote acquisition). Raises on missing files so
    the failure lands in job_runs and the APScheduler log before the
    ingest window."""
    from src.calendars.calendar_sbs import prev_reporting_day
    from src.scrapers.sbs import all_files_present

    run_date = prev_reporting_day(date.today())
    logger.info(f"--- job: check sbs | reporting day={run_date} ---")

    if not all_files_present(run_date):
        raise RuntimeError(
            f"SBS files missing for {run_date}. "
            f"Ingestion at the next window will use stale data."
        )
    logger.info(f"All SBS files present for {run_date}.")
    return run_date


def job_ingest_sbs() -> date:
    """Runs every SBS price sub-pipeline (shared registry, includes
    dividendos) for the previous reporting day. Each sub-pipeline
    gates itself on the reporting calendar."""
    from src.calendars.calendar_sbs import prev_reporting_day
    from src.pipelines.prices.sbs.registry import run_sbs_pipelines

    run_date = prev_reporting_day(date.today())
    logger.info(f"--- job: ingest sbs | reporting day={run_date} ---")
    run_sbs_pipelines(run_date=run_date)
    return run_date


def job_positions_fms() -> date:
    """Daily FMS positions: holdings, cash, net receivables, forwards,
    sequentially, all for the previous NYSE-or-XLIM business day
    (same union as the SBS reporting calendar). Feeds are idempotent,
    so one failing does not stop the rest; any failure is re-raised
    at the end so the job lands in job_runs as 'error'."""
    from src.calendars.calendar_sbs import prev_reporting_day
    from src.pipelines.positions.fms.cash.run import run_full as run_cash
    from src.pipelines.positions.fms.forwards.run import run_full as run_forwards
    from src.pipelines.positions.fms.holdings.run import run_full as run_holdings
    from src.pipelines.positions.fms.net_receivables.run import run_full as run_net_receivables

    run_date = prev_reporting_day(date.today())
    logger.info(f"--- job: positions fms | date={run_date} ---")

    feeds: list[tuple[str, Callable]] = [
        ("holdings", run_holdings),
        ("cash", run_cash),
        ("net_receivables", run_net_receivables),
        ("forwards", run_forwards),
    ]
    failures: list[str] = []
    for name, run_full in feeds:
        logger.info(f"--- fms feed: {name} ---")
        try:
            run_full(start_date=run_date, end_date=run_date)
        except Exception:
            logger.exception(f"fms feed {name} failed for {run_date}")
            failures.append(name)

    if failures:
        raise RuntimeError(f"FMS feeds failed for {run_date}: {failures}")
    return run_date


# ---- Registration ----------------------------------------------

def _register(job_id: str, fn: Callable[[], Optional[date]], name: str, jobs_cfg: dict) -> None:
    cfg = jobs_cfg.get(job_id)
    if cfg is None:
        raise KeyError(f"Job '{job_id}' has no entry in config/schedules.yaml")
    scheduler.add_job(
        _tracked(job_id, fn),
        CronTrigger(
            day_of_week=cfg["day_of_week"],
            hour=cfg["hour"],
            minute=cfg["minute"],
            timezone=cfg.get("timezone", TZ),
        ),
        id=job_id,
        name=name,
        misfire_grace_time=cfg.get("misfire_grace_time", 3600),
        coalesce=True,
        max_instances=1,
    )


def register_jobs() -> None:
    jobs_cfg = load_schedules()["jobs"]

    if bloomberg_enabled():
        _register("prices_bloomberg", job_prices_bloomberg, "Bloomberg daily prices", jobs_cfg)
        _register("dim_enrichment", job_dim_enrichment, "Bloomberg dim enrichment", jobs_cfg)

    if scraper_enabled():
        _register("acquire_sbs", job_acquire_sbs, "SBS daily acquisition", jobs_cfg)

    if sbs_ingestion_enabled():
        # check_sbs only matters when acquisition happens on a remote
        # machine; a machine that scrapes and ingests needs no gate.
        if not scraper_enabled():
            _register("check_sbs", job_check_sbs, "SBS file check", jobs_cfg)
        _register("ingest_sbs", job_ingest_sbs, "SBS ingestion", jobs_cfg)

    if fms_enabled():
        _register("positions_fms", job_positions_fms, "FMS daily positions", jobs_cfg)

    scheduler.add_job(
        job_heartbeat,
        IntervalTrigger(minutes=5),
        id="heartbeat",
        name="Scheduler heartbeat",
        coalesce=True,
        max_instances=1,
    )


# ---- Entry point -----------------------------------------------

if __name__ == "__main__":
    from datetime import datetime, timezone as dt_timezone
    _STARTED_AT = datetime.now(dt_timezone.utc)

    register_jobs()

    registered = [j.id for j in scheduler.get_jobs()]
    logger.info("=== Scheduler started ===")
    logger.info(f"Machine:                {MACHINE}")
    logger.info(f"Timezone:               {TZ}")
    logger.info(f"bloomberg_enabled:      {bloomberg_enabled()}")
    logger.info(f"scraper_enabled:        {scraper_enabled()}")
    logger.info(f"sbs_ingestion_enabled:  {sbs_ingestion_enabled()}")
    logger.info(f"fms_enabled:            {fms_enabled()}")
    logger.info(f"Registered jobs:        {registered}")

    if registered == ["heartbeat"]:
        logger.warning(
            "No capability flags set for this machine - only the heartbeat "
            "will run. Check machine_config (market_data_config.yaml)."
        )

    job_heartbeat()  # first heartbeat immediately, not after 5 min

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("=== Scheduler stopped ===")
        scheduler.shutdown()
