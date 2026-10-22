# tests/analytics/benchmark/test_definitions.py
# ---------------------------------------------------------------
# The definition writer's refusal paths that need no database, the
# weight normalization, and the append-only guarantee itself: the
# module must contain no UPDATE or DELETE against the two definition
# tables. The refusals that need rows (self-reference, 'initial'
# twice, a foreign superseded version) are in test_changelog.py,
# which runs against a scratch database.
# ---------------------------------------------------------------

import datetime as dt
import inspect
import re

import pytest

from src.pipelines.analytics.benchmark import definitions
from src.pipelines.analytics.benchmark.definitions import validate_version

TODAY = dt.date(2026, 10, 13)
BASKET = [{"label": "A", "series_id": 1, "weight": 60},
          {"label": "B", "series_id": 2, "weight": 40}]


def _ok(**overrides):
    kw = dict(effective_from=dt.date(2026, 1, 5), method="buy_and_hold",
              change_type="initial", reason="Launch", constituents=BASKET, today=TODAY)
    kw.update(overrides)
    return validate_version(**kw)


def test_weights_are_normalized_from_100_or_1():
    v = _ok()
    assert [c["weight"] for c in v["constituents"]] == pytest.approx([0.6, 0.4])
    v = _ok(constituents=[{"label": "A", "series_id": 1, "weight": 0.25},
                          {"label": "B", "series_id": 2, "weight": 0.75}])
    assert [c["weight"] for c in v["constituents"]] == pytest.approx([0.25, 0.75])
    assert v["reason"] == "Launch"
    assert v["rebalance_frequency"] is None


@pytest.mark.parametrize("reason", ["", "   ", None, "\n\t"])
def test_blank_reason_is_refused(reason):
    with pytest.raises(ValueError, match="reason"):
        _ok(reason=reason)


def test_unknown_method_and_change_type_are_refused():
    with pytest.raises(ValueError, match="method"):
        _ok(method="equal_weight")
    with pytest.raises(ValueError, match="change_type"):
        _ok(change_type="tweak")


def test_rebalance_frequency_goes_with_fixed_weights_only():
    with pytest.raises(ValueError, match="rebalance_frequency"):
        _ok(method="fixed_weights")
    with pytest.raises(ValueError, match="rebalance_frequency"):
        _ok(method="fixed_weights", rebalance_frequency="weekly")
    with pytest.raises(ValueError, match="rebalance_frequency"):
        _ok(method="buy_and_hold", rebalance_frequency="monthly")
    v = _ok(method="fixed_weights", rebalance_frequency="quarterly")
    assert v["rebalance_frequency"] == "quarterly"


def test_effective_from_accepts_iso_text_but_not_the_future():
    assert _ok(effective_from="2026-01-05")["effective_from"] == dt.date(2026, 1, 5)
    with pytest.raises(ValueError, match="future"):
        _ok(effective_from=dt.date(2026, 10, 14))
    with pytest.raises(ValueError, match="date"):
        _ok(effective_from=20260105)


def test_basket_problems_are_named():
    with pytest.raises(ValueError, match="empty"):
        _ok(constituents=[])
    with pytest.raises(ValueError, match="label"):
        _ok(constituents=[{"label": " ", "series_id": 1, "weight": 1}])
    with pytest.raises(ValueError, match="series_id"):
        _ok(constituents=[{"label": "A", "weight": 1}])
    with pytest.raises(ValueError, match="'B'"):
        _ok(constituents=[{"label": "A", "series_id": 1, "weight": 1},
                          {"label": "B", "series_id": 2, "weight": 0}])
    with pytest.raises(ValueError, match="repeats"):
        _ok(constituents=[{"label": "A", "series_id": 1, "weight": 50},
                          {"label": "A2", "series_id": 1, "weight": 50}])
    with pytest.raises(ValueError, match="sum to"):
        _ok(constituents=[{"label": "A", "series_id": 1, "weight": 60},
                          {"label": "B", "series_id": 2, "weight": 30}])


def test_the_writer_never_updates_or_deletes_a_version():
    """
    Append-only is a property of the code, not of the data: the only
    statements the module issues against the definition tables are
    INSERTs. A future UPDATE or DELETE there has to delete this test
    first, and explain why in the PR.
    """
    source = inspect.getsource(definitions)
    for table in ("dim_benchmark_version", "benchmark_constituent"):
        assert not re.search(rf"(UPDATE|DELETE\s+FROM)\s+{table}\b", source), (
            f"definitions.py must not UPDATE or DELETE {table}")
    assert re.search(r"INSERT\s+INTO\s+dim_benchmark_version\b", source)
    assert re.search(r"INSERT\s+INTO\s+benchmark_constituent\b", source)
