# src/pipelines/prices/sbs/valor_cuota/run.py
# ---------------------------------------------------------------
# Orchestration for the SPP valor cuota feed. No argparse here -
# scripts/run_sbs_valor_cuota.py owns the CLI.
#
# Entry points:
#   run_daily(...)      scrape the SPP variables page (last 7 business
#                       days, three metrics) and load what is missing.
#                       The only automatable load. Needs the visible
#                       Chrome + interactive session (WAF).
#   run_history(...)    load an SBS monthly XLS (valor cuota since
#                       1993) from a path, or downloaded with
#                       download=True.
#   review_history()    first half of a two-step upload: read the XLS
#                       and say exactly what would happen, writing
#                       nothing.
#   load_history()      second half: write the reviewed bytes in the
#                       chosen mode ('missing' | 'replace').
#   run_scheduled()     the body of the scheduler job acquire_spp
#                       (scripts/scheduler.py; fire times in
#                       config/schedules.yaml). Skips the scrape when the
#                       book already holds the day the SBS publishes (t-2
#                       reporting days): the job fires at 16:00 and again
#                       at 16:30 and 17:00, and only the first attempt
#                       that finds something should touch the SBS. Its
#                       outcome lands in job_runs like every other job.
#
# Unlike the file-driven SBS feeds this one does not use the
# backfill-pending dance: the series universe is closed and declared
# in config/afps.yaml, and ensure_registered() keeps the registry in
# sync on every run.
# ---------------------------------------------------------------

import logging
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pandas as pd

from src.db.connection import get_connection
from src.db.queries import update_series_run_metadata
from src.pipelines.prices.sbs.valor_cuota import afps
from src.pipelines.prices.sbs.valor_cuota.extract import (
    CHANNEL_DAILY, CHANNEL_HISTORY, load_stg, parse_daily, parse_history,
    prepare_stg)
from src.pipelines.prices.sbs.valor_cuota.loader import load_facts
from src.pipelines.prices.sbs.valor_cuota.transform import transform
from src.shared.paths import DATA_DIR

logger = logging.getLogger(__name__)

LOAD_MODES = ("missing", "replace")

# The cross-process scrape lock lives next to the browser profile's data.
SPP_DIR = DATA_DIR / "spp"
LOCK_FILE = SPP_DIR / "scrape.lock"


def ensure_registered() -> None:
    """Idempotent registration of the AFP series universe."""
    with get_connection() as conn:
        afps.register_series(conn)


@contextmanager
def scrape_lock():
    """
    One SPP scrape at a time, ACROSS processes.

    Every path to the SBS reaches the same visible Chrome and the same
    browser profile: the Windows task, its retries, a hand-launched run.
    The task scheduler's own guard (-MultipleInstances) only compares
    the task with itself, so a scrape launched by hand at 15:59 and the
    scheduled one a minute later both start: the second Chrome finds
    the profile's singleton, hands its URL to the first window and
    exits, and the pipeline reads a page that never loaded.
    """
    import os

    SPP_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
    held = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = True
        except OSError:
            raise RuntimeError(
                "An SPP scrape is already running (the scheduled task or a "
                "hand-launched run). Wait for it to finish: both use the same "
                "Chrome and the same browser profile.")
        os.lseek(fd, 1, os.SEEK_SET)
        os.write(fd, f"pid {os.getpid()}\n".encode())
        yield
    finally:
        try:
            if held:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def run_daily(run_date: date | None = None, force: bool = False) -> dict:
    """
    Scrape -> stage -> transform -> load. Returns a small result dict
    (dates seen, fact rows loaded) for logs and the scheduler.
    force=True restates: figures already in the book are replaced.
    """
    with scrape_lock():
        return _run_daily(run_date, force)


def _run_daily(run_date: date | None, force: bool) -> dict:
    from src.scrapers import spp as scraper

    run_date = run_date or date.today()
    logger.info(f"=== prices/sbs/valor_cuota | daily | run_date={run_date} "
                f"| mode={'force' if force else 'incremental'} ===")
    ensure_registered()

    html = scraper.fetch_daily_html(run_date)
    raw_df = parse_daily(html)
    stg_df = prepare_stg(raw_df, channel=CHANNEL_DAILY)

    # Staging in its own transaction, committed before the fact step: a
    # later fact failure must not discard the staged rows.
    with get_connection() as conn:
        load_stg(conn, stg_df)

    return _facts_from(stg_df, force)


def run_history(file: Path | None = None, download: bool = False,
                force: bool = False) -> dict:
    """
    Load the SBS historical XLS. `file` is a local path; with
    download=True it is fetched from the SBS index page instead (needs
    the interactive Chrome session).
    """
    logger.info(f"=== prices/sbs/valor_cuota | history | "
                f"file={file} download={download} ===")
    ensure_registered()

    if download:
        from src.scrapers import spp as scraper
        file = scraper.download_history_xls()
    if not file:
        raise ValueError("No file given: pass a path or download=True.")

    content = Path(file).read_bytes()
    return load_history(content, mode="replace" if force else "missing")


def load_history(content: bytes, mode: str = "missing") -> dict:
    """
    Writes an already-reviewed XLS in the chosen mode.

    missing:  inserts what the book does not have - new dates AND
              missing cells of known dates (in long format both are
              plain inserts on absent rows). Touches no loaded value.
    replace:  additionally replaces values that differ from the file.
              In no mode does an empty cell erase a value: a missing
              value is a row that never reaches the loader.
    """
    if mode not in LOAD_MODES:
        raise ValueError(f"Invalid load mode: {mode}. Use one of {', '.join(LOAD_MODES)}.")
    # An upload path enters here directly (no run_daily before it): on a
    # fresh database an empty series_map would silently drop every value
    # and report the load as done.
    ensure_registered()
    raw_df = parse_history(content)
    # Future dates in a hand-edited file must not enter the book.
    raw_df = raw_df[raw_df["date"] <= date.today()].reset_index(drop=True)
    if raw_df.empty:
        raise ValueError("Every date in the file is in the future.")
    stg_df = prepare_stg(raw_df, channel=CHANNEL_HISTORY)

    with get_connection() as conn:
        load_stg(conn, stg_df)

    result = _facts_from(stg_df, force=(mode == "replace"))
    result["mode"] = mode
    return result


def _facts_from(stg_df: pd.DataFrame, force: bool) -> dict:
    """Shared transform+load+metadata tail of both entry points."""
    with get_connection() as conn:
        series_map = afps.series_map(conn)

    facts_df = transform(stg_df, series_map)
    if facts_df.empty:
        logger.warning("Transform returned no fact rows.")
        return {"dates": 0, "loaded": 0, "skipped": 0}

    with get_connection() as conn:
        loaded, skipped = load_facts(conn, facts_df, force=force)
        # Operational trail per touched series.
        for sid, group in facts_df.groupby("series_id"):
            update_series_run_metadata(conn, int(sid), "success",
                                       group["date"].max())

    dates = int(facts_df["date"].nunique())
    logger.info(f"=== valor_cuota complete: {dates} dates, "
                f"{loaded} loaded, {skipped} skipped ===")
    return {"dates": dates, "loaded": loaded, "skipped": skipped}


# ---- Review (first half of a two-step upload) -----------------------

def review_history(content: bytes) -> dict:
    """
    Reads the XLS and says exactly what would happen, writing nothing.
    The report it returns is what a caller shows before choosing the
    load mode.
    """
    ensure_registered()
    unknown_afps: set[str] = set()
    df = parse_history(content, unknown_afps)

    today = date.today()
    future_dates = sorted(str(d) for d in df["date"].unique() if d > today)
    if future_dates:
        df = df[df["date"] <= today].reset_index(drop=True)
    if df.empty:
        raise ValueError("Every date in the file is in the future.")

    # Current book (valor cuota only - the XLS brings nothing else),
    # keyed by (afp, fondo, date).
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.procode, fp.date, fp.price
            FROM fact_prices fp
            JOIN series_registry sr ON sr.series_id = fp.series_id
            JOIN dim_entity e ON e.entity_id = sr.entity_id
            WHERE e.procode LIKE 'SPP\\_%%' AND e.entity_type = 'fund'
              AND sr.source = %s AND sr.field = 'PX_LAST'
            """,
            (afps.SOURCE_SBS_SPP,))
        rows = cur.fetchall()
    book: dict[tuple, float] = {}
    book_dates: set = set()
    for r in rows:
        parsed = afps.parse_procode(r["procode"])
        if parsed is None:
            continue
        book[(parsed[0], parsed[1], r["date"])] = float(r["price"])
        book_dates.add(r["date"])

    file_dates = set(df["date"])
    new_dates = file_dates - book_dates
    known_dates = file_dates & book_dates

    new_cells = fill_cells = changed_cells = unchanged_cells = 0
    examples = []
    # zip instead of iterrows: ~100k cells inside the request the user
    # is waiting on for the review report.
    for afp, fund, day, v in zip(df["afp"], df["fondo"], df["date"], df["valor_cuota"]):
        v = float(v)
        if day in new_dates:
            new_cells += 1
            continue
        current = book.get((afp, int(fund), day))
        if current is None:
            fill_cells += 1
        elif abs(current - v) > 1e-9:
            changed_cells += 1
            if len(examples) < 12:
                examples.append({
                    "date": str(day),
                    "column": f"{afp}_f{fund}",
                    "series": f"{afps.name_of(afp)} F{fund}",
                    "book": current, "file": v})
        else:
            unchanged_cells += 1

    return {
        "series": int(df.groupby(["afp", "fondo"]).ngroups),
        "dates": int(df["date"].nunique()),
        "from": str(df["date"].min()),
        "to": str(df["date"].max()),
        "values": int(len(df)),
        "new_dates": len(new_dates),
        "known_dates": len(known_dates),
        "new_cells": new_cells,
        "fill_cells": fill_cells,
        "changed_cells": changed_cells,
        "unchanged_cells": unchanged_cells,
        "examples": examples,
        "future_dates": future_dates[:10],
        "total_future": len(future_dates),
        "unknown_afps": sorted(unknown_afps),
        "book_dates": len(book_dates),
        "sample": _file_sample(df),
    }


def _file_sample(df: pd.DataFrame, rows: int = 15) -> dict:
    """Last rows of the file in wide form, most recent first - the
    visual half of the review: counts say HOW MUCH enters, the sample
    lets one check it enters RIGHT."""
    wide = (df.assign(col=[f"{afps.name_of(a)} F{f}"
                           for a, f in zip(df["afp"], df["fondo"])])
            .pivot_table(index="date", columns="col", values="valor_cuota",
                         aggfunc="last")
            .sort_index(ascending=False).head(rows))
    return {
        "columns": list(wide.columns),
        "rows": [[str(day)] + [None if pd.isna(v) else float(v) for v in row]
                 for day, row in wide.iterrows()],
        "total": int(df["date"].nunique()),
    }


# ---- The scheduler job (acquire_spp) --------------------------------

def expected_date(today: date | None = None) -> date:
    """
    The day the SBS page is expected to have published by now: two
    reporting days back on the SBS calendar (NYSE or Lima open), so a
    holiday on both exchanges does not make the retries open Chrome for
    a day that will never be published.
    """
    from src.calendars.calendar_sbs import prev_reporting_day
    return prev_reporting_day(prev_reporting_day(today or date.today()))


def book_has_date(day: date) -> bool:
    """True when every AFP valor cuota series has a row for `day`."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) AS series, COUNT(fp.series_id) AS with_data
            FROM series_registry sr
            JOIN dim_entity e ON e.entity_id = sr.entity_id
            LEFT JOIN fact_prices fp
                   ON fp.series_id = sr.series_id AND fp.date = %s
            WHERE sr.source = %s AND sr.field = %s
              AND e.procode LIKE 'SPP\\_%%' AND e.entity_type = 'fund'
            """,
            (day, afps.SOURCE_SBS_SPP, afps.METRIC_FIELD["valor_cuota"]))
        row = cur.fetchone()
    return bool(row) and row["series"] > 0 and row["with_data"] == row["series"]


def run_scheduled(force: bool = False) -> date:
    """
    The body of the scheduler job acquire_spp (and of the CLI's
    --scheduled): when the book already holds the day the SBS publishes
    (t-2 reporting days) for every AFP, nothing is scraped and no Chrome
    opens - the 16:30 and 17:00 attempts land here when 16:00 already
    brought the day. Otherwise run_daily(). Returns the expected date;
    raises on failure so the job_runs row records the error.
    """
    from src.configs.machine_config import machine_id, scraper_enabled

    if not scraper_enabled():
        raise RuntimeError(
            f"The scraper is not enabled on this machine ({machine_id()}). "
            "Set SCRAPER_ENABLED=true in the project's .env.")
    expected = expected_date()
    if not force and book_has_date(expected):
        logger.info(f"The book already holds {expected} (t-2 reporting days) for "
                    "every AFP: the SBS is not scraped.")
        return expected
    run_daily(force=force)
    return expected
