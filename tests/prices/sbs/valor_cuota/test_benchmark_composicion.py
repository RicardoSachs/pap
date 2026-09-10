# tests/prices/sbs/valor_cuota/test_benchmark_composicion.py
# ---------------------------------------------------------------
# Golden tests for encadenar(): the drifting (buy-and-hold)
# composite-index chaining. No DB.
#
# Pinned down:
#   - units are struck at the rebalance (peso * I / price) and the
#     index is their mark-to-market afterwards, so weights DRIFT
#   - a rebalance re-strikes at the chained level: the index is
#     CONTINUOUS across composition changes
#   - prices forward-fill inside the grid
#   - a component with no price at the strike fails loud, by name
# ---------------------------------------------------------------

import datetime as dt

import pytest

from src.pipelines.prices.sbs.valor_cuota.benchmark_composicion import encadenar

D1, D2, D3, D4 = (dt.date(2026, 1, d) for d in (5, 6, 7, 8))


def _comp(etiqueta, peso, precios):
    return {"etiqueta": etiqueta, "peso": peso, "precios": precios}


def test_deriva_un_periodo():
    # uA = 0.6*100/10 = 6 unidades; uB = 0.4*100/20 = 2 unidades.
    niveles = dict(encadenar([{
        "desde": D1,
        "componentes": [
            _comp("A", 0.6, {D1: 10, D2: 12, D3: 11}),
            _comp("B", 0.4, {D1: 20, D2: 20, D3: 22}),
        ],
    }]))
    assert niveles[D1] == pytest.approx(100.0)
    assert niveles[D2] == pytest.approx(6 * 12 + 2 * 20)   # 112: A ya pesa mas
    assert niveles[D3] == pytest.approx(6 * 11 + 2 * 22)   # 110


def test_rebalanceo_es_continuo_y_re_estrena_pesos():
    niveles = dict(encadenar([
        {"desde": D1, "componentes": [
            _comp("A", 0.6, {D1: 10, D2: 12}),
            _comp("B", 0.4, {D1: 20, D2: 20}),
        ]},
        {"desde": D3, "componentes": [
            _comp("A", 0.5, {D3: 11, D4: 11}),
            _comp("B", 0.5, {D3: 22, D4: 24.2}),
        ]},
    ]))
    # El nivel entra al rebalanceo en 112 (cierre del periodo previo) y
    # el rebalanceo NO lo altera: solo re-parte el capital 50/50.
    assert niveles[D2] == pytest.approx(112.0)
    assert niveles[D3] == pytest.approx(112.0)
    # D4: la pata B (56 -> *1.10) sube 10%; la A queda igual.
    assert niveles[D4] == pytest.approx(56.0 + 56.0 * 1.10)


def test_precio_faltante_se_arrastra():
    niveles = dict(encadenar([{
        "desde": D1,
        "componentes": [
            _comp("A", 0.5, {D1: 10, D2: 12}),
            _comp("B", 0.5, {D1: 20}),          # sin precio en D2: ffill
        ],
    }]))
    assert niveles[D2] == pytest.approx(5 * 12 + 2.5 * 20)  # B al ultimo precio


def test_sin_precio_al_estrenar_falla_con_nombre():
    with pytest.raises(ValueError, match="'B'"):
        encadenar([{
            "desde": D1,
            "componentes": [
                _comp("A", 0.5, {D1: 10}),
                _comp("B", 0.5, {D2: 20}),      # su primer precio es POSTERIOR
            ],
        }])


def test_base_configurable():
    niveles = dict(encadenar(
        [{"desde": D1, "componentes": [_comp("A", 1.0, {D1: 10, D2: 11})]}],
        base=1000.0))
    assert niveles[D1] == pytest.approx(1000.0)
    assert niveles[D2] == pytest.approx(1100.0)
