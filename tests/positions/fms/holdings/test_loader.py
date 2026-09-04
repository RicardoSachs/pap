# tests/positions/fms/holdings/test_loader.py
# ---------------------------------------------------------------
# Guard tests for the three holdings fact writers: the pre-INSERT NOT NULL
# check (via _common) and the conflict-key targets in each UPSERT. No DB.
# ---------------------------------------------------------------

from datetime import date

import pandas as pd
import pytest

from src.pipelines.positions.fms import _common
from src.pipelines.positions.fms.holdings import loader


def _sec_row(**over) -> dict:
    base = {c: None for c in loader.SECURITIES_FACT_COLUMNS}
    base.update({"portfolio_id": 7, "security_entity_id": 42, "date": date(2026, 8, 31),
                 "source": "fms", "importe_pen": 5000.0})
    base.update(over)
    return base


def _dep_row(**over) -> dict:
    base = {c: None for c in loader.DEPOSITS_FACT_COLUMNS}
    base.update({"portfolio_id": 7, "id_orden_inversion": 555, "date": date(2026, 8, 31),
                 "source": "fms", "codigo_iso_moneda": "USD", "importe_pen": 20000.0})
    base.update(over)
    return base


def _val_row(**over) -> dict:
    base = {c: None for c in loader.VALUATION_FACT_COLUMNS}
    base.update({"portfolio_id": 7, "date": date(2026, 8, 31), "source": "fms",
                 "valor_cuota": 15.5, "valor_cartera": 1000000.0})
    base.update(over)
    return base


# ---- NOT NULL guards ------------------------------------------

def test_securities_not_null_guard():
    _common.validate_not_null(pd.DataFrame([_sec_row()]), loader.SECURITIES_NOT_NULL,
                              table="fact_positions_securities", id_col="security_entity_id")
    with pytest.raises(ValueError, match="importe_pen"):
        _common.validate_not_null(pd.DataFrame([_sec_row(importe_pen=None)]), loader.SECURITIES_NOT_NULL,
                                  table="fact_positions_securities", id_col="security_entity_id")


def test_deposits_not_null_guard():
    _common.validate_not_null(pd.DataFrame([_dep_row()]), loader.DEPOSITS_NOT_NULL,
                              table="fact_positions_deposits", id_col="id_orden_inversion")
    with pytest.raises(ValueError, match="codigo_iso_moneda"):
        _common.validate_not_null(pd.DataFrame([_dep_row(codigo_iso_moneda=None)]), loader.DEPOSITS_NOT_NULL,
                                  table="fact_positions_deposits", id_col="id_orden_inversion")


def test_valuation_not_null_guard():
    _common.validate_not_null(pd.DataFrame([_val_row()]), loader.VALUATION_NOT_NULL,
                              table="fact_portfolio_valuation", id_col="portfolio_id")
    with pytest.raises(ValueError, match="valor_cartera"):
        _common.validate_not_null(pd.DataFrame([_val_row(valor_cartera=None)]), loader.VALUATION_NOT_NULL,
                                  table="fact_portfolio_valuation", id_col="portfolio_id")


# ---- conflict keys --------------------------------------------

def test_conflict_keys():
    assert "ON CONFLICT (codigo_fondo, codigo_sbs, id_orden_inversion, date)" in loader.STG_UPSERT
    assert "ON CONFLICT (portfolio_id, security_entity_id, date, source)" in loader.SECURITIES_UPSERT
    assert "ON CONFLICT (portfolio_id, id_orden_inversion, date, source)" in loader.DEPOSITS_UPSERT
    assert "ON CONFLICT (portfolio_id, date, source)" in loader.VALUATION_UPSERT


def test_upserts_target_right_tables():
    assert "INSERT INTO stg_positions_fms_holdings" in loader.STG_UPSERT
    assert "INSERT INTO fact_positions_securities" in loader.SECURITIES_UPSERT
    assert "INSERT INTO fact_positions_deposits" in loader.DEPOSITS_UPSERT
    assert "INSERT INTO fact_portfolio_valuation" in loader.VALUATION_UPSERT
