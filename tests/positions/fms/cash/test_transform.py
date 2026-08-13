# tests/positions/fms/cash/test_transform.py
# ---------------------------------------------------------------
# Golden-file tests for the FMS cash pure transforms. No DB, no FMS.
#
# Locks the behaviour easy to break silently:
#   - yyyymmdd -> DATE conversion
#   - Tier1 typed columns vs Tier2 raw_payload split
#   - schema-guard: raise on a missing expected column, warn on an
#     unexpected one (it still lands in raw_payload)
#   - portfolio resolution and the unresolved-fund drop
#   - institution code/name mapping; per-institution grain (no collision)
#   - balance + interest pass-through (transforms don't fabricate/drop)
# ---------------------------------------------------------------

from datetime import date

import pandas as pd
import pytest

from src.pipelines.positions.fms.cash import transform

ALL_COLUMNS = list(transform.STAGING_COLUMN_MAP.keys()) + transform.TIER_2_COLUMNS


def _raw_row(**overrides) -> dict:
    """A full vendor-native (PascalCase) FMS cash row; override any field."""
    base = {
        # Tier 1
        "IdSecuencialFechaReporte": 20260622,
        "CodigoFondo": "FONDO0",
        "IdEntidad": "ENT1",
        "Institucion": "Bank One",
        "CodigoIsoMoneda": "USD",
        "SaldoContable": 1000.0,
        "MontoTotalSoles": 3750.0,
        "TasaInteres": 0.045,
        "InteresAcumulado": 12.34,
        # Tier 2 -> raw_payload
        "MontoTotalOriginal": 1000.0,
        "CodigoInstrumento": "INSTR-1",
    }
    base.update(overrides)
    return base


def _raw_df(rows, extra_columns=None) -> pd.DataFrame:
    columns = ALL_COLUMNS + (extra_columns or [])
    return pd.DataFrame(rows, columns=columns)


def _portfolios(mapping) -> pd.DataFrame:
    return pd.DataFrame(
        {"procode": list(mapping.keys()), "portfolio_id": list(mapping.values())}
    )


# ---- transform_for_staging ------------------------------------

def test_staging_date_conversion_and_tier_split():
    stg = transform.transform_for_staging(_raw_df([_raw_row()]), "batch_test")

    assert stg.loc[0, "date"] == date(2026, 6, 22)
    assert stg.loc[0, "batch_id"] == "batch_test"
    assert stg.loc[0, "codigo_fondo"] == "FONDO0"
    assert stg.loc[0, "codigo_iso_moneda"] == "USD"
    # Tier 2 columns land in raw_payload; Tier 1 are NOT duplicated into it
    payload = stg.loc[0, "raw_payload"]
    assert set(payload.keys()) == {"MontoTotalOriginal", "CodigoInstrumento"}
    assert payload["CodigoInstrumento"] == "INSTR-1"


def test_staging_raises_on_missing_expected_column():
    raw = _raw_df([_raw_row()]).drop(columns=["SaldoContable"])
    with pytest.raises(ValueError):
        transform.transform_for_staging(raw, "b")


def test_staging_unexpected_column_lands_in_payload():
    row = _raw_row()
    row["CodigoCuenta"] = "ACC-1"
    raw = _raw_df([row], extra_columns=["CodigoCuenta"])

    stg = transform.transform_for_staging(raw, "b")
    assert stg.loc[0, "raw_payload"]["CodigoCuenta"] == "ACC-1"


def test_staging_maps_institution_code_and_name():
    stg = transform.transform_for_staging(
        _raw_df([_raw_row(IdEntidad="ENT9", Institucion="Bank Nine")]), "b"
    )
    assert stg.loc[0, "codigo_institucion"] == "ENT9"
    assert stg.loc[0, "nombre_institucion"] == "Bank Nine"


def test_staging_empty_in_empty_out():
    assert transform.transform_for_staging(pd.DataFrame(), "b").empty


# ---- transform_for_fact ---------------------------------------

def test_fact_resolves_portfolio_and_sets_source():
    stg = transform.transform_for_staging(_raw_df([_raw_row()]), "b")
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))

    assert fact.iloc[0]["portfolio_id"] == 7
    assert fact.iloc[0]["source"] == "fms"
    assert fact.iloc[0]["codigo_iso_moneda"] == "USD"


def test_fact_carries_balance_columns():
    stg = transform.transform_for_staging(
        _raw_df([_raw_row(SaldoContable=1234.5, MontoTotalSoles=4629.4)]), "b"
    )
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))
    assert fact.iloc[0]["saldo_contable"] == 1234.5
    assert fact.iloc[0]["monto_total_soles"] == 4629.4


def test_fact_two_institutions_same_currency_produce_two_rows():
    # Institution is part of the grain: two banks in the same currency on the
    # same date must stay as two distinct fact rows (the transform never
    # aggregates them; the schema PK keeps them apart on load).
    stg = transform.transform_for_staging(
        _raw_df([
            _raw_row(IdEntidad="ENT1", CodigoIsoMoneda="USD"),
            _raw_row(IdEntidad="ENT2", CodigoIsoMoneda="USD"),
        ]),
        "b",
    )
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))
    assert len(fact) == 2
    assert set(fact["codigo_institucion"]) == {"ENT1", "ENT2"}


def test_fact_carries_interest_columns():
    stg = transform.transform_for_staging(
        _raw_df([_raw_row(TasaInteres=0.05, InteresAcumulado=99.9)]), "b"
    )
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))
    assert fact.iloc[0]["tasa_interes"] == 0.05
    assert fact.iloc[0]["interes_acumulado"] == 99.9


def test_fact_drops_unresolved_fondo():
    stg = transform.transform_for_staging(
        _raw_df([
            _raw_row(CodigoFondo="FONDO0", CodigoIsoMoneda="USD"),
            _raw_row(CodigoFondo="UNKNOWN", CodigoIsoMoneda="PEN"),
        ]),
        "b",
    )
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))

    assert len(fact) == 1
    assert set(fact["portfolio_id"]) == {7}


def test_fact_empty_in_empty_out():
    assert transform.transform_for_fact(pd.DataFrame(), _portfolios({"FONDO0": 7})).empty


# ---- null pass-through (proves the transforms are innocent) ----

def test_staging_preserves_null_soles():
    stg = transform.transform_for_staging(_raw_df([_raw_row(MontoTotalSoles=None)]), "b")
    assert pd.isna(stg.loc[0, "monto_total_soles"])


def test_fact_preserves_null_saldo_contable():
    stg = transform.transform_for_staging(_raw_df([_raw_row(SaldoContable=None)]), "b")
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))
    assert pd.isna(fact.iloc[0]["saldo_contable"])
