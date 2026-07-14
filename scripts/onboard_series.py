
# ---------------------------------------------------------------
# Entry point for incremental series onboarding.
# Run after adding new rows to series.csv.
#
# Usage examples:
#   # Register new series only
#   python scripts/onboard_series.py
#
#   # Register + enrich dims for all vendors
#   python scripts/onboard_series.py --enrich
#
#   # Register + enrich bloomberg securities only
#   python scripts/onboard_series.py --enrich --enrich-vendor bloomberg --enrich-domain security
#
#   # Register + enrich + backfill all pending
#   python scripts/onboard_series.py --enrich --backfill
#
#   # Register + backfill prices/bloomberg only
#   python scripts/onboard_series.py --backfill --backfill-domain prices --backfill-source bloomberg
# ---------------------------------------------------------------

import argparse
import sys
from pathlib import Path

sys.path.insert(0,
                str(Path(__file__).resolve().parent.parent))

from src.db.onboard import run_onboard, run_backfill_pending
from src.shared.logging import setup_logging

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Onboard new series from series.csv into the database.',
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        '--enrich',
        action='store_true',
        default=False,
        help='Run dim enrichment pipelines after onboarding.'
    )
    parser.add_argument(
        '--enrich-vendor',
        type=str,
        default=None,
        dest='enrich_vendor',
        help='Filter dim enrichment by vendor (e.g., bloomberg, sbs)'
    )
    parser.add_argument(
        '--enrich-domain',
        type=str,
        default=None,
        dest='enrich_domain',
        help='Filter dim enrichment by domain (e.g., security, macro)'
    )
    parser.add_argument(
        '--backfill',
        action='store_true',
        default=False,
        help='Trigger fact backfill for all backfill-pending series.'
    )
    parser.add_argument(
        '--backfill-domain',
        type=str,
        default=None,
        dest='backfill_domain',
        help='Filter backfill by domain (prices, fundamentals, macro).'
    )
    parser.add_argument(
        '--backfill-source',
        type=str,
        default=None,
        dest='backfill_source',
        help='Filter backfill by source (bloomberg, sbs, etc.).'
    )

    args = parser.parse_args()
    setup_logging('onboard')

    run_onboard(
        enrich=args.enrich,
        enrich_vendor=args.enrich_vendor,
        enrich_domain=args.enrich_domain,
    )

    if args.backfill:
        run_backfill_pending(
            domain=args.backfill_domain,
            source=args.backfill_source
        )


if __name__ == '__main__':
    main()
