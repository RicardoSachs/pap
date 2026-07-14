
# --------------------------------------------------------------
# Daily SBS file acquisition entry point.
# Opens browser, waits for manual login (image pad),
# then automatically downloads all files for run_date.
#
# Usage:
#   python scripts/acquire/acquire_sbs.py
#   python scripts/acquire/acquire_sbs.py --date 2026-08-03
#   python scripts/acquire/acquire_sbs.py --file-types vector_completo rf_local
#   python scripts/acquire/acquire_sbs.py --timeout 120
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
from src.scrapers.sbs import (
    acquire_day, all_files_present, SBS_FILES_LEGACY, VP_SBS_DIR_LEGACY
)
from src.configs.machine_config import assert_scraper

logger = logging.getLogger(__name__)


def main() -> None:
    assert_scraper()
    known_types = SBS_FILES_LEGACY.keys()

    parser = argparse.ArgumentParser(
        description='Semi-automated daily SBS file acquisition.',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--date',
        type=date.fromisoformat,
        default=None,
        help='Reference date for file naming. Defaults to today - 1.'
    )
    parser.add_argument(
        '--file-types',
        nargs='+',
        default=None,
        dest='file_types',
        help=(
            'File types to download. Downloads all if omitted.'
            f'Options: {", ".join(known_types)}'
        )        
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=720,
        help='Seconds to wait for manual login. Default: 720.'
    )
    parser.add_argument(
        '--legacy',
        action="store_true",
        default=False,
        help='Run legacy download. Defaults to false'
    )
    parser.add_argument(
        '--force',
        action="store_true",
        default=False,
        help='Force overwrite of already existing files'
    )
    args = parser.parse_args()
    
    setup_logging('acquire_sbs_legacy' if args.legacy else 'acquire_sbs')
    run_date = args.date or (date.today()-timedelta(days=1))

    if run_date.weekday() >= 5: #Force friday if run_date on weekend
        run_date -= timedelta(days = run_date.weekday() - 4) 

    raw_dir = VP_SBS_DIR_LEGACY if args.legacy else None
    sbs_files = SBS_FILES_LEGACY if args.legacy else None

    if not args.force and all_files_present(run_date, args.file_types, raw_dir, sbs_files):
        logger.info(f'All files present. Use --force to re-download')
        sys.exit(0)

    results = acquire_day(
        run_date=run_date,
        file_types=args.file_types,
        timeout_seconds=args.timeout,
        raw_dir=raw_dir,
        sbs_files=sbs_files,
        force=args.force
    )

    success_count = sum(1 for ok in results.values() if ok)
    total = len(results)
    
    logger.info(f'Acquisition complete: {success_count}/{total} files downloaded.')
    for name, ok in results.items():
        logger.info(f'{name}: {"OK" if ok else "FAILED"}')

    if success_count < total:
        logger.error('Some files failed. Resolve before runing ingestion.')
        sys.exit(1)

    logger.info(
        f'All files ready. Run ingestion with: '
        f'python scripts/run_price.py TODO'
    )

if __name__ == '__main__':
    main()
