# scripts/onboard_bloomberg_series.py
# ---------------------------------------------------------------
# Applies the held-universe rule for Bloomberg PX_LAST series
# (src/db/onboard.py::register_bloomberg_series, docs/BLOOMBERG_SBS.md):
# registers a series for every Bloomberg-covered instrument held within
# the trailing window, suspends series whose name left the window, and
# reactivates ones that came back. Writes series_registry only - no
# Bloomberg call - so it runs on either machine. History for new series
# is pulled afterwards on the workstation:
#
#   python scripts/onboard_series.py --backfill --backfill-source bloomberg
#
# Usage:
#   python scripts/onboard_bloomberg_series.py --dry-run     # show what would change
#   python scripts/onboard_bloomberg_series.py               # apply
#   python scripts/onboard_bloomberg_series.py --held-within-days 730 --buffer-days 60
# ---------------------------------------------------------------

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.onboard import register_bloomberg_series
from src.shared.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register PX_LAST/bloomberg series for held, covered SBS instruments.",
    )
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="list the candidates without writing series_registry")
    parser.add_argument("--buffer-days", type=int, default=30, dest="buffer_days",
                        help="default_start_date = first held date minus this (default 30)")
    parser.add_argument("--held-within-days", type=int, default=1095, dest="held_within_days",
                        help="a name held within this many days counts as held (default 1095)")
    args = parser.parse_args()

    setup_logging("onboard_bloomberg_series")
    result = register_bloomberg_series(
        dry_run=args.dry_run,
        buffer_days=args.buffer_days,
        held_within_days=args.held_within_days,
    )
    verb = "would" if args.dry_run else "did"

    print(f"-- register ({len(result['register'])}) --")
    for c in result['register']:
        print(f"{c['entity_id']:>7}  {c['procode']:<24} {c['parsekyable']:<28} "
              f"first_held={c['first_held']}  start={c['default_start_date']}  {c['name'] or ''}")
    print(f"-- suspend ({len(result['suspend'])}): last held before the window --")
    for c in result['suspend']:
        print(f"{c['entity_id']:>7}  {c['procode']:<24} last_held={c['last_held']}")
    print(f"-- reactivate ({len(result['reactivate'])}): held again within the window --")
    for c in result['reactivate']:
        print(f"{c['entity_id']:>7}  {c['procode']:<24} last_held={c['last_held']}")
    print(f"rule {verb} register {len(result['register'])}, suspend {len(result['suspend'])}, "
          f"reactivate {len(result['reactivate'])}"
          + (" (dry run)" if args.dry_run else ""))

if __name__ == "__main__":
    main()
