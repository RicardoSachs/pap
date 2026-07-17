# scripts/acquire/acquire_sbs_range.py
# ---------------------------------------------------------------
# Bulk SBS acquisition for initial or catch-up loads.
# Single browser session: logs in once, queries portal for
# eligible dates, diffs against raw/, downloads what is missing.
#
# Usage:
#   # Full history from 2020 to today
#   python scripts/acquire/acquire_sbs_range.py --start 2020-01-01
#
#   # Scoped date range
#   python scripts/acquire/acquire_sbs_range.py --start 2024-01-01 --end 2024-12-31
#
#   # Specific file types only
#   python scripts/acquire/acquire_sbs_range.py --start 2020-01-01 --file-types tasa_activa_mn tipo_cambio
#
#   # Custom retry settings
#   python scripts/acquire/acquire_sbs_range.py --start 2020-01-01 --max-retries 5 --retry-delay 60
# ---------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, 
                str(Path(__file__).resolve().parent.parent.parent)
                )

from src.shared.logging import setup_logging
from src.scrapers.sbs import (
    acquire_range, SBS_FILES, SBS_FILES_LEGACY, VP_SBS_DIR, VP_SBS_DIR_LEGACY
)
from src.configs.machine_config import assert_scraper

logger = logging.getLogger(__name__)


def main() -> None:
    assert_scraper()
    known_types = SBS_FILES_LEGACY.keys()

    parser = argparse.ArgumentParser(
        description="Bulk SBS acquisition across a date range.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        required=True,
        help="Start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="End date in YYYY-MM-DD format. Defaults to today - 1.",
    )
    parser.add_argument(
        "--file-types",
        nargs="+",
        default=None,
        dest="file_types",
        help=(
            "File types to download. Downloads all if omitted. "
            f"Options: {', '.join(known_types)}"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=720,
        help="Seconds to wait for manual login. Default: 720.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=10,
        dest="max_retries",
        help="Max download attempts per file before giving up. Default: 10.",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=10,
        dest="retry_delay",
        help="Seconds between retry attempts. Default: 10.",
    )
    parser.add_argument(
        '--legacy',
        action="store_true",
        default=False,
        help='Run legacy download. Defaults to false'
    )

    args     = parser.parse_args()
    end_date = args.end or (date.today()-timedelta(days=1))

    setup_logging('acquire_sbs_range_legacy' if args.legacy else 'acquire_sbs_range')

    logger.info(
        f"=== SBS range acquisition | "
        f"{args.start} to {end_date} | "
        f"file_types={args.file_types or 'all'} ==="
    )

    raw_dir = VP_SBS_DIR_LEGACY if args.legacy else None
    sbs_files = SBS_FILES_LEGACY if args.legacy else None

    results = acquire_range(
        start_date=args.start,
        end_date=end_date,
        file_types=args.file_types,
        timeout_seconds=args.timeout,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
        raw_dir=raw_dir,
        sbs_files=sbs_files
    )

    succeeded = results["succeeded"]
    failed    = results["failed"]
    skipped   = results["skipped"]

    logger.info(
        f"Summary: {len(succeeded)} succeeded, "
        f"{len(failed)} failed, {len(skipped)} skipped."
    )

    if failed:
        failed_sorted = sorted(failed)
        logger.error(
            f"{len(failed)} dates failed. Re-run with: "
            f"python scripts/acquire/acquire_sbs_range.py "
            f"--start {failed_sorted[0]} --end {failed_sorted[-1]}"
            + (f" --file-types {' '.join(args.file_types)}" if args.file_types else "")
        )
        sys.exit(1)

if __name__ == "__main__":
    main()
