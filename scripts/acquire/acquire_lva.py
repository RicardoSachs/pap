
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
from src.scrapers.lva import download_day

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Automated daily LVA Indices acquisition.',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--date',
        type=date.fromisoformat,
        default=None,
        help='Reference date for file naming. Defaults to today - 1.'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='Seconds to wait for scraping. Default: 10.'
    )
    args = parser.parse_args()
    
    setup_logging('acquire_lva')
    run_date = args.date or (date.today()-timedelta(days=1))

    success = download_day(
        run_date=run_date,
        timeout_seconds=args.timeout
    )
    
    logger.info(f'Acquisition complete')
    
    logger.info(
        f'All files ready. Run ingestion with: '
        f'python scripts/run_price.py TODOOOOOOOOOOO'
    )

if __name__ == '__main__':
    main()
