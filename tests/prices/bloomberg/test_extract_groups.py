# tests/prices/bloomberg/test_extract_groups.py
# ---------------------------------------------------------------
# The BDH request grouping: one call per (start_date, field), each series
# requested by its OWN field. Guards the regression where every series was
# requested as PX_LAST regardless of what it was registered for.
# ---------------------------------------------------------------

import sys
from datetime import date
from unittest.mock import MagicMock

# src/vendors/bloomberg.py imports blpapi at module level (and evaluates
# blpapi.Session() in a default argument); only the workstation has it.
# A MagicMock module lets the pure grouping helper be tested anywhere.
sys.modules.setdefault("blpapi", MagicMock())

from src.pipelines.prices.bloomberg.extract import _request_groups  # noqa: E402


def test_groups_by_start_date_and_own_field():
    secs = [
        {"parsekyable": "A PE Equity", "field": "PX_LAST", "start_date": date(2026, 1, 2)},
        {"parsekyable": "B PE Equity", "field": "PX_LAST", "start_date": date(2026, 1, 2)},
        {"parsekyable": "A PE Equity", "field": "PX_VOLUME", "start_date": date(2026, 1, 2)},
        {"parsekyable": "C US Equity", "field": "PX_LAST", "start_date": "2025-06-01"},
    ]
    groups = _request_groups(secs)

    assert set(groups) == {
        ("2026-01-02", "PX_LAST"), ("2026-01-02", "PX_VOLUME"), ("2025-06-01", "PX_LAST"),
    }
    assert [s["parsekyable"] for s in groups[("2026-01-02", "PX_LAST")]] == ["A PE Equity", "B PE Equity"]
    assert [s["parsekyable"] for s in groups[("2026-01-02", "PX_VOLUME")]] == ["A PE Equity"]


def test_missing_field_defaults_to_px_last():
    groups = _request_groups([{"parsekyable": "A PE Equity", "start_date": date(2026, 1, 2)}])
    assert list(groups) == [("2026-01-02", "PX_LAST")]
