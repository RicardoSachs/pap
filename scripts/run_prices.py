# scripts/run_prices.py
# ---------------------------------------------------------------
# Scheduler entry point for fact prices pipelines.
# Dispatches to vendor/file-type specific price pipelines.
#
# Usage:
#   # Bloomberg daily prices (incremental)
#   python scripts/run_prices.py --source bloomberg
#
#   # Bloomberg for a specific date
#   python scripts/run_prices.py --source bloomberg --date 2026-03-10
#
#   # Bloomberg backfill all pending
#   python scripts/run_prices.py --source bloomberg --backfill
#
#   # SBS all file types (incremental)
#   python scripts/run_prices.py --source sbs
#
#   # SBS specific file type only
#   python scripts/run_prices.py --source sbs --file-type rf_local
#
#   # SBS backfill all pending, specific file type
#   python scripts/run_prices.py --source sbs --file-type rf_local --backfill
#
#   # SBS backfill all file types
#   python scripts/run_prices.py --source sbs --backfill
#
#   # SBS restatement: replace one date (re-download the raw file first
#   # with acquire_sbs.py --force, then)
#   python scripts/run_prices.py --source sbs --date 2026-09-21 --force
# ---------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.prices.sbs.registry import SBS_PIPELINES, run_sbs_pipelines
from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the prices fact pipeline.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Run date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="bloomberg",
        choices=["bloomberg", "sbs"],
        help="Data source to run. Defaults to bloomberg.",
    )
    parser.add_argument(
        "--file-type",
        type=str,
        default=None,
        dest="file_type",
        choices=list(SBS_PIPELINES.keys()),
        help=(
            "SBS file type to run. Only valid when --source sbs.\n"
            f"Options: {', '.join(SBS_PIPELINES.keys())}.\n"
            "Runs all SBS file types if omitted."
        ),
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        default=False,
        help="Run in backfill mode: processes all backfill-pending series.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="SBS only: restate --date. Replaces staging rows for that date and upserts fact_prices.",
    )

    args = parser.parse_args()

    # Validate --file-type is only used with --source sbs
    if args.file_type and args.source != "sbs":
        parser.error("--file-type is only valid when --source sbs.")
    if args.force and (args.source != "sbs" or args.date is None):
        parser.error("--force requires --source sbs and an explicit --date.")

    setup_logging("run_prices")

    series_override: Optional[list[dict]] = None

    # ---- Bloomberg ---------------------------------------------
    if args.source == "bloomberg":
        from src.configs.machine_config import assert_bloomberg
        assert_bloomberg()

        if args.backfill:
            from src.db.connection import get_connection
            from src.db.queries import get_backfill_pending_series
            with get_connection() as conn:
                series_override = get_backfill_pending_series(
                    conn, domain="prices", source="bloomberg"
                )

        from src.pipelines.prices.bloomberg.run import run
        run(run_date=args.date, series_override=series_override)

    # ---- SBS ---------------------------------------------------
    elif args.source == "sbs":
        if args.backfill:
            from src.db.connection import get_connection
            from src.db.queries import get_backfill_pending_series
            with get_connection() as conn:
                series_override = get_backfill_pending_series(
                    conn, domain="prices", source="sbs"
                )

        run_sbs_pipelines(
            run_date=args.date,
            series_override=series_override,
            file_type=args.file_type,
            force=args.force,
        )


if __name__ == "__main__":
    main()
