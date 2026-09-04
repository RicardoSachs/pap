# scripts/run_fms_holdings.py
# ---------------------------------------------------------------
# CLI entry point for the FMS holdings feed (securities + deposits +
# portfolio valuation) from the IDI daily valorization.
#
# Usage:
#   python scripts/run_fms_holdings.py --start-date 2026-08-31 --end-date 2026-08-31
#   python scripts/run_fms_holdings.py --start-date 2026-08-01 --end-date 2026-08-31
#   python scripts/run_fms_holdings.py --from-stg --batch-id fms_holdings_20260831_081532
#   python scripts/run_fms_holdings.py --start-date 2025-01-01 --end-date 2025-12-31 --force
#
# Flags:
#   --start-date / --end-date  required unless --from-stg
#   --from-stg                 skip FMS, rebuild the facts from staging
#   --batch-id STR             required with --from-stg
#   --force                    override MAX_RANGE_DAYS guard in extract
#   --allow-unresolved         don't fail on unresolved funds/securities
# ---------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.positions.fms.holdings.run import run_full, run_from_stg

from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)

def main() -> None:
    args = _parse_args()

    if args.from_stg:
        run_from_stg(batch_id=args.batch_id)
    else:
        run_full(
            start_date=args.start_date,
            end_date=args.end_date,
            force=args.force,
            allow_unresolved=args.allow_unresolved,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the FMS holdings pipeline (extract, stage, 3-fact load)."
    )
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--from-stg", action="store_true",
                   help="skip FMS extract, rebuild the facts from an existing staging batch")
    parser.add_argument("--batch-id", type=str, help="required with --from-stg")
    parser.add_argument("--force", action="store_true",
                   help="override MAX_RANGE_DAYS guard in extract")
    parser.add_argument("--allow-unresolved", action="store_true", dest="allow_unresolved",
                   help="don't fail when a fund or security can't be resolved")

    args = parser.parse_args()

    if args.from_stg:
        if not args.batch_id:
            parser.error("--from-stg requires --batch-id")
    else:
        if not (args.start_date and args.end_date):
            parser.error("--start-date and --end-date are required unless --from-stg")

    return args


if __name__ == "__main__":
    setup_logging('run_position_fms_holdings')
    main()
