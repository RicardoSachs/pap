# tests/positions/fms/forwards/test_transform.py
# ---------------------------------------------------------------
# Golden-file tests for the FMS forwards pure transforms. No DB, no FMS.
#
# These lock in the behaviour that is easy to break silently:
#   - yyyymmdd -> DATE conversion
#   - Tier1 typed columns vs Tier2 raw_payload split
#   - schema-guard: raise on a missing expected column, warn on an
#     unexpected one (it still lands in raw_payload)
#   - portfolio resolution and the unresolved-fund drop
#   - mtm_soles = PrecioInversion + PrecioDesinversion (NOT PrecioVector)
#   - fecha_vencimiento derivation
#   - the nocional_soles = valor_nocional * tipo_cambio_spot invariant
# ---------------------------------------------------------------

from datetime import date

import pandas as pd
import pytest

from src.pipelines.positions.fms.forwards import transform

ALL_COLUMNS = list(transform.STAGING_COLUMN_MAP.keys()) + transform.TIER_2_COLUMNS


def _raw_row(**overrides) -> dict:
    """A full vendor-native (PascalCase) FMS forwards row; override any field."""
    base = {
        # Tier 1
        "IdSecuencialFechaProceso": 20260622,
        "CodigoFondo": "FONDO0",
        "CodigoSbs": "SBS123",
        "CodigoIsoMonedaNocional": "USD",
        "CodigoIsoMonedaContraparte": "PEN",
        "ValorNocional": 1000.0,
        "TipoCambioSpot": 3.75,
        "NocionalSoles": 3750.0,
        "MonedaCompra": "USD",
        "MonedaVenta": "PEN",
        # Tier 2
        "CodigoReferencia": "REF-1",
        "IdTipoOperacion": 1,
        "IdSecuencialFechaForwardPrecio": 20260622,
        "IdSecuencialFechaOperacion": 20260601,
        "IdSecuencialFechaVencimiento": 20260921,
        "Remanente": 90,
        "ValorStrike": 3.80,
        "PrecioForward": 3.78,
        "PrecioVector": 999.0,          # deliberately NOT the MTM
        "PrecioInversion": 3800.0,
        "PrecioDesinversion": -3750.0,
        "IndCxcCxp": "C",
        "MonedaNocional": "USD",
        "MonedaContraparte": "PEN",
        "Importe": 50.0,
        "TipoMovimiento": "X",
        "IdCuentaCobrarPagar": 42,
        "ValorNocionalCarga": 1000.0,
        "PrecioInversionCarga": 3800.0,
        "PrecioDesinversionCarga": -3750.0,
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

    payload = stg.loc[0, "raw_payload"]
    # Tier 2 preserved verbatim...
    assert payload["PrecioInversion"] == 3800.0
    assert payload["PrecioDesinversion"] == -3750.0
    # ...Tier 1 not duplicated into the payload
    assert "CodigoFondo" not in payload


def test_staging_raises_on_missing_expected_column():
    raw = _raw_df([_raw_row()]).drop(columns=["PrecioInversion"])
    with pytest.raises(ValueError):
        transform.transform_for_staging(raw, "b")


def test_staging_unexpected_column_lands_in_payload():
    row = _raw_row()
    row["BrandNewCol"] = "surprise"
    raw = _raw_df([row], extra_columns=["BrandNewCol"])

    stg = transform.transform_for_staging(raw, "b")
    assert stg.loc[0, "raw_payload"]["BrandNewCol"] == "surprise"


def test_staging_empty_in_empty_out():
    assert transform.transform_for_staging(pd.DataFrame(), "b").empty


# ---- transform_for_fact ---------------------------------------

def test_fact_mtm_is_inversion_minus_desinversion():
    stg = transform.transform_for_staging(
        _raw_df([_raw_row(PrecioInversion=3800.0, PrecioDesinversion=-3750.0)]), "b"
    )
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))

    # 3800 - 3750 = 50; NOT PrecioVector (999)
    assert fact.iloc[0]["mtm_soles"] == 50.0
    assert fact.iloc[0]["portfolio_id"] == 7
    assert fact.iloc[0]["source"] == "fms"
    assert fact.iloc[0]["fecha_vencimiento"] == date(2026, 9, 21)


def test_fact_mtm_null_when_operand_missing():
    stg = transform.transform_for_staging(
        _raw_df([_raw_row(PrecioInversion=None)]), "b"
    )
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))
    assert fact.iloc[0]["mtm_soles"] is None


def test_fact_drops_unresolved_fondo():
    stg = transform.transform_for_staging(
        _raw_df([
            _raw_row(CodigoFondo="FONDO0", CodigoSbs="SBS123"),
            _raw_row(CodigoFondo="UNKNOWN", CodigoSbs="SBS999"),
        ]),
        "b",
    )
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))

    assert len(fact) == 1
    assert set(fact["portfolio_id"]) == {7}


def test_fact_nocional_soles_invariant():
    stg = transform.transform_for_staging(_raw_df([_raw_row()]), "b")
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))
    row = fact.iloc[0]
    assert row["nocional_soles"] == row["valor_nocional"] * row["tipo_cambio_spot"]


def test_fact_empty_in_empty_out():
    assert transform.transform_for_fact(pd.DataFrame(), _portfolios({"FONDO0": 7})).empty


# ---- null pass-through (proves the transforms are innocent) ----
# A stale FMS TipoCambioSpot arrives NULL; the transforms must pass it through
# unchanged (not fabricate a value, not drop the row). The NULL is a source/SQL
# problem — these lock the transforms so nobody re-investigates them.

def test_staging_preserves_null_spot():
    stg = transform.transform_for_staging(_raw_df([_raw_row(TipoCambioSpot=None)]), "b")
    assert pd.isna(stg.loc[0, "tipo_cambio_spot"])


def test_fact_preserves_null_nocional_soles():
    stg = transform.transform_for_staging(_raw_df([_raw_row(NocionalSoles=None)]), "b")
    fact = transform.transform_for_fact(stg, _portfolios({"FONDO0": 7}))
    assert pd.isna(fact.iloc[0]["nocional_soles"])
