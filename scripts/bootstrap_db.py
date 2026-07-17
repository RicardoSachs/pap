# scripts/bootstrap_db.py
# ---------------------------------------------------------------
# Entry point for first-time database setup.
#
# Usage examples:
#   # Schema + seeds only (safest first run)
#   python scripts/bootstrap_db.py
#
#   # Schema + seeds + dim enrichment for all vendors
#   python scripts/bootstrap_db.py --enrich
#
#   # Schema + seeds + enrich bloomberg securities only
#   python scripts/bootstrap_db.py --enrich --enrich-vendor bloomberg --enrich-domain security
#
#   # Full bootstrap: seeds + enrich + backfill all
#   python scripts/bootstrap_db.py --enrich --backfill
#
#   # Full bootstrap scoped to prices/bloomberg only
#   python scripts/bootstrap_db.py --enrich --enrich-vendor bloomberg
#       --backfill --backfill-domain prices --backfill-source bloomberg
# ---------------------------------------------------------------

import argparse
import sys
from pathlib import Path

sys.path.insert(0,
                str(Path(__file__).resolve().parent.parent))

from src.db.bootstrap import run_bootstrap
from src.shared.logging import setup_logging

def main() -> None:
    parser =argparse.ArgumentParser(
        description='Bootstrap the market data database.',
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        '--enrich',
        action='store_true',
        default=False,
        help='Run dim enrichment pipelines after seed loading.'
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
        help='Run fact backfill for all backfill-pending series after seeding.'
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
    setup_logging('bootstrap')

    run_bootstrap(
        enrich=args.enrich,
        enrich_vendor=args.enrich_vendor,
        enrich_domain=args.enrich_domain,
        run_backfill=args.backfill,
        backfill_domain=args.backfill_domain,
        backfill_source=args.backfill_source
    )


if __name__ == "__main__":
    main()
