# tests/web/test_series_catalog.py
# ---------------------------------------------------------------
# The series catalog and the per-source summary the Benchmarks module
# reads (web/api/services/benchmarks.py): what a basket may draw from,
# how a series is found and how its coverage is reported. Needs a
# scratch PostgreSQL database (PAP_TEST_DBNAME) and is SKIPPED without
# one - same contract as tests/analytics/benchmark/test_changelog.py.
# ---------------------------------------------------------------

import datetime as dt
import os

import psycopg
import pytest
from psycopg.rows import dict_row

from src.db.bootstrap import create_schema
from src.db.onboard import register_series
from src.pipelines.analytics.benchmark import definitions
from web.api.services.benchmarks import _catalog_rows, _sources_rows

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


def _prices(conn, series_id, prices):
    cur = conn.cursor()
    for day, px in prices.items():
        cur.execute("INSERT INTO fact_prices (series_id, date, price, source) "
                    "VALUES (%s, %s, %s, 'test')", (series_id, day, px))


@pytest.fixture
def universe(conn):
    """Two Bloomberg series - one pending with no prices, one active with
    three - and a benchmark, whose own level series must never be offered."""
    spy = register_series(conn, {"procode": "SPY_US", "name": "SPDR S&P 500",
                                 "parsekyable": "SPY US Equity",
                                 "default_start_date": "2016-01-04", "isin": "US78462F1030"})
    spx = register_series(conn, {"procode": "SPX", "name": "S&P 500", "parsekyable": "SPX Index",
                                 "default_start_date": "2010-01-04", "entity_type": "index"})
    _prices(conn, spx["series_id"], {dt.date(2026, 1, 5): 5000.0, dt.date(2026, 1, 6): 5050.0,
                                     dt.date(2026, 1, 7): 5100.0})
    conn.execute("UPDATE series_registry SET status = 'active' WHERE series_id = %s",
                 (spx["series_id"],))
    definitions.ensure_benchmark(conn, "TEST_BENCH", "Test benchmark")
    return {"spy": spy, "spx": spx}


def test_catalog_finds_by_ticker_isin_name_and_procode(universe, conn):
    for q in ("SPY US", "us78462f", "spdr", "spy_us"):
        assert [r["procode"] for r in _catalog_rows(conn, q)] == ["SPY_US"], q
    assert [r["procode"] for r in _catalog_rows(conn, "500")] == ["SPX", "SPY_US"]
    assert _catalog_rows(conn, "nothing like this") == []


def test_catalog_reports_coverage_status_and_identifiers(universe, conn):
    rows = {r["procode"]: r for r in _catalog_rows(conn)}
    assert "TEST_BENCH" not in rows
    spy, spx = rows["SPY_US"], rows["SPX"]
    assert (spy["points"], spy["from"], spy["to"], spy["status"]) == (
        0, None, None, "backfill-pending")
    assert (spx["points"], spx["from"], spx["to"], spx["status"]) == (
        3, "2026-01-05", "2026-01-07", "active")
    assert spy["ticker"] == "SPY US Equity"
    assert spy["isin"] == "US78462F1030"
    assert spy["default_start_date"] == "2016-01-04"
    assert spx["detail"] == "PX_LAST · bloomberg · SPX Index"
    assert spx["label"] == "SPX"


def test_catalog_filters_by_source_and_series_id(universe, conn):
    assert [r["procode"] for r in _catalog_rows(conn, source="bloomberg")] == ["SPX", "SPY_US"]
    assert _catalog_rows(conn, source="sbs") == []
    only = _catalog_rows(conn, series_id=universe["spy"]["series_id"])
    assert [r["series_id"] for r in only] == [universe["spy"]["series_id"]]
    assert [r["procode"] for r in _catalog_rows(conn, limit=1)] == ["SPX"]


def test_sources_summary(universe, conn):
    rows = {r["source"]: r for r in _sources_rows(conn)}
    assert set(rows) == {"bloomberg"}
    b = rows["bloomberg"]
    assert (b["series"], b["active"], b["pending"], b["priced"], b["points"]) == (2, 1, 1, 1, 3)
    assert (b["from"], b["to"]) == ("2026-01-05", "2026-01-07")
