# tests/positions/fms/forwards/test_loader.py
# ---------------------------------------------------------------
# Guard tests for the pre-INSERT NOT NULL check. No DB — _validate_not_null is
# a pure DataFrame check. It turns a source-origin null (e.g. a stale FMS
# TipoCambioSpot with no MonedaCambio fallback) into a clear, actionable error
# at the fact boundary instead of an opaque psycopg NotNullViolation.
# ---------------------------------------------------------------

from datetime import date

import pandas as pd
import pytest

from src.pipelines.positions.fms import _common
from src.pipelines.positions.fms.forwards import loader


def _fact_row(**overrides) -> dict:
    base = {
        "portfolio_id": 7,
        "codigo_sbs": "SBS123",
        "date": date(2026, 6, 22),
        "source": "fms",
        "codigo_iso_moneda_nocional": "USD",
        "valor_nocional": 1000.0,
        "tipo_cambio_spot": 3.75,
        "nocional_soles": 3750.0,
        "moneda_compra": "USD",
        "moneda_venta": "PEN",
        "fecha_vencimiento": None,   # nullable — not checked
        "precio_forward": None,
        "valor_strike": None,
        "mtm_soles": None,
    }
    base.update(overrides)
    return base


def test_validate_not_null_raises_and_names_column_and_sbs():
    df = pd.DataFrame([_fact_row(tipo_cambio_spot=None)])
    with pytest.raises(ValueError, match="tipo_cambio_spot"):
        _common.validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS,
                                  table="fact_positions_forwards", id_col="codigo_sbs")


def test_validate_not_null_passes_when_complete():
    df = pd.DataFrame([_fact_row()])
    _common.validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS,
                              table="fact_positions_forwards", id_col="codigo_sbs")  # must not raise


def test_validate_not_null_ignores_nullable_columns():
    # mtm_soles / fecha_vencimiento are legitimately nullable and not in the list
    df = pd.DataFrame([_fact_row(mtm_soles=None, fecha_vencimiento=None)])
    _common.validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS,
                              table="fact_positions_forwards", id_col="codigo_sbs")  # must not raise
