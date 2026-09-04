# tests/positions/fms/holdings/test_transform.py
# ---------------------------------------------------------------
# Golden-file tests for the FMS holdings transforms. No DB, no FMS.
#
# Locks: staging mapping + date derivation + Tier-2 payload; the '60' split;
# securities entity resolution (fund + sbs->entity) with unresolved drop;
# deposit maturity derivation; portfolio_valuation de-dup.
# ---------------------------------------------------------------

from datetime import date

import pandas as pd
import pytest

from src.pipelines.positions.fms.holdings import transform

_ALL = list(transform.STAGING_COLUMN_MAP.keys()) + transform.TIER_2_COLUMNS


def _base() -> dict:
    return {c: None for c in _ALL}


def _security_row(**over) -> dict:
    r = _base()
    r.update({
        "IdSecuencialFechaIDI": 20260831,
        "CodigoFondo": "FONDO0",
        "IdOrdenInversion": 0,             # 0 => security
        "CodigoSBS": "EQ0001",             # not '60' => security
        "CodigoIsoMoneda": "PEN",
        "IndClase": 146,
        "ImportePEN": 5000.0,
        "ValorCuota": 15.5,
        "ValorCartera": 1000000.0,
        "Cantidad": 100.0,
        "PrecioPEN": 50.0,
        "CantidadAnterior": 90.0,
        "PrecioAnteriorPEN": 49.0,
        "ImporteAnteriorPEN": 4410.0,
        "MontoDividendos": 12.0,
        "Factor": 1.0,
    })
    r.update(over)
    return r


def _deposit_row(**over) -> dict:
    r = _base()
    r.update({
        "IdSecuencialFechaIDI": 20260831,
        "CodigoFondo": "FONDO0",
        "IdOrdenInversion": 555,           # real order => deposit
        "CodigoSBS": "601234",             # '60' => deposit
        "CodigoIsoMoneda": "USD",
        "ImportePEN": 20000.0,
        "ValorCuota": 15.5,
        "ValorCartera": 1000000.0,
        "Tasa": 0.045,
        "DiasVigencia": 90,
        "IdSecuencialFechaVencimiento": 20261129,
        "Factor": 1.0,
    })
    r.update(over)
    return r


def _raw_df(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_ALL)


def _portfolios(mapping) -> pd.DataFrame:
    return pd.DataFrame({"procode": list(mapping.keys()), "portfolio_id": list(mapping.values())})


def _securities(mapping) -> pd.DataFrame:
    return pd.DataFrame({"codigo_sbs": list(mapping.keys()),
                         "security_entity_id": list(mapping.values())})


# ---- staging ---------------------------------------------------

def test_staging_maps_and_derives_date():
    stg = transform.transform_for_staging(_raw_df([_security_row()]), "b")
    assert stg.loc[0, "date"] == date(2026, 8, 31)
    assert stg.loc[0, "codigo_fondo"] == "FONDO0"
    assert stg.loc[0, "id_orden_inversion"] == 0
    assert stg.loc[0, "ind_clase"] == 146
    assert stg.loc[0, "raw_payload"] == {"Factor": 1.0}


def test_staging_raises_on_missing_expected_column():
    raw = _raw_df([_security_row()]).drop(columns=["ImportePEN"])
    with pytest.raises(ValueError):
        transform.transform_for_staging(raw, "b")


def test_is_deposit():
    assert transform.is_deposit("601234") is True
    assert transform.is_deposit("EQ0001") is False


# ---- securities fact ------------------------------------------

def test_securities_split_and_resolves_fund_and_entity():
    stg = transform.transform_for_staging(_raw_df([_security_row(), _deposit_row()]), "b")
    fact = transform.transform_for_fact_securities(
        stg, _portfolios({"FONDO0": 7}), _securities({"EQ0001": 42}))
    assert len(fact) == 1                                   # deposit excluded
    row = fact.iloc[0]
    assert row["portfolio_id"] == 7
    assert row["security_entity_id"] == 42
    assert row["source"] == "fms"
    assert row["ind_clase"] == 146
    assert row["importe_pen"] == 5000.0
    assert list(fact.columns) == transform.SECURITIES_FACT_COLUMNS


def test_securities_drops_unresolved_entity():
    stg = transform.transform_for_staging(_raw_df([_security_row(CodigoSBS="UNKNOWN9")]), "b")
    fact = transform.transform_for_fact_securities(
        stg, _portfolios({"FONDO0": 7}), _securities({"EQ0001": 42}))
    assert fact.empty


# ---- deposits fact --------------------------------------------

def test_deposits_split_and_derives_maturity():
    stg = transform.transform_for_staging(_raw_df([_security_row(), _deposit_row()]), "b")
    fact = transform.transform_for_fact_deposits(stg, _portfolios({"FONDO0": 7}))
    assert len(fact) == 1                                   # security excluded
    row = fact.iloc[0]
    assert row["portfolio_id"] == 7
    assert row["id_orden_inversion"] == 555
    assert row["tasa"] == 0.045
    assert row["fecha_vencimiento"] == date(2026, 11, 29)
    assert list(fact.columns) == transform.DEPOSITS_FACT_COLUMNS


# ---- portfolio valuation fact ---------------------------------

def test_valuation_dedups_per_fund_date():
    # two securities + one deposit, all same fund/date -> one valuation row
    rows = [_security_row(CodigoSBS="EQ0001"),
            _security_row(CodigoSBS="EQ0002"),
            _deposit_row()]
    stg = transform.transform_for_staging(_raw_df(rows), "b")
    fact = transform.transform_for_fact_valuation(stg, _portfolios({"FONDO0": 7}))
    assert len(fact) == 1
    row = fact.iloc[0]
    assert row["portfolio_id"] == 7
    assert row["valor_cuota"] == 15.5
    assert row["valor_cartera"] == 1000000.0
    assert list(fact.columns) == transform.VALUATION_FACT_COLUMNS


def test_empty_in_empty_out():
    empty = pd.DataFrame()
    assert transform.transform_for_staging(empty, "b").empty
    assert transform.transform_for_fact_securities(empty, _portfolios({"FONDO0": 7}), _securities({"EQ0001": 42})).empty
    assert transform.transform_for_fact_deposits(empty, _portfolios({"FONDO0": 7})).empty
    assert transform.transform_for_fact_valuation(empty, _portfolios({"FONDO0": 7})).empty
