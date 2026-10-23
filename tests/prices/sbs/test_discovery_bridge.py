# tests/prices/sbs/test_discovery_bridge.py
# ---------------------------------------------------------------
# The Bloomberg bridge: SBS discovery writes a '/isin/<ISIN>' parsekyable
# alias (source bloomberg, is_primary=False) for ISIN-bearing instruments,
# and the enrichment transform records PARSEKYABLE_DES as the current
# parsekyable while keeping ID_ISIN an alias. No DB: the identifier upsert
# and entity helpers are monkeypatched to record their calls.
# ---------------------------------------------------------------

from datetime import date

import pandas as pd

from src.pipelines.prices.sbs import discovery
from src.pipelines.dim.bloomberg.security import transform


class _Conn:
    def execute(self, *a, **k):
        return None


def _patch_registry(monkeypatch, calls, resolved=None):
    monkeypatch.setattr(
        discovery, "upsert_entity_identifier",
        lambda conn, entity_id, id_type, id_value, source, is_primary=False, seen_date=None:
            calls.append((id_type, id_value, source, is_primary)),
    )
    monkeypatch.setattr(discovery, "resolve_entity_id_from_identifier",
                        lambda *a, **k: resolved)
    monkeypatch.setattr(discovery, "get_or_create_entity_id", lambda *a, **k: 42)
    monkeypatch.setattr(discovery, "_register_series", lambda *a, **k: 1)
    monkeypatch.setattr(discovery, "_resolve_by_isin_prefix", lambda *a, **k: None)


def test_normal_instrument_gets_isin_parsekyable_alias(monkeypatch):
    calls = []
    _patch_registry(monkeypatch, calls)
    row = pd.Series({"codigo_sbs": "123", "isin": "PE1000000001",
                     "tipo_instrumento": "AC", "emisor": "X", "moneda": "PEN"})
    discovery._register_normal_instrument(
        _Conn(), row, ["PX_LAST"], date(2026, 1, 2), "prices", "sbs", "daily")

    assert ("parsekyable", "/isin/PE1000000001", "bloomberg", False) in calls
    assert ("isin", "PE1000000001", "internal", False) in calls
    assert ("codigo_sbs", "123", "sbs", True) in calls


def test_uncovered_instrument_type_gets_no_bridge(monkeypatch):
    calls = []
    _patch_registry(monkeypatch, calls)
    row = pd.Series({"codigo_sbs": "0101", "isin": "PE2000000002",
                     "tipo_instrumento": "CD BCRP", "emisor": "BCRP", "moneda": "PEN"})
    discovery._register_normal_instrument(
        _Conn(), row, ["PX_LAST"], date(2026, 1, 2), "prices", "sbs", "daily")

    assert not [c for c in calls if c[0] == "parsekyable"]
    assert ("isin", "PE2000000002", "internal", False) in calls   # still registered


def test_coverage_match_ignores_case_and_spacing():
    assert not discovery.bloomberg_covered("fon.inv.trad")
    assert not discovery.bloomberg_covered("FON. INV. TRAD")
    assert not discovery.bloomberg_covered(" CDLD BCRP ")
    assert discovery.bloomberg_covered("AC")
    assert discovery.bloomberg_covered(None)


def test_x_isin_instrument_gets_no_bridge(monkeypatch):
    calls = []
    _patch_registry(monkeypatch, calls)
    row = pd.Series({"codigo_sbs": "124", "isin": "PE100000000X",
                     "tipo_instrumento": "BC", "emisor": "X", "moneda": "PEN"})
    discovery._register_x_isin_instrument(
        _Conn(), row, ["PX_LAST"], date(2026, 1, 2), "prices", "sbs", "daily")

    assert not [c for c in calls if c[0] == "parsekyable"]


def test_enrichment_promotes_parsekyable_but_not_isin():
    wide = pd.DataFrame([{
        "parsekyable": "/isin/PE1000000001", "entity_id": 42,
        "PARSEKYABLE_DES": "BAP PE Equity", "ID_ISIN": "PE1000000001",
    }])
    out = transform._map_identifiers(wide)
    flags = {r["id_type"]: (r["id_value"], r["source"], r["is_primary"])
             for _, r in out.iterrows()}
    assert flags["parsekyable"] == ("BAP PE Equity", "bloomberg", True)
    assert flags["isin"] == ("PE1000000001", "internal", False)
