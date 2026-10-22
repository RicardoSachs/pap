# tests/analytics/benchmark/test_assignment.py
# ---------------------------------------------------------------
# The assignment of a benchmark to the entity it measures
# (benchmark_assignment, definitions.assign / assignments): one link
# per benchmark, replaced on reassignment, read back by every benchmark
# query. Needs a scratch PostgreSQL database (PAP_TEST_DBNAME) and is
# SKIPPED without one - same contract as test_changelog.py.
# ---------------------------------------------------------------

import os

import psycopg
import pytest
from psycopg.rows import dict_row

from src.db.bootstrap import create_schema
from src.db.queries import get_or_create_entity_id
from src.pipelines.analytics.benchmark import definitions

DBNAME = os.environ.get("PAP_TEST_DBNAME")
pytestmark = pytest.mark.skipif(
    not DBNAME, reason="set PAP_TEST_DBNAME to a scratch database to run the DB tests")


@pytest.fixture
def conn():
    from src.shared.config_pg import get_db_config
    cfg = {**get_db_config(), "dbname": DBNAME}
    connection = psycopg.connect(
        host=cfg["host"], port=cfg["port"], dbname=cfg["dbname"],
        user=cfg["user"], password=cfg["password"], row_factory=dict_row)
    try:
        create_schema(connection)
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_assign_links_a_benchmark_to_a_fund_entity_once(conn):
    bench = definitions.ensure_benchmark(conn, "TEST_BENCH", "Test benchmark")
    f2 = get_or_create_entity_id(conn, "SPP_TEST_F2", "fund", name="Test Fondo 2")
    f3 = get_or_create_entity_id(conn, "SPP_TEST_F3", "fund", name="Test Fondo 3")

    definitions.assign(conn, bench["portfolio_id"], f2)
    row = definitions.benchmark_by_procode(conn, "TEST_BENCH")
    assert (row["assigned_entity_id"], row["assigned_procode"]) == (f2, "SPP_TEST_F2")

    # Reassigning replaces the link; it never adds a second one.
    definitions.assign(conn, bench["portfolio_id"], f3)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM benchmark_assignment WHERE portfolio_id = %s",
                (bench["portfolio_id"],))
    assert cur.fetchone()["n"] == 1
    assert [a["assigned_procode"] for a in definitions.assignments(conn)] == ["SPP_TEST_F3"]
    assert definitions.assignments(conn)[0]["series_id"] == bench["series_id"]


def test_unassigned_benchmarks_are_listed_without_a_link_and_skipped_by_assignments(conn):
    a = definitions.ensure_benchmark(conn, "TEST_A", "A")
    definitions.ensure_benchmark(conn, "TEST_B", "B")
    fund = get_or_create_entity_id(conn, "SPP_TEST_F1", "fund", name="Test Fondo 1")
    definitions.assign(conn, a["portfolio_id"], fund)

    by_code = {b["procode"]: b for b in definitions.benchmarks(conn)}
    assert by_code["TEST_A"]["assigned_procode"] == "SPP_TEST_F1"
    assert by_code["TEST_B"]["assigned_procode"] is None
    assert [x["procode"] for x in definitions.assignments(conn)] == ["TEST_A"]


def test_assign_refuses_an_unknown_entity(conn):
    bench = definitions.ensure_benchmark(conn, "TEST_BENCH", "Test benchmark")
    with pytest.raises(ValueError, match="does not exist"):
        definitions.assign(conn, bench["portfolio_id"], 999_999)
