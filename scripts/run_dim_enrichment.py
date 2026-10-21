# scripts/run_dim_enrichment.py
# ---------------------------------------------------------------
# Generic entry point for dim enrichment pipelines.
# Dispatches to vendor/domain-specific enrichment pipelines
# via the registry in src/db/bootstrap.run_dim_enrichment().
#
# Scheduled weekly (scheduler.py, job dim_enrichment) in 'new' mode:
# only securities never asked about, plus unrecognised ones past the
# retry window. --refresh re-requests the recently held set (entities
# with a non-terminal Bloomberg series); run it by hand when a name,
# sector or market status is suspected stale. See docs/BLOOMBERG_SBS.md.
#
# Usage:
#   # New securities only (what the scheduler runs)
#   python scripts/run_dim_enrichment.py
#
#   # Refresh the recently held set
#   python scripts/run_dim_enrichment.py --refresh
#
#   # Re-ask unrecognised ISINs sooner than the 90-day default
#   python scripts/run_dim_enrichment.py --retry-days 30
#
#   # Enrich bloomberg securities only
#   python scripts/run_dim_enrichment.py --vendor bloomberg --domain security
#
#   # Enrich all bloomberg dims
#   python scripts/run_dim_enrichment.py --vendor bloomberg
#
#   # Enrich all security dims across all vendors
#   python scripts/run_dim_enrichment.py --domain security
# ---------------------------------------------------------------

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.configs.machine_config import assert_bloomberg
from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run dim enrichment pipelines.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--vendor",
        type=str,
        default=None,
        help=(
            "Filter by vendor (e.g. bloomberg, refinitiv). "
            "Runs all vendors if omitted."
        ),
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help=(
            "Filter by domain (e.g. security). "
            "Runs all domains if omitted."
        ),
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-request entities with a non-terminal Bloomberg series instead of new ones",
    )
    parser.add_argument(
        "--retry-days",
        type=int,
        default=90,
        dest="retry_days",
        help="in 'new' mode, re-ask unrecognised securities older than this (default 90)",
    )

    args = parser.parse_args()
    setup_logging("run_dim_enrichment")
    mode = "refresh" if args.refresh else "new"

    # All dim enrichment pipelines currently require Bloomberg access.
    # If non-Bloomberg vendors are added later, move this guard
    # inside the vendor-specific branch.
    assert_bloomberg()

    logger.info(
        f"=== Dim enrichment | "
        f"vendor={args.vendor or 'all'} | "
        f"domain={args.domain or 'all'} | mode={mode} ==="
    )

    from src.db.bootstrap import run_dim_enrichment
    run_dim_enrichment(vendor=args.vendor, domain=args.domain,
                       mode=mode, retry_days=args.retry_days)


if __name__ == "__main__":
    main()
