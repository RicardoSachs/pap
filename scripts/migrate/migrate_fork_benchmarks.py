# scripts/migrate/migrate_fork_benchmarks.py
# ---------------------------------------------------------------
# ONE-SHOT. Brings a database created from the fork's SPP branch to
# the benchmark analytics model of PR C.
#
# The fork registered the composite indices as dim_entity rows of
# type 'index' (SPP_TARGET_F{n}, SPP_BENCH_F{n}) with a PX_LAST series
# whose source was 'benchmark', and kept their definitions in two
# tables of its own (`benchmark`, `benchmark_composicion`). PR C keeps
# the entities, moves the level series to source 'model', gives each
# index the dim_portfolio row the analytics layer keys on, and leaves
# the definitions to dim_benchmark_version / benchmark_constituent.
#
# What it does, per index entity whose series has source 'benchmark':
#   1. series_registry.source 'benchmark' -> 'model' (and the few
#      stored fact_prices rows follow);
#   2. dim_portfolio (procode, 'model', 'benchmark') with
#      parent_entity_id = the entity, display_name = dim_entity.name.
# The fork's definition tables are NOT translated: on every database
# seen they were empty (verified 2026-10-13), and a basket needs a
# reason to become a version anyway. --drop-legacy drops them; by
# default they are left in place and only counted.
#
# Dry by default: nothing is written without --apply. Idempotent: a
# second run finds nothing to move. Not part of any scheduled path;
# delete once no database created from the fork exists anywhere.
#
# Usage:
#   python scripts/migrate/migrate_fork_benchmarks.py             # report only
#   python scripts/migrate/migrate_fork_benchmarks.py --apply
#   python scripts/migrate/migrate_fork_benchmarks.py --apply --drop-legacy
# ---------------------------------------------------------------

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.db.connection import get_connection
from src.pipelines.analytics.benchmark import definitions
from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)

LEGACY_SOURCE = "benchmark"
LEGACY_TABLES = ("benchmark_composicion", "benchmark")


def legacy_series(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT e.entity_id, e.procode, e.name, sr.series_id,
               (SELECT COUNT(*) FROM fact_prices f WHERE f.series_id = sr.series_id) AS points
        FROM dim_entity e
        JOIN series_registry sr ON sr.entity_id = e.entity_id
        WHERE e.entity_type = 'index' AND sr.field = %s AND sr.source = %s
        ORDER BY e.procode
        """,
        (definitions.LEVEL_FIELD, LEGACY_SOURCE))
    return cur.fetchall()


def legacy_tables(conn) -> dict[str, int | None]:
    """Row count per legacy table, None when the table does not exist."""
    cur = conn.cursor()
    out = {}
    for table in LEGACY_TABLES:
        cur.execute("SELECT to_regclass(%s) AS oid", (table,))
        if cur.fetchone()["oid"] is None:
            out[table] = None
            continue
        cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
        out[table] = cur.fetchone()["n"]
    return out


def migrate(conn, apply: bool, drop_legacy: bool) -> None:
    rows = legacy_series(conn)
    tables = legacy_tables(conn)
    logger.info(f"{len(rows)} index series with source {LEGACY_SOURCE!r}; "
                f"legacy tables: {tables}.")
    for r in rows:
        logger.info(f"  {r['procode']:<16} series_id={r['series_id']} "
                    f"{r['points']} point(s)  name={r['name']!r}")
    if not apply:
        logger.info("Dry run: nothing written. Re-run with --apply.")
        return

    cur = conn.cursor()
    for r in rows:
        cur.execute(
            "UPDATE series_registry SET source = %s, updated_at = NOW() WHERE series_id = %s",
            (definitions.SOURCE_MODEL, r["series_id"]))
        cur.execute(
            "UPDATE fact_prices SET source = %s WHERE series_id = %s AND source <> %s",
            (definitions.SOURCE_MODEL, r["series_id"], definitions.SOURCE_MODEL))
        moved = cur.rowcount
        bench = definitions.ensure_benchmark(conn, r["procode"], r["name"] or r["procode"])
        logger.info(f"  {r['procode']}: series -> {definitions.SOURCE_MODEL} "
                    f"({moved} level(s) relabelled), portfolio_id={bench['portfolio_id']}.")

    if drop_legacy:
        for table in LEGACY_TABLES:
            if tables.get(table) is None:
                continue
            cur.execute(f"DROP TABLE IF EXISTS {table}")
            logger.info(f"  dropped {table} ({tables[table]} row(s)).")
    elif any(n is not None for n in tables.values()):
        logger.info("Legacy tables left in place (use --drop-legacy to remove them).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move a fork-created database to the PR C benchmark model.")
    parser.add_argument("--apply", action="store_true", help="write (default: report only)")
    parser.add_argument("--drop-legacy", action="store_true",
                        help="with --apply: drop benchmark_composicion and benchmark")
    args = parser.parse_args()

    setup_logging("migrate_fork_benchmarks")
    with get_connection() as conn:
        migrate(conn, apply=args.apply, drop_legacy=args.drop_legacy)


if __name__ == "__main__":
    main()
