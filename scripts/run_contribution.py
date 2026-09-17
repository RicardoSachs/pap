# scripts/run_contribution.py
# ---------------------------------------------------------------
# CLI entry point for the daily contribution fact (Postgres only).
#
# Usage:
#   python scripts/run_contribution.py --start-date 2026-08-01 --end-date 2026-08-31
#   python scripts/run_contribution.py --start-date 2026-08-01 --end-date 2026-08-31 --check
#
# --check runs the fund-day tie-out assertion after the load.
# ---------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.analytics.contribution.run import run_full, check
from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild fact_contribution for a date range.")
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--check", action="store_true", help="assert the cuota tie-out after loading")
    args = parser.parse_args()

    setup_logging('run_contribution')
    run_full(start_date=args.start_date, end_date=args.end_date)
    if args.check:
        check(args.start_date, args.end_date)


if __name__ == "__main__":
    main()
