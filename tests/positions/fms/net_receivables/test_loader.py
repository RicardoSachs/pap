# tests/positions/fms/net_receivables/test_loader.py
# ---------------------------------------------------------------
# Guard tests for the pre-INSERT NOT NULL check (via _common) and the
# collision-key conflict targets. No DB — pure DataFrame checks.
# ---------------------------------------------------------------

from datetime import date

import pandas as pd
import pytest

from src.pipelines.positions.fms import _common
from src.pipelines.positions.fms.net_receivables import loader


def _fact_row(**overrides) -> dict:
    base = {
        "portfolio_id": 7,
        "codigo_iso_moneda": "USD",
        "date": date(2026, 8, 27),
        "source": "fms",
        "monto_cobrar": 1000.0,
        "monto_pagar": 250.0,
    }
    base.update(overrides)
    return base


def test_validate_not_null_raises_on_null_cobrar():
    df = pd.DataFrame([_fact_row(monto_cobrar=None)])
    with pytest.raises(ValueError, match="monto_cobrar"):
        _common.validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS,
                                  table="fact_positions_net_receivables", id_col="codigo_iso_moneda")


def test_validate_not_null_raises_on_null_pagar():
    df = pd.DataFrame([_fact_row(monto_pagar=None)])
    with pytest.raises(ValueError, match="monto_pagar"):
        _common.validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS,
                                  table="fact_positions_net_receivables", id_col="codigo_iso_moneda")


def test_validate_not_null_passes_when_complete():
    df = pd.DataFrame([_fact_row()])
    _common.validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS,
                              table="fact_positions_net_receivables", id_col="codigo_iso_moneda")


def test_conflict_keys():
    assert ("ON CONFLICT (portfolio_id, codigo_iso_moneda, date, source)") in loader.FACT_UPSERT
    assert ("ON CONFLICT (codigo_fondo, codigo_iso_moneda, date)") in loader.STG_UPSERT
