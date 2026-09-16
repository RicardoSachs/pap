"""
El Tradebook: lo que decide si una fila entra al libro y como.

No se prueba la aritmetica sino los sitios donde equivocarse cuesta: el
lado (que invierte el signo de la operacion), el monto deducido (que no
puede deducirse al reves), y la normalizacion de lo que viene escrito de
cualquier manera en un Excel de mesa.
"""
import datetime as dt

import pytest

from src.pipelines.tradebook.operaciones import (_validar, normalizar_lado,
                                                 normalizar_moneda)


# ---- El lado ---------------------------------------------------------------

@pytest.mark.parametrize("crudo", ["compra", "COMPRA", " Compra ", "C", "c",
                                   "buy", "BUY", "B", "adquisicion"])
def test_las_formas_de_decir_compra(crudo):
    assert normalizar_lado(crudo) == "compra"


@pytest.mark.parametrize("crudo", ["venta", "VENTA", "V", "sell", "SELL", "S",
                                   "sold"])
def test_las_formas_de_decir_venta(crudo):
    assert normalizar_lado(crudo) == "venta"


@pytest.mark.parametrize("crudo", ["permuta", "swap", "", None, "reporte", "x"])
def test_un_lado_que_no_se_reconoce_se_rechaza_en_vez_de_suponerse(crudo):
    """
    Adivinar el lado invierte el signo de la operacion. Es preferible que
    la fila caiga y se vea en las descartadas a que entre como lo
    contrario de lo que fue.
    """
    with pytest.raises(ValueError, match="lado"):
        normalizar_lado(crudo)


# ---- La moneda -------------------------------------------------------------

@pytest.mark.parametrize("crudo, esperado", [
    ("PEN", "PEN"), ("pen", "PEN"), ("S/", "PEN"), ("S/.", "PEN"),
    ("soles", "PEN"), ("SOLES", "PEN"),
    ("USD", "USD"), ("usd", "USD"), ("dolares", "USD"), ("US$", "USD"),
    ("EUR", "EUR"),
    ("", "PEN"), (None, "PEN"),          # vacio = moneda de la casa
])
def test_normalizacion_de_moneda(crudo, esperado):
    assert normalizar_moneda(crudo) == esperado


# ---- La operacion completa -------------------------------------------------

BASE = {"fecha": "2026-09-10", "fondo": 2, "lado": "compra",
        "instrumento": "PERU 3.55 03/31", "cantidad": 1000, "precio": 98.45,
        "moneda": "USD"}


def test_el_monto_se_deduce_de_cantidad_por_precio():
    op = _validar(dict(BASE))
    assert op["monto"] == pytest.approx(1000 * 98.45)


def test_el_monto_que_viene_manda_sobre_el_calculado():
    """
    El monto del sistema origen lleva comisiones y devengado dentro.
    Recalcularlo restataria en silencio lo que la mesa pago de verdad.
    """
    op = _validar({**BASE, "monto": 98_600})
    assert op["monto"] == 98_600


def test_sin_monto_ni_precio_no_hay_operacion():
    sin = {k: v for k, v in BASE.items() if k != "precio"}
    with pytest.raises(ValueError, match="monto"):
        _validar(sin)


def test_la_cantidad_negativa_se_rechaza():
    """
    La direccion la dice el lado. Una cantidad negativa en una venta
    significaria la venta dos veces, y cada lector tendria que decidir a
    cual de las dos hacer caso.
    """
    with pytest.raises(ValueError, match="mayor que cero"):
        _validar({**BASE, "cantidad": -1000})


def test_la_cantidad_cero_tampoco():
    with pytest.raises(ValueError, match="mayor que cero"):
        _validar({**BASE, "cantidad": 0})


def test_la_liquidacion_no_puede_ser_anterior_a_la_operacion():
    with pytest.raises(ValueError, match="liquidacion"):
        _validar({**BASE, "fecha_liquidacion": "2026-09-01"})


def test_la_liquidacion_el_mismo_dia_es_valida():
    op = _validar({**BASE, "fecha_liquidacion": "2026-09-10"})
    assert op["fecha_liquidacion"] == dt.date(2026, 9, 10)


def test_las_fechas_llegan_como_fecha_no_como_texto():
    op = _validar(dict(BASE))
    assert isinstance(op["fecha"], dt.date)


@pytest.mark.parametrize("crudo", ["10/09/2026", "2026-09-10", "10-09-2026"])
def test_formatos_de_fecha_que_usa_una_mesa(crudo):
    assert _validar({**BASE, "fecha": crudo})["fecha"] == dt.date(2026, 9, 10)


def test_el_instrumento_vacio_se_rechaza():
    with pytest.raises(ValueError, match="instrumento"):
        _validar({**BASE, "instrumento": "   "})


def test_un_origen_inventado_se_rechaza():
    """La columna dice de donde salio la fila; un valor libre la haria inutil."""
    with pytest.raises(ValueError, match="Origen"):
        _validar({**BASE, "origen": "intuicion"})


def test_el_origen_por_defecto_es_manual():
    assert _validar(dict(BASE))["origen"] == "manual"


def test_la_referencia_vacia_queda_en_nulo_y_no_en_cadena():
    """
    El indice unico es parcial sobre referencia IS NOT NULL. Una cadena
    vacia no es nula, asi que dos filas sin referencia chocarian entre si
    y la segunda carga fallaria.
    """
    assert _validar({**BASE, "referencia": ""})["referencia"] is None
    assert _validar({**BASE, "referencia": "   "})["referencia"] is None
    assert _validar({**BASE, "referencia": "OP1"})["referencia"] == "OP1"
