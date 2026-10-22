# tests/analytics/benchmark/test_changelog.py
# ---------------------------------------------------------------
# The database half of the benchmark analytics on a two-version
# fixture: the changelog view's diff, the append-only refusals that
# need rows, materialize()'s three outputs and the "current" view.
#
# Needs a scratch PostgreSQL database and is SKIPPED without one:
#
#   set PAP_TEST_DBNAME=pap_scratch
#   python -m pytest tests/analytics/benchmark/test_changelog.py -q
#
# Host, port, user and password come from .env (the PG_* keys); only
# the database name is replaced. Every test runs the schema files and
# its fixture inside ONE transaction that is rolled back at the end,
# so the scratch database is left exactly as it was found. Never point
# PAP_TEST_DBNAME at a database you care about: the schema files are
# idempotent, but this is a test.
# ---------------------------------------------------------------

import datetime as dt
import os

import psycopg
import pytest
from psycopg.rows import dict_row

from src.db.bootstrap import create_schema
from src.pipelines.analytics.benchmark import definitions
from src.pipelines.analytics.benchmark.materialize import SOURCE_MODEL, materialize

DBNAME = os.environ.get("PAP_TEST_DBNAME")
pytestmark = pytest.mark.skipif(
    not DBNAME, reason="set PAP_TEST_DBNAME to a scratch database to run the DB tests")

D1, D2, D3, D4 = (dt.date(2026, 1, d) for d in (5, 6, 7, 8))


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


def _priced_series(conn, procode, prices):
    """A fund entity with a PX_LAST series and the given {date: price}."""
    from src.db.queries import get_or_create_entity_id
    entity_id = get_or_create_entity_id(conn, procode, "fund", name=procode)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO series_registry (entity_id, field, domain, source, frequency, status)
        VALUES (%s, 'PX_LAST', 'prices', 'test', 'daily', 'active')
        ON CONFLICT (entity_id, field, source) DO NOTHING
        """, (entity_id,))
    cur.execute(
        "SELECT series_id FROM series_registry WHERE entity_id = %s AND source = 'test'",
        (entity_id,))
    series_id = cur.fetchone()["series_id"]
    for day, px in prices.items():
        cur.execute(
            "INSERT INTO fact_prices (series_id, date, price, source) VALUES (%s, %s, %s, 'test')"
            " ON CONFLICT (series_id, date) DO UPDATE SET price = EXCLUDED.price",
            (series_id, day, px))
    return {"entity_id": entity_id, "series_id": series_id}


@pytest.fixture
def two_versions(conn):
    """
    TEST_BENCH: v1 (initial, D1) = 60% A + 40% B; v2 (constituent_change,
    D3, supersedes v1) = 50% A + 50% C. B is dropped, C added, A
    reweighted. Prices as in test_chain.py.
    """
    a = _priced_series(conn, "TEST_A", {D1: 10, D2: 12, D3: 11, D4: 11})
    b = _priced_series(conn, "TEST_B", {D1: 20, D2: 20, D3: 22, D4: 24.2})
    c = _priced_series(conn, "TEST_C", {D1: 5, D2: 5, D3: 5, D4: 5.5})
    bench = definitions.ensure_benchmark(conn, "TEST_BENCH", "Test benchmark")
    v1 = definitions.add_version(
        conn, bench["portfolio_id"], effective_from=D1, method="buy_and_hold",
        change_type="initial", reason="Launch",
        constituents=[{"label": "A", "series_id": a["series_id"], "weight": 60},
                      {"label": "B", "series_id": b["series_id"], "weight": 40}])
    v2 = definitions.add_version(
        conn, bench["portfolio_id"], effective_from=D3, method="buy_and_hold",
        change_type="constituent_change", reason="B delisted; C replaces it",
        supersedes_version_id=v1,
        constituents=[{"label": "A", "series_id": a["series_id"], "weight": 50},
                      {"label": "C", "series_id": c["series_id"], "weight": 50}])
    return {"bench": bench, "a": a, "b": b, "c": c, "v1": v1, "v2": v2}


def test_ensure_benchmark_is_idempotent_and_renames(conn):
    first = definitions.ensure_benchmark(conn, "TEST_BENCH", "Test benchmark")
    again = definitions.ensure_benchmark(conn, "TEST_BENCH", "Renamed benchmark")
    assert again["portfolio_id"] == first["portfolio_id"]
    assert again["entity_id"] == first["entity_id"]
    assert again["series_id"] == first["series_id"]
    assert again["display_name"] == "Renamed benchmark"
    assert again["portfolio_type"] == "benchmark"
    cur = conn.cursor()
    cur.execute("SELECT entity_type, name FROM dim_entity WHERE entity_id = %s",
                (first["entity_id"],))
    assert cur.fetchone() == {"entity_type": "index", "name": "Renamed benchmark"}
    cur.execute("SELECT field, domain, source, status FROM series_registry WHERE series_id = %s",
                (first["series_id"],))
    assert cur.fetchone() == {"field": "PX_LAST", "domain": "prices",
                              "source": "model", "status": "active"}


def test_changelog_diffs_each_version_against_the_one_it_supersedes(conn, two_versions):
    f = two_versions
    rows = definitions.changelog(conn, f["bench"]["portfolio_id"])
    by_version = {}
    for r in rows:
        by_version.setdefault(r["version_id"], {})[r["label"]] = r

    first = by_version[f["v1"]]
    assert {k: v["change"] for k, v in first.items()} == {"A": "added", "B": "added"}
    assert first["A"]["previous_version_id"] is None
    assert first["A"]["weight_before"] is None
    assert first["A"]["weight_after"] == pytest.approx(0.6)
    assert first["A"]["reason"] == "Launch"

    second = by_version[f["v2"]]
    assert {k: v["change"] for k, v in second.items()} == {
        "A": "reweighted", "B": "dropped", "C": "added"}
    assert second["A"]["previous_version_id"] == f["v1"]
    assert second["A"]["weight_delta"] == pytest.approx(-0.1)
    assert second["B"]["weight_after"] is None
    assert second["B"]["weight_delta"] == pytest.approx(-0.4)
    assert second["C"]["weight_before"] is None
    assert second["C"]["weight_delta"] == pytest.approx(0.5)
    assert second["C"]["reason"] == "B delisted; C replaces it"
    assert second["C"]["effective_from"] == D3


def test_append_only_refusals_that_need_rows(conn, two_versions):
    f = two_versions
    pid = f["bench"]["portfolio_id"]
    basket = [{"label": "A", "series_id": f["a"]["series_id"], "weight": 1}]
    # 'initial' is for the first version only.
    with pytest.raises(ValueError, match="initial"):
        definitions.add_version(conn, pid, effective_from=D4, method="buy_and_hold",
                                change_type="initial", reason="again", constituents=basket)
    # The benchmark cannot hold itself.
    with pytest.raises(ValueError, match="itself"):
        definitions.add_version(
            conn, pid, effective_from=D4, method="buy_and_hold", change_type="rebalance",
            reason="loop",
            constituents=[{"label": "me", "series_id": f["bench"]["series_id"], "weight": 1}])
    # Every leg must exist.
    with pytest.raises(ValueError, match="does not exist"):
        definitions.add_version(
            conn, pid, effective_from=D4, method="buy_and_hold", change_type="rebalance",
            reason="ghost", constituents=[{"label": "X", "series_id": 999_999, "weight": 1}])
    # The superseded version must be one of this benchmark's.
    other = definitions.ensure_benchmark(conn, "TEST_OTHER", "Other")
    with pytest.raises(ValueError, match="supersedes_version_id"):
        definitions.add_version(
            conn, other["portfolio_id"], effective_from=D1, method="buy_and_hold",
            change_type="initial", reason="first", constituents=basket,
            supersedes_version_id=f["v1"])
    # A first version must be 'initial'.
    with pytest.raises(ValueError, match="initial"):
        definitions.add_version(
            conn, other["portfolio_id"], effective_from=D1, method="buy_and_hold",
            change_type="rebalance", reason="first", constituents=basket)
    # Nothing above left a trace.
    assert [v["version_id"] for v in definitions.versions(conn, pid)] == [f["v1"], f["v2"]]
    assert definitions.versions(conn, other["portfolio_id"]) == []


def test_materialize_writes_levels_valuation_and_versioned_holdings(conn, two_versions):
    f = two_versions
    pid = f["bench"]["portfolio_id"]
    summary = materialize(conn, pid)
    assert (summary["dates"], summary["from"], summary["to"]) == (4, D1, D4)
    assert summary["versions"] == 2 and summary["stale_levels"] == 0

    cur = conn.cursor()
    # 1. the level series, source 'model': 100, 112, 110 (old basket on
    #    the handover), then A flat and C +10% at 50% -> 115.5
    cur.execute("SELECT date, price, source FROM fact_prices WHERE series_id = %s ORDER BY date",
                (f["bench"]["series_id"],))
    levels = cur.fetchall()
    assert [r["source"] for r in levels] == [SOURCE_MODEL] * 4
    assert [r["price"] for r in levels] == pytest.approx([100.0, 112.0, 110.0, 115.5])

    # 2. one valuation row per date, notional = level
    cur.execute("SELECT date, valor_cuota, valor_cartera FROM fact_portfolio_valuation "
                "WHERE portfolio_id = %s AND source = %s ORDER BY date", (pid, SOURCE_MODEL))
    val = cur.fetchall()
    assert [float(r["valor_cartera"]) for r in val] == pytest.approx([100.0, 112.0, 110.0, 115.5])
    assert [float(r["valor_cuota"]) for r in val] == pytest.approx([100.0, 112.0, 110.0, 115.5])

    # 3. holdings tagged with the version that produced them; the
    #    handover date carries the NEW basket (A and C, version 2)
    cur.execute("SELECT date, entity_id, version_id, units, weight, market_value_pen "
                "FROM fact_positions_model WHERE portfolio_id = %s ORDER BY date, entity_id", (pid,))
    holdings = cur.fetchall()
    by_date = {}
    for r in holdings:
        by_date.setdefault(r["date"], []).append(r)
    assert {r["version_id"] for r in by_date[D1] + by_date[D2]} == {f["v1"]}
    assert {r["version_id"] for r in by_date[D3] + by_date[D4]} == {f["v2"]}
    assert {r["entity_id"] for r in by_date[D3]} == {f["a"]["entity_id"], f["c"]["entity_id"]}
    for day, level in zip((D1, D2, D3, D4), (100.0, 112.0, 110.0, 115.5)):
        assert sum(float(r["market_value_pen"]) for r in by_date[day]) == pytest.approx(level)
        assert sum(float(r["weight"]) for r in by_date[day]) == pytest.approx(1.0)

    # Re-running changes nothing and reports it.
    again = materialize(conn, pid)
    assert again["levels_written"] == 0 and again["levels_unchanged"] == 4
    assert again["holdings_written"] == 0 and again["valuation_written"] == 0


def test_a_correction_keeps_the_old_rows_and_the_current_view_picks_the_new(conn, two_versions):
    f = two_versions
    pid = f["bench"]["portfolio_id"]
    materialize(conn, pid)

    # v3 corrects v2 from the SAME effective date: 70/30 instead of 50/50.
    v3 = definitions.add_version(
        conn, pid, effective_from=D3, method="buy_and_hold", change_type="correction",
        reason="Weights were keyed in swapped", supersedes_version_id=f["v2"],
        constituents=[{"label": "A", "series_id": f["a"]["series_id"], "weight": 70},
                      {"label": "C", "series_id": f["c"]["series_id"], "weight": 30}])
    governing = definitions.governing_versions(conn, pid)
    assert [v["version_id"] for v in governing] == [f["v1"], v3]

    summary = materialize(conn, pid)
    assert summary["versions"] == 2
    cur = conn.cursor()
    # D4 level: on 110, A flat (70%) and C +10% (30%) -> 113.3
    cur.execute("SELECT price FROM fact_prices WHERE series_id = %s AND date = %s",
                (f["bench"]["series_id"], D4))
    assert cur.fetchone()["price"] == pytest.approx(113.3)

    # The v2 rows are still there; the current view shows v3 only.
    cur.execute("SELECT DISTINCT version_id FROM fact_positions_model "
                "WHERE portfolio_id = %s AND date >= %s ORDER BY 1", (pid, D3))
    assert [r["version_id"] for r in cur.fetchall()] == [f["v2"], v3]
    cur.execute("SELECT date, version_id, weight FROM vw_positions_model_current "
                "WHERE portfolio_id = %s AND date = %s ORDER BY weight DESC", (pid, D3))
    current = cur.fetchall()
    assert [r["version_id"] for r in current] == [v3, v3]
    assert [float(r["weight"]) for r in current] == pytest.approx([0.7, 0.3])

    # The changelog shows the correction against v2 as a reweighting.
    rows = {r["label"]: r for r in definitions.changelog(conn, pid) if r["version_id"] == v3}
    assert rows["A"]["change"] == "reweighted" and rows["A"]["previous_version_id"] == f["v2"]
    assert rows["A"]["weight_delta"] == pytest.approx(0.2)
    assert rows["C"]["weight_delta"] == pytest.approx(-0.2)


def test_partial_rebuild_from_a_date_matches_the_full_one(conn, two_versions):
    f = two_versions
    pid = f["bench"]["portfolio_id"]
    full = materialize(conn, pid)
    partial = materialize(conn, pid, from_date=D3)
    assert partial["from"] == D3 and partial["to"] == D4
    assert partial["levels_written"] == 0 and partial["levels_unchanged"] == 2
    assert partial["level"] == full["level"]
    with pytest.raises(ValueError, match="No version governs"):
        materialize(conn, pid, from_date=dt.date(2025, 12, 31))


def test_heuristic_is_refused_before_writing(conn, two_versions):
    f = two_versions
    pid = f["bench"]["portfolio_id"]
    definitions.add_version(
        conn, pid, effective_from=D4, method="heuristic", change_type="methodology",
        reason="Named rule, no module yet",
        constituents=[{"label": "A", "series_id": f["a"]["series_id"], "weight": 1}])
    with pytest.raises(ValueError, match="heuristic"):
        materialize(conn, pid)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM fact_prices WHERE series_id = %s",
                (f["bench"]["series_id"],))
    assert cur.fetchone()["n"] == 0
