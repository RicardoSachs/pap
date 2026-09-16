# web/api/services/formatos.py
# ---------------------------------------------------------------------------
# Que formato espera cada sitio que recibe un archivo.
#
# Lo importante de este modulo es de donde saca la respuesta: de las MISMAS
# constantes que usa el lector para parsear. Una ayuda escrita a mano al lado
# del formulario se desincroniza en la primera vez que alguien agrega un
# alias de columna, y entonces miente - que es peor que no estar, porque el
# operador la sigue y el archivo se le cae sin entender por que.
#
# Aqui no hay ninguna lista de columnas escrita dos veces. Si manana el
# lector del tradebook acepta 'fecha_negociacion', la ventana lo dira sola.
#
# El unico formato que se describe a mano es el historico de la SBS, porque
# ahi no hay lector de columnas que consultar: es el Excel publicado por la
# SBS, con su disposicion propia, y lo que el operador necesita saber es que
# no debe tocarlo.
# ---------------------------------------------------------------------------
from __future__ import annotations

import datetime as dt

from src.pipelines.prices.bloomberg import manual_series as bbg
from src.pipelines.prices.manual import series as man
from src.pipelines.tradebook import operaciones as tb


def _columna(nombre, obligatoria, alias, ayuda, ejemplo=None) -> dict:
    # El nombre canonico va primero y no se repite entre los alias: es el que
    # conviene usar, y verlo dos veces sugeriria que son dos columnas.
    otros = [a for a in alias if a != nombre]
    return {"nombre": nombre, "obligatoria": obligatoria,
            "alias": otros, "ayuda": ayuda, "ejemplo": ejemplo}


AYUDA_TRADEBOOK = {
    "fecha": "El dia de la operacion. Vale 10/09/2026, 2026-09-10 o 10-09-2026.",
    "fondo": "El numero de fondo: 0, 1, 2 o 3.",
    "lado": "compra o venta. Tambien se entiende C/V y buy/sell.",
    "instrumento": "Como se llama el papel. Se guarda tal cual venga.",
    "cantidad": "Siempre positiva: la direccion la dice el lado.",
    "precio": "Opcional si viene el monto.",
    "monto": "Opcional si viene el precio: se calcula cantidad x precio.",
    "moneda": "PEN si se deja vacia. Se entienden S/, soles, US$ y dolares.",
    "contraparte": "Con quien se opero.",
    "fecha_liquidacion": "No puede ser anterior a la fecha de la operacion.",
    "referencia": "El id que le da tu sistema. Es lo que evita que recargar "
                  "el mismo archivo duplique: las filas que lo traen se "
                  "actualizan en vez de insertarse otra vez.",
    "trader": "Quien opero. Obligatorio en el registro propio; si el archivo "
              "entero es de una sola persona, se puede poner abajo en vez de "
              "columna por columna.",
    "nota": "Texto libre.",
}

EJEMPLO_TRADEBOOK = {
    "fecha": "10/09/2026", "fondo": "2", "lado": "compra",
    "instrumento": "PERU 3.55 03/31", "cantidad": "1,000,000", "precio": "98.45",
    "monto": "984,500.00", "moneda": "USD", "contraparte": "BCP",
    "fecha_liquidacion": "12/09/2026", "referencia": "OP00123",
    "trader": "R. SACHS", "nota": "",
}


def _tradebook(origen: str) -> dict:
    de_traders = origen in tb.ORIGENES_TRADER
    columnas = []
    for nombre, alias in tb._ALIAS.items():
        if nombre == "trader" and not de_traders:
            continue
        obligatoria = (nombre in tb._OBLIGATORIAS
                       or (nombre == "trader" and de_traders))
        columnas.append(_columna(nombre, obligatoria, alias,
                                 AYUDA_TRADEBOOK.get(nombre, ""),
                                 EJEMPLO_TRADEBOOK.get(nombre)))
    return {
        "titulo": ("Operaciones · registro del trader" if de_traders
                   else "Operaciones · reporte de FMS"),
        "resumen": (
            "Una fila por operacion. Los encabezados pueden estar en "
            "cualquier fila de las primeras: se busca la que tenga 'fecha'. "
            "El orden de las columnas da igual, y las que no se reconozcan se "
            "ignoran."),
        "columnas": columnas,
        "notas": _notas_tradebook(de_traders),
        "plantilla": f"/api/tradebook/plantilla?origen={origen}",
    }


def _notas_tradebook(de_traders: bool) -> list[str]:
    notas = [
        "Hace falta el monto o el precio; con uno de los dos basta.",
        "La cantidad va siempre en positivo. Una cantidad negativa se "
        "descarta, porque la direccion ya la dice el lado.",
    ]
    if de_traders:
        notas.append(
            "Cada fila lleva trader. Si el archivo entero es de una persona, "
            "deja la columna fuera y escribe el nombre en 'Trader del "
            "archivo': solo rellena las filas que no lo traigan.")
    else:
        notas.append(
            "El reporte de FMS NO lleva trader. Una fila con trader se "
            "descarta: FMS no dice quien opero, y ponerlo aqui seria "
            "inventarlo.")
    notas.append(
        "Excel o CSV. El formato se reconoce por el contenido, no por la "
        "extension. En CSV se deducen el separador y el decimal.")
    return notas


def _series_manuales() -> dict:
    return {
        "titulo": "Valores de una serie manual",
        "resumen": (
            "Dos columnas: la fecha y el valor. Los encabezados pueden estar "
            "en cualquier fila de las primeras: se busca la que tenga "
            "'fecha'."),
        "columnas": [
            _columna("fecha", True, man._COLS_FECHA,
                     "Vale 10/09/2026, 2026-09-10 o 10-09-2026.", "10/09/2026"),
            _columna("valor", True, man._COLS_VALOR,
                     "El nivel de la serie en esa fecha.", "1,234.5678"),
        ],
        "notas": [
            "Si no hay una columna llamada 'valor' pero el archivo tiene solo "
            "dos columnas, se toma la otra como el valor y se avisa.",
            "Una fecha repetida se queda con el ultimo valor que aparezca.",
            "Excel o CSV. Si las celdas numericas estan como TEXTO y llevan "
            "comas y puntos, el archivo se rechaza en vez de adivinar el "
            "separador decimal: adivinarlo mal multiplica por mil sin que se "
            "note. Da formato numerico a las celdas o exporta a CSV.",
        ],
        "plantilla": "/api/spp/series-manuales/plantilla",
    }


def _bloomberg() -> dict:
    # El alias de Bloomberg esta al reves que los demas (alias -> destino),
    # asi que se le da la vuelta para poder listarlo por columna.
    porcol: dict[str, list] = {}
    for alias, destino in bbg._ALIAS_COL.items():
        porcol.setdefault(destino, []).append(alias)
    ayuda = {
        "ticker": "El ticker tal como lo pide Bloomberg, con su sufijo.",
        "campo": "PX_LAST si se deja vacio.",
        "intervalo": "diario si se deja vacio.",
        "fecha_inicio": "Desde cuando descargar. Informativa.",
        "descripcion": "Para reconocerla en la lista.",
        "moneda": "Informativa.",
    }
    ejemplo = {"ticker": "SPX Index", "campo": "PX_LAST", "intervalo": "diario",
               "fecha_inicio": "01/01/2016", "descripcion": "S&P 500",
               "moneda": "USD"}
    return {
        "titulo": "Series de Bloomberg a registrar",
        "resumen": (
            "Este archivo declara QUE descargar, no los datos: los precios "
            "los trae Bloomberg despues. Solo el ticker es obligatorio."),
        "columnas": [
            _columna(c, c == "ticker", porcol.get(c, []), ayuda.get(c, ""),
                     ejemplo.get(c))
            for c in bbg.CABECERA_SERIES
        ],
        "notas": [
            "Registrar es idempotente por ticker + campo + intervalo: volver "
            "a subir el mismo archivo actualiza, no duplica.",
            "Las columnas que no se reconozcan se ignoran y se avisa de ello.",
        ],
        "plantilla": "/api/spp/bloomberg/plantilla",
    }


def _valor_cuota_historico() -> dict:
    """
    El unico que no sale de un lector de columnas: es el Excel que publica
    la SBS, y lo que hay que decir del formato es que no se toque.
    """
    return {
        "titulo": "Historico de valor cuota (archivo de la SBS)",
        "resumen": (
            "No es una plantilla nuestra: es el Excel que publica la SBS, tal "
            "como se descarga. Su disposicion ya se entiende - no hay que "
            "reordenarlo, renombrar hojas ni quitar las filas de titulo."),
        "columnas": [],
        "notas": [
            "Descargalo con el boton «Abrir la pagina de la SBS» que esta "
            "aqui al lado, y elige «Valores cuota desde Agosto 1993».",
            "Trae las cuatro AFP y los cuatro tipos de fondo en la misma "
            "hoja; el lector los separa solo.",
            "Las fechas futuras se descartan y se avisa de ellas.",
            "Subirlo NO carga nada todavia: primero muestra que cambiaria, y "
            "la carga se confirma despues.",
        ],
        "plantilla": None,
    }


FORMATOS = {
    "tradebook_traders": lambda: _tradebook("excel"),
    "tradebook_fms": lambda: _tradebook("fms"),
    "series_manuales": _series_manuales,
    "bloomberg": _bloomberg,
    "valor_cuota_historico": _valor_cuota_historico,
}


def formato(clave: str) -> dict:
    if clave not in FORMATOS:
        raise ValueError(
            f"No hay un formato llamado '{clave}'. Los que hay: "
            + ", ".join(sorted(FORMATOS)))
    return {"clave": clave, **FORMATOS[clave]()}
