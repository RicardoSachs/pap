
# --------------------------------------------------------------
# Daily LVA file acquisition entry point.
# Automatically downloads the table for run_date.
#
# Usage:
#   python scripts/acquire/acquire_lva.py
#   python scripts/acquire/acquire_lva.py --date 2026-08-03
#   python scripts/acquire/acquire_lva.py --timeout 20
# --------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0,
                str(Path(__file__).resolve().parent.parent.parent)
                )

from src.shared.logging import setup_logging
from src.scrapers.lva import download_range

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='LVA Indices acquisition across a date range.',
        formatter_class=argparse.RawTextHelpFormatter
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
        '--timeout',
        type=int,
        default=10,
        help='Seconds to wait for scraping. Default: 10.'
    )
    args = parser.parse_args()
    end_date = args.end or (date.today()-timedelta(days=1))
    
    setup_logging('acquire_lva_range')

    results = download_range(
        start_date=args.start,
        end_date=end_date,
        timeout_seconds=args.timeout
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
            f"python scripts/acquire/acquire_lva_range.py "
            f"--start {failed_sorted[0]} --end {failed_sorted[-1]}"
        )
        sys.exit(1)
    
    logger.info(
        f'All files ready. Run ingestion with: '
        f'python scripts/run_price.py TODO'
    )

if __name__ == '__main__':
    main()
