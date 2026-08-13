# tests/positions/fms/cash/test_loader.py
# ---------------------------------------------------------------
# Guard tests for the pre-INSERT NOT NULL check. No DB — _validate_not_null
# is a pure DataFrame check. It turns a source-origin null (e.g. a row missing
# SaldoContable / MontoTotalSoles) into a clear, actionable error at the fact
# boundary instead of an opaque psycopg NotNullViolation.
# ---------------------------------------------------------------

from datetime import date

import pandas as pd
import pytest

from src.pipelines.positions.fms.cash import loader


def _fact_row(**overrides) -> dict:
    base = {
        "portfolio_id": 7,
        "codigo_institucion": "ENT1",
        "codigo_iso_moneda": "USD",
        "date": date(2026, 6, 22),
        "source": "fms",
        "nombre_institucion": "Bank One",
        "saldo_contable": 1000.0,
        "monto_total_soles": 3750.0,
        "tasa_interes": 0.045,
        "interes_acumulado": 12.34,
    }
    base.update(overrides)
    return base


def test_validate_not_null_raises_on_null_soles():
    df = pd.DataFrame([_fact_row(monto_total_soles=None)])
    with pytest.raises(ValueError, match="monto_total_soles"):
        loader._validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS)


def test_validate_not_null_raises_on_null_saldo_contable():
    df = pd.DataFrame([_fact_row(saldo_contable=None)])
    with pytest.raises(ValueError, match="saldo_contable"):
        loader._validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS)


def test_validate_not_null_raises_on_null_institucion():
    df = pd.DataFrame([_fact_row(codigo_institucion=None)])
    with pytest.raises(ValueError, match="codigo_institucion"):
        loader._validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS)


def test_validate_not_null_passes_when_complete():
    df = pd.DataFrame([_fact_row()])
    loader._validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS)  # must not raise


def test_validate_not_null_ignores_nullable_name_and_interest():
    # nombre_institucion / tasa_interes / interes_acumulado are nullable
    df = pd.DataFrame([_fact_row(nombre_institucion=None, tasa_interes=None,
                                 interes_acumulado=None)])
    loader._validate_not_null(df, loader.FACT_NOT_NULL_COLUMNS)  # must not raise


def test_conflict_keys_include_institucion():
    # The collision fix lives in the upsert conflict target: institution code
    # must be part of both keys, or two banks in one currency overwrite each other.
    assert ("ON CONFLICT (portfolio_id, codigo_institucion, codigo_iso_moneda, "
            "date, source)") in loader.FACT_UPSERT
    assert ("ON CONFLICT (codigo_fondo, codigo_institucion, codigo_iso_moneda, "
            "date)") in loader.STG_UPSERT
