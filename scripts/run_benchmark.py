# scripts/run_benchmark.py
# ---------------------------------------------------------------
# CLI entry point for the benchmark analytics (Postgres only).
#
# Usage:
#   python scripts/run_benchmark.py                          # materialize every active benchmark
#   python scripts/run_benchmark.py --procode SPP_BENCH_F2   # one benchmark
#   python scripts/run_benchmark.py --procode SPP_BENCH_F2 --from-date 2026-01-01
#   python scripts/run_benchmark.py --define config/benchmarks/spp_bench_f2.json
#   python scripts/run_benchmark.py --define spec.json --no-materialize
#   python scripts/run_benchmark.py --changelog SPP_BENCH_F2
#
# --define appends ONE version from a JSON file (definitions.define
# documents the shape) and materializes the benchmark in the same
# transaction. Definitions are append-only: there is no flag to edit
# or delete a version; add another one with its reason.
# ---------------------------------------------------------------

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.analytics.benchmark.run import run_changelog, run_define, run_materialize
from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Define and materialize benchmarks (composite indices).")
    parser.add_argument("--procode", help="materialize this benchmark only")
    parser.add_argument("--from-date", type=date.fromisoformat,
                        help="rebuild from this date forward, anchored at the stored level")
    parser.add_argument("--define", metavar="FILE",
                        help="append the version described in this JSON file")
    parser.add_argument("--no-materialize", action="store_true",
                        help="with --define: record the version without materializing")
    parser.add_argument("--changelog", metavar="PROCODE",
                        help="print the changelog of this benchmark and exit")
    args = parser.parse_args()

    setup_logging("run_benchmark")

    if args.changelog:
        for r in run_changelog(args.changelog):
            before = "" if r["weight_before"] is None else f"{r['weight_before']:.4f}"
            after = "" if r["weight_after"] is None else f"{r['weight_after']:.4f}"
            print(f"v{r['version_id']:<4} {r['effective_from']} {r['change_type']:<18} "
                  f"{r['change']:<10} {r['label']:<24} {before:>8} -> {after:<8} "
                  f"| {r['reason']}")
        return

    if args.define:
        result = run_define(args.define, materialize_after=not args.no_materialize)
        logger.info(f"defined {result['procode']}: version_id={result['version_id']}")
        return

    for summary in run_materialize(args.procode, args.from_date):
        logger.info(
            f"{summary['procode']}: {summary['dates']} dates "
            f"{summary['from']}..{summary['to']} level {summary['level']:,.4f}")


if __name__ == "__main__":
    main()
