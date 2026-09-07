# scripts/backfill_sbs.py
# ---------------------------------------------------------------
# File-driven backfill for SBS price pipelines - set-based path.
#
# Discovers available dates from raw filenames and hands them to
# src/pipelines/prices/sbs/backfill.py, which stages the whole range
# with bulk COPY, registers instruments ONCE for the span, loads
# fact_prices with one INSERT..SELECT per field inside Postgres, and
# sweeps series_registry / dim_security in single statements.
#
# The per-day incremental pipelines (each vector's run.py) are NOT
# used here - they remain the scheduler's daily path. This script
# replaced the old per-day loop, which re-ran registration and
# per-series classification for every date (tens of thousands of
# no-op statements per day per file type).
#
# Usage:
#   # Backfill all file types
#   python scripts/backfill_sbs.py
#
#   # Backfill specific file type(s)
#   python scripts/backfill_sbs.py --file-type rf_local rf_exterior
#
#   # Backfill within a date range
#   python scripts/backfill_sbs.py --start 2024-01-01 --end 2024-12-31
#
#   # Dry run: show available dates without loading
#   python scripts/backfill_sbs.py --file-type vector_completo --dry-run
#
#   # Re-stage dates even if already staged (facts are ON CONFLICT
#   # DO NOTHING either way; re-staged dates win via latest loaded_at)
#   python scripts/backfill_sbs.py --file-type rf_local --force
# ---------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.shared.logging import setup_logging
from src.shared.paths import RAW_DIR

logger = logging.getLogger(__name__)

# Maps file type to its raw subdirectory under data/raw/sbs/vector_precios/
FILE_TYPE_SUBDIR = {
    "vector_completo": "vector_completo",
    "rf_local":        "rfl",
    "rf_exterior":     "rfe",
    "tipo_cambio":     "tc",
    "dividendos":      "dividendos",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Set-based file-driven backfill for SBS price pipelines. "
            "Stages all available raw files for a range, then loads facts "
            "with set-based SQL."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--file-type",
        nargs="+",
        default=None,
        dest="file_types",
        choices=list(FILE_TYPE_SUBDIR.keys()),
        help=(
            "File type(s) to backfill. Runs all if omitted.\n"
            f"Options: {', '.join(FILE_TYPE_SUBDIR.keys())}"
        ),
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        help="Only process files on or after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="Only process files on or before this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Show available dates without running any pipelines.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help=(
            "Re-stage all dates even if already staged. Default: dates "
            "already present in the staging table are not re-read; the "
            "fact/metadata/dim phases run over the full span either way."
        ),
    )

    args       = parser.parse_args()
    file_types = args.file_types or list(FILE_TYPE_SUBDIR.keys())

    setup_logging("backfill_sbs_prices")
    logger.info(
        f"=== SBS backfill | file_types={file_types} | "
        f"start={args.start} | end={args.end} | "
        f"dry_run={args.dry_run} | force={args.force} ==="
    )

    for file_type in file_types:
        _backfill_file_type(
            file_type=file_type,
            start=args.start,
            end=args.end,
            dry_run=args.dry_run,
            force=args.force,
        )

    logger.info("=== SBS backfill complete ===")


# ---- Per file type backfill ------------------------------------

def _backfill_file_type(
    file_type: str,
    start: Optional[date],
    end: Optional[date],
    dry_run: bool,
    force: bool,
) -> None:
    logger.info(f"--- Backfill: {file_type} ---")

    available_dates = _discover_dates(file_type, start, end)

    if not available_dates:
        logger.warning(
            f"{file_type}: no raw files found in "
            f"{RAW_DIR / 'sbs' / 'vector_precios' / FILE_TYPE_SUBDIR[file_type]}."
        )
        return

    logger.info(f"{file_type}: {len(available_dates)} files available.")

    if dry_run:
        logger.info(f"{file_type}: dry run - dates that would be processed:")
        for d in available_dates:
            logger.info(f"  {d}")
        return

    from src.pipelines.prices.sbs.backfill import run_backfill

    try:
        run_backfill(file_type, available_dates, force=force)
    except Exception as e:
        logger.error(f"{file_type}: backfill failed: {e}", exc_info=True)
        # Continue to the next file type; every phase is idempotent, so
        # re-running this file type resumes where it left off.


# ---- Filesystem helpers ----------------------------------------

def _discover_dates(
    file_type: str,
    start: Optional[date],
    end: Optional[date],
) -> list[date]:
    """
    Scans data/raw/sbs/vector_precios/{subdomain}/ and extracts dates
    from YYYYMMDD_ prefixed filenames.
    Returns sorted list of dates within the optional range.
    """
    subdir = RAW_DIR / 'sbs' / 'vector_precios' / FILE_TYPE_SUBDIR[file_type]

    if not subdir.exists():
        return []

    dates = []
    for f in sorted(subdir.glob("*.xls*")):
        stem = f.stem
        if len(stem) >= 8 and stem[:8].isdigit():
            try:
                d = date(
                    int(stem[:4]),
                    int(stem[4:6]),
                    int(stem[6:8]),
                )
                if start and d < start:
                    continue
                if end and d > end:
                    continue
                dates.append(d)
            except ValueError:
                continue

    return sorted(set(dates))


if __name__ == "__main__":
    main()
