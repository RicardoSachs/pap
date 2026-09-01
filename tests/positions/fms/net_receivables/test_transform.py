# tests/positions/fms/net_receivables/test_transform.py
# ---------------------------------------------------------------
# Golden-file tests for the FMS net-receivables pure transforms. No DB, no FMS.
#
# Locks the behaviour easy to break silently:
#   - Tier1 typed columns vs Tier2 raw_payload split
#   - the extract-stamped `date` is carried through (and required)
#   - schema-guard: raise on a missing expected column, warn on an unexpected one
#   - portfolio resolution and the unresolved-fund drop
#   - both legs (monto_cobrar, monto_pagar) carried; source='fms'
# ---------------------------------------------------------------

from datetime import date

import pandas as pd
import pytest

from src.pipelines.positions.fms.net_receivables import transform

# `date` is stamped by extract, so it must be present in the raw frame too.
ALL_COLUMNS = list(transform.STAGING_COLUMN_MAP.keys()) + transform.TIER_2_COLUMNS + ["date"]


def _raw_row(**overrides) -> dict:
    """A raw FMS net-receivables row as extract produces it (query cols + date)."""
    base = {
        "CodigoFondo": "FONDO0",
        "CodigoIsoMoneda": "USD",
        "MontoCobrar": 1000.0,
        "MontoPagar": 250.0,
        "date": date(2026, 8, 27),   # stamped by extract
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

def test_staging_maps_columns_and_carries_date():
    stg = transform.transform_for_staging(_raw_df([_raw_row()]), "batch_test")

    assert stg.loc[0, "batch_id"] == "batch_test"
    assert stg.loc[0, "date"] == date(2026, 8, 27)
    assert stg.loc[0, "codigo_fondo"] == "FONDO0"
    assert stg.loc[0, "codigo_iso_moneda"] == "USD"
    assert stg.loc[0, "monto_cobrar"] == 1000.0
    assert stg.loc[0, "monto_pagar"] == 250.0
    # no Tier 2 -> empty payload; `date` is not dumped into it
    assert stg.loc[0, "raw_payload"] == {}


def test_staging_raises_on_missing_expected_column():
    raw = _raw_df([_raw_row()]).drop(columns=["MontoCobrar"])
    with pytest.raises(ValueError):
        transform.transform_for_staging(raw, "b")


def test_staging_raises_when_date_missing():
    # `date` is expected (extract must stamp it) — missing it is a hard error.
    raw = _raw_df([_raw_row()]).drop(columns=["date"])
    with pytest.raises(ValueError, match="date"):
        transform.transform_for_staging(raw, "b")


def test_staging_unexpected_column_lands_in_payload():
    row = _raw_row()
    row["MontoTotalOriginal"] = 42.0
    raw = _raw_df([row], extra_columns=["MontoTotalOriginal"])

    stg = transform.transform_for_staging(raw, "b")
    assert stg.loc[0, "raw_payload"]["MontoTotalOriginal"] == 42.0


def test_staging_empty_in_empty_out():
    assert transform.transform_for_staging(pd.DataFrame(), "b").empty


# ---- transform_for_fact ---------------------------------------

def test_fact_resolves_portfolio_and_carries_both_legs():
    stg = transform.transform_for_staging(_raw_df([_raw_row()]), "b")
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))

    row = fact.iloc[0]
    assert row["portfolio_id"] == 7
    assert row["source"] == "fms"
    assert row["codigo_iso_moneda"] == "USD"
    assert row["monto_cobrar"] == 1000.0
    assert row["monto_pagar"] == 250.0
    assert row["date"] == date(2026, 8, 27)


def test_fact_drops_unresolved_fondo():
    stg = transform.transform_for_staging(
        _raw_df([
            _raw_row(CodigoFondo="FONDO0"),
            _raw_row(CodigoFondo="UNKNOWN", CodigoIsoMoneda="PEN"),
        ]),
        "b",
    )
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))

    assert len(fact) == 1
    assert set(fact["portfolio_id"]) == {7}


def test_fact_empty_in_empty_out():
    assert transform.transform_for_fact(pd.DataFrame(), _portfolios({"FONDO0": 7})).empty
