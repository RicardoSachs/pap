# tests/db/test_onboard_series.py
# ---------------------------------------------------------------
# Registering ONE Bloomberg series from the tablero
# (src/db/onboard.py: normalize_series_spec, register_series). The
# validation needs no database; the writes run against a scratch
# PostgreSQL database and are SKIPPED without one:
#
#   set PAP_TEST_DBNAME=pap_scratch
#   python -m pytest tests/db -q
#
# Same contract as tests/analytics/benchmark/test_changelog.py: PG_*
# from .env with only the database name replaced, and every test runs
# inside ONE transaction that is rolled back at the end.
# ---------------------------------------------------------------

import datetime as dt
import os

import psycopg
import pytest
from psycopg.rows import dict_row

from src.db.bootstrap import create_schema
from src.db.onboard import SeriesConflict, normalize_series_spec, register_series

TODAY = dt.date(2026, 10, 21)
SPEC = {"procode": "spy_us", "name": " SPDR  S&P 500 ", "parsekyable": "SPY  US Equity",
        "default_start_date": "2016-01-04", "security_type": "ETF", "isin": "us78462f1030"}


# ---- validation, no database ---------------------------------------------

def test_normalize_cleans_and_uppercases():
    s = normalize_series_spec(SPEC, today=TODAY)
    assert s["procode"] == "SPY_US"
    assert s["name"] == "SPDR S&P 500"
    assert s["parsekyable"] == "SPY US Equity"
    assert s["isin"] == "US78462F1030"
    assert s["entity_type"] == "security"
    assert s["security_type"] == "ETF"
    assert s["default_start_date"] == dt.date(2016, 1, 4)


@pytest.mark.parametrize("field, value, message", [
    ("procode", "", "procode"),
    ("procode", "SPY US", "procode"),
    ("name", "   ", "name"),
    ("parsekyable", None, "parsekyable"),
    ("entity_type", "macro", "entity_type"),
    ("default_start_date", None, "default_start_date"),
    ("default_start_date", "2016/01/04", "default_start_date"),
    ("default_start_date", "2026-10-22", "future"),
    ("isin", "US784", "isin"),
])
def test_normalize_refuses_bad_fields(field, value, message):
    with pytest.raises(ValueError, match=message):
        normalize_series_spec({**SPEC, field: value}, today=TODAY)


def test_optional_fields_default_to_none():
    s = normalize_series_spec(
        {"procode": "SPX", "name": "S&P 500", "parsekyable": "SPX Index",
         "default_start_date": dt.date(2010, 1, 4), "entity_type": "index"}, today=TODAY)
    assert s["security_type"] is None
    assert s["isin"] is None
    assert s["entity_type"] == "index"


# ---- the writes, on a scratch database -----------------------------------

DBNAME = os.environ.get("PAP_TEST_DBNAME")
needs_db = pytest.mark.skipif(
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


def _one(conn, sql, *params):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchone()


@needs_db
def test_register_writes_the_rows_the_seeds_would(conn):
    r = register_series(conn, SPEC)
    assert r["created"] is True
    assert r["procode"] == "SPY_US"

    entity = _one(conn, "SELECT * FROM dim_entity WHERE entity_id = %s", r["entity_id"])
    assert (entity["procode"], entity["entity_type"], entity["name"]) == (
        "SPY_US", "security", "SPDR S&P 500")

    series = _one(conn, "SELECT * FROM series_registry WHERE series_id = %s", r["series_id"])
    assert (series["field"], series["domain"], series["source"], series["frequency"]) == (
        "PX_LAST", "prices", "bloomberg", "daily")
    assert series["status"] == "backfill-pending"
    assert series["default_start_date"] == dt.date(2016, 1, 4)

    bbg = _one(conn, "SELECT id_value, is_primary FROM dim_entity_identifiers "
                     "WHERE entity_id = %s AND id_type = 'parsekyable' AND source = 'bloomberg'",
               r["entity_id"])
    assert (bbg["id_value"], bbg["is_primary"]) == ("SPY US Equity", True)
    isin = _one(conn, "SELECT id_value, source FROM dim_entity_identifiers "
                      "WHERE entity_id = %s AND id_type = 'isin'", r["entity_id"])
    assert (isin["id_value"], isin["source"]) == ("US78462F1030", "internal")
    sec = _one(conn, "SELECT security_type FROM dim_security WHERE entity_id = %s", r["entity_id"])
    assert sec["security_type"] == "ETF"

    # The Bloomberg pipeline's own query sees it as a backfill candidate,
    # with the parsekyable it will send to the terminal.
    from src.db.queries import get_backfill_pending_series
    pending = get_backfill_pending_series(conn, domain="prices", source="bloomberg")
    assert [(p["procode"], p["parsekyable"]) for p in pending] == [("SPY_US", "SPY US Equity")]


@needs_db
def test_register_is_idempotent_and_keeps_the_status(conn):
    first = register_series(conn, SPEC)
    conn.execute("UPDATE series_registry SET status = 'active' WHERE series_id = %s",
                 (first["series_id"],))
    again = register_series(conn, {**SPEC, "name": "Another name",
                                   "default_start_date": "2000-01-03"})
    assert again["created"] is False
    assert again["series_id"] == first["series_id"]
    series = _one(conn, "SELECT status, default_start_date FROM series_registry "
                        "WHERE series_id = %s", first["series_id"])
    assert series["status"] == "active"
    assert series["default_start_date"] == dt.date(2016, 1, 4)
    n = _one(conn, "SELECT COUNT(*) AS n FROM series_registry WHERE entity_id = %s",
             first["entity_id"])
    assert n["n"] == 1


@needs_db
def test_a_ticker_cannot_belong_to_two_procodes(conn):
    register_series(conn, SPEC)
    with pytest.raises(SeriesConflict, match="SPY_US"):
        register_series(conn, {**SPEC, "procode": "SPY_COPY", "isin": None})


@needs_db
def test_an_index_gets_no_dim_security_row(conn):
    r = register_series(conn, {"procode": "SPX", "name": "S&P 500", "parsekyable": "SPX Index",
                               "default_start_date": "2010-01-04", "entity_type": "index"})
    entity = _one(conn, "SELECT entity_type FROM dim_entity WHERE entity_id = %s", r["entity_id"])
    assert entity["entity_type"] == "index"
    n = _one(conn, "SELECT COUNT(*) AS n FROM dim_security WHERE entity_id = %s", r["entity_id"])
    assert n["n"] == 0
