# src/pipelines/analytics/benchmark/run.py
# ---------------------------------------------------------------
# Entry points for the benchmark analytics: define from a file,
# materialize one or every benchmark. Each run_* opens its own
# connection (get_connection owns commit/rollback); the modules it
# calls take the connection, so tests drive them inside a transaction
# they roll back.
#
# Definitions are append-only and come from humans (a JSON file, see
# definitions.define); materialization is derived data and can be
# re-run at any time - it regenerates the same facts from the same
# versions.
# ---------------------------------------------------------------

import json
import logging
from pathlib import Path

from src.db.connection import get_connection
from src.pipelines.analytics.benchmark import definitions
from src.pipelines.analytics.benchmark.materialize import materialize

logger = logging.getLogger(__name__)


def run_define(spec_file, materialize_after: bool = True) -> dict:
    """
    Reads one definition file, appends the version it describes and,
    by default, materializes the benchmark in the same transaction -
    a definition that cannot be priced is rolled back with its facts.
    """
    spec = json.loads(Path(spec_file).read_text(encoding="utf-8"))
    with get_connection() as conn:
        result = definitions.define(conn, spec)
        if materialize_after and result.get("version_id") is not None:
            result["materialized"] = materialize(conn, result["portfolio_id"])
    return result


def run_materialize(procode: str | None = None, from_date=None) -> list[dict]:
    """
    Regenerates the facts of one benchmark (by procode) or of every
    active one. Each benchmark is its own transaction, so one that
    cannot be priced does not hold the others back; its error is
    logged and re-raised at the end. Without a procode, a benchmark
    that has no version yet is skipped with a warning (it was declared
    but never defined); with one, it is an error.
    """
    with get_connection() as conn:
        if procode:
            bench = definitions.benchmark_by_procode(conn, procode)
            if bench is None or bench["portfolio_type"] != definitions.PORTFOLIO_TYPE:
                raise ValueError(f"{procode} is not a benchmark portfolio.")
            targets = [bench]
        else:
            targets = []
            for bench in definitions.benchmarks(conn):
                if definitions.versions(conn, bench["portfolio_id"]):
                    targets.append(bench)
                else:
                    logger.warning(f"{bench['procode']}: no versions yet, skipped.")
    if not targets:
        logger.warning("No benchmark portfolios to materialize.")
        return []

    summaries, failures = [], []
    for bench in targets:
        try:
            with get_connection() as conn:
                summaries.append(materialize(conn, bench["portfolio_id"], from_date))
        except Exception as exc:
            logger.error(f"{bench['procode']}: materialization failed: {exc}")
            failures.append((bench["procode"], exc))
    if failures:
        names = ", ".join(p for p, _ in failures)
        raise RuntimeError(f"{len(failures)} benchmark(s) failed: {names}") from failures[0][1]
    return summaries


def run_changelog(procode: str) -> list[dict]:
    """The changelog rows of one benchmark (vw_benchmark_changelog)."""
    with get_connection() as conn:
        bench = definitions.benchmark_by_procode(conn, procode)
        if bench is None:
            raise ValueError(f"{procode} is not a benchmark portfolio.")
        return definitions.changelog(conn, bench["portfolio_id"])
