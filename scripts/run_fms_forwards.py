# scripts/run_fms_forwards.py
# ---------------------------------------------------------------
# CLI entry point for the FMS forwards pipeline.
#
# Thin shell: parses argparse, sets up logging, dispatches to the
# run() wrappers in src/pipelines/positions/fms/forwards/run.py.
#
# Usage:
#   python scripts/run_fms_forwards.py --start-date 2026-06-22 --end-date 2026-06-22
#   python scripts/run_fms_forwards.py --start-date 2026-06-01 --end-date 2026-06-30
#   python scripts/run_fms_forwards.py --from-stg --batch-id fms_forwards_20260622_081532
#   python scripts/run_fms_forwards.py --start-date 2025-01-01 --end-date 2025-12-31 --force
#
# Flags:
#   --start-date YYYY-MM-DD    required unless --from-stg
#   --end-date YYYY-MM-DD      required unless --from-stg
#   --from-stg                 skip FMS, rebuild fact from staging
#   --batch-id STR             required with --from-stg
#   --force                    override MAX_RANGE_DAYS guard in extract
#   --allow-unresolved         don't fail when a fund can't be resolved
#                              to a portfolio (e.g. historical backfills)
# ---------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.positions.fms.forwards.run import run_full, run_from_stg

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
        description="Run the FMS forwards pipeline (extract, stage, fact-load)."
    )
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--from-stg", action="store_true",
                   help="skip FMS extract, rebuild fact from existing staging batch")
    parser.add_argument("--batch-id", type=str,
                   help="required with --from-stg")
    parser.add_argument("--force", action="store_true",
                   help="override MAX_RANGE_DAYS guard in extract (allows large backfills)")
    parser.add_argument("--allow-unresolved", action="store_true", dest="allow_unresolved",
                   help="don't fail when a codigo_fondo can't be resolved to a portfolio")

    args = parser.parse_args()

    if args.from_stg:
        if not args.batch_id:
            parser.error("--from-stg requires --batch-id")
    else:
        if not (args.start_date and args.end_date):
            parser.error("--start-date and --end-date are required unless --from-stg")

    return args


if __name__ == "__main__":
    setup_logging('run_position_fms_forwards')
    main()
