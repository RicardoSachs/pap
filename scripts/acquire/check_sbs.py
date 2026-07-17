# scripts/acquire/check_sbs.py
# ---------------------------------------------------------------
# Validates that today's SBS files have arrived in data/raw/
# before the central PC ingestion pipeline runs.
#
# Only meaningful when acquisition runs on a different machine
# than the central PC. When acquisition runs locally, the
# scheduler already gates ingestion via acquire_sbs.py exit code.
# 
# Exits with code 1 if any expected file is missing so the
# scheduler suppresses the ingestion step automatically.
#
# Usage:
#   python scripts/acquire/check_sbs.py
#   python scripts/acquire/check_sbs.py --date 2026-03-10
#   python scripts/acquire/check_sbs.py --file-types vector_completo rf_local
# ---------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0,
                str(Path(__file__).resolve().parent.parent.parent)
                )

from src.scrapers.sbs import find_latest_file, SBS_FILES
from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)

def main() -> None:
    known_types = SBS_FILES.keys()

    parser = argparse.ArgumentParser(
        description=(
            "Checks whether today's SBS files have arrived in data/raw/. "
            'Exits with code 1 if any file is missing.'
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--date',
        type=date.fromisoformat,
        default=None,
        help='Date to check in YYYY-MM-DD format. Defaults to today - 1.'
    )
    parser.add_argument(
        '--file-types',
        nargs='+',
        default=None,
        dest='file_types',
        help=(
            'File types to check. Checks all if omitted.\n'
            f'Options: {", ".join(known_types)}'
        )
    )

    args = parser.parse_args()
    setup_logging('check_sbs')
    
    run_date = args.date or (date.today() - timedelta(days=1))
    date_prefix = run_date.strftime('%Y%m%d')

    files_to_check = (
        {k:f for k, f in SBS_FILES.items() if k in args.file_types}
        if args.file_types
        else SBS_FILES
    )

    logger.info(
        f'=== SBS file check | run_date={run_date} | '
        f'checking {len(files_to_check)} file types ==='
    )

    all_present = True
    for file_name, file_cfg in files_to_check.items():
        path = find_latest_file(file_cfg['folder'], run_date)

        if path is None or path.stem[:8] != date_prefix:
            logger.warning(
                f"{file_name}: today's file not found. "
                f'Expected in data/raw/sbs/vector_precios/'
                f'{file_cfg["folder"]}/.'
                f'Run acquire_sbs.py on the acquisition machine.'
            )
            all_present = False
        else:
            logger.info(f'{file_name}: OK ({path.name})')

    if not all_present:
        logger.error(
            f'One or more SBS files missing for {run_date}. '
            f'Ingestino will be skipped.'
        )
        sys.exit(1)

    logger.info(f'All SBS files present for {run_date}. Ready for ingestion.')

if __name__ == "__main__":
    main()
