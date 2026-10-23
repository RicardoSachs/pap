# tests/web/test_windows_benchmarks.py
# ---------------------------------------------------------------
# The benchmark rows of the SPP return tables: an index assigned to a
# house fund appears in that fund's block with its own returns and the
# house's excess over it, its levels forward-filled onto the SPP grid.
# The return arithmetic is tested without a database; the rows need a
# scratch PostgreSQL database (PAP_TEST_DBNAME) and are SKIPPED without
# one - same contract as tests/analytics/benchmark/test_changelog.py.
# ---------------------------------------------------------------

import datetime as dt
import os

import psycopg
import pytest
from psycopg.rows import dict_row

from src.db.bootstrap import create_schema
from src.db.queries import get_or_create_entity_id
from src.pipelines.analytics.benchmark import definitions
from src.pipelines.prices.sbs.valor_cuota import afps
from web.api.services.spp import LEVEL_KEYS, _benchmark_rows, _window_returns

D1, D2, D3, D4, D5 = (dt.date(2026, 1, d) for d in (5, 6, 7, 8, 9))


def test_window_returns_from_the_levels_at_the_reference_dates():
    v = {"t": 110.0, "t1": 100.0, "t2": 90.0, "month": 100.0, "month1": 80.0,
         "m3": 100.0, "a3": 100.0, "year": 100.0, "year1": 50.0}
    r = _window_returns(v)
    assert r["level"] == 110.0
    assert r["d0"] == pytest.approx(0.10)
    assert r["d1"] == pytest.approx(100 / 90 - 1)
    assert r["mtd"] == pytest.approx(0.10)
    assert r["m1"] == pytest.approx(0.25)
    assert r["a1"] == pytest.approx(1.0)
    assert r["a3"] == pytest.approx(1.1 ** (1 / 3) - 1)
    # Windows without a base are None, never zero.
    assert r["d2"] is None and r["m6"] is None and r["a10"] is None


# ---- database half -------------------------------------------------------

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


def _levels(conn, series_id, prices):
    cur = conn.cursor()
    for day, px in prices.items():
        cur.execute("INSERT INTO fact_prices (series_id, date, price, source) "
                    "VALUES (%s, %s, %s, 'model')", (series_id, day, px))


REF = {"t": D4, "t1": D3, "t2": D2, "t3": D1, "t4": None, "t5": None,
       "month": D1, "month1": None, "month2": None, "year": None, "year1": None,
       "fy": None, "m3": None, "m6": None, "m12": None, "a3": None, "a5": None, "a10": None}
HOUSE = {"d0": 0.01, "d1": 0.0, "d2": None, "mtd": 0.03}


@needs_db
def test_an_assigned_benchmark_becomes_a_row_of_its_fund(conn):
    bench = definitions.ensure_benchmark(conn, "TEST_BENCH_F2", "Bench F2")
    _levels(conn, bench["series_id"], {D1: 100.0, D2: 101.0, D3: 102.0, D4: 104.0})
    fund = get_or_create_entity_id(conn, afps.procode(afps.house_afp(), 2), "fund",
                                   name="House fund 2")
    definitions.assign(conn, bench["portfolio_id"], fund)

    levels, absolute, relative = _benchmark_rows(conn, REF, {2: HOUSE})
    assert [(r["afp"], r["fund"], r["benchmark"], r["procode"]) for r in absolute] == [
        ("Bench F2", 2, True, "TEST_BENCH_F2")]
    r = absolute[0]["values"]
    assert r["level"] == 104.0
    assert r["d0"] == pytest.approx(104 / 102 - 1)
    assert r["mtd"] == pytest.approx(0.04)
    assert r["m3"] is None
    assert levels[0]["values"]["t"] == 104.0 and set(levels[0]["values"]) == set(LEVEL_KEYS)
    # The relative row is the HOUSE's excess over the index, None where
    # either side is missing.
    x = relative[0]["values"]
    assert relative[0]["absolute"] is False
    assert x["d0"] == pytest.approx(0.01 - (104 / 102 - 1))
    assert x["mtd"] == pytest.approx(0.03 - 0.04)
    assert x["d2"] is None
    assert "level" not in x


@needs_db
def test_levels_are_carried_forward_onto_the_spp_grid(conn):
    bench = definitions.ensure_benchmark(conn, "TEST_BENCH_F1", "Bench F1")
    _levels(conn, bench["series_id"], {D1: 100.0, D3: 103.0})          # no print on D2, D4
    fund = get_or_create_entity_id(conn, afps.procode(afps.house_afp(), 1), "fund",
                                   name="House fund 1")
    definitions.assign(conn, bench["portfolio_id"], fund)

    _, absolute, _ = _benchmark_rows(conn, REF, {})
    v = absolute[0]["values"]
    assert v["level"] == 103.0                       # D4 reads D3's level
    assert v["d0"] == pytest.approx(0.0)             # D4 vs D3: the same print
    assert v["d1"] == pytest.approx(0.03)            # D3 vs D2 (= D1's level)
    assert absolute[0]["fund"] == 1


@needs_db
def test_unassigned_or_unmaterialized_benchmarks_add_no_rows(conn):
    loose = definitions.ensure_benchmark(conn, "TEST_LOOSE", "No fund")
    _levels(conn, loose["series_id"], {D1: 100.0, D4: 101.0})
    empty = definitions.ensure_benchmark(conn, "TEST_EMPTY_F3", "No levels yet")
    fund = get_or_create_entity_id(conn, afps.procode(afps.house_afp(), 3), "fund",
                                   name="House fund 3")
    definitions.assign(conn, empty["portfolio_id"], fund)

    levels, absolute, relative = _benchmark_rows(conn, REF, {3: HOUSE})
    assert [r["procode"] for r in absolute] == ["TEST_EMPTY_F3"]
    assert absolute[0]["values"]["level"] is None     # assigned, nothing printed yet: a dash
    assert all(v is None for v in relative[0]["values"].values())
    assert levels[0]["values"]["t"] is None
