# src/pipelines/tradebook/operaciones.py
# ---------------------------------------------------------------------------
# El tradebook: alta, lectura y baja de las operaciones de la mesa, y las
# tres maneras en que entran.
#
#   - a mano, una operacion suelta desde el formulario;
#   - por archivo, un Excel o CSV que se revisa antes de guardarse;
#   - derivadas de las posiciones, que es la mas delicada y se explica en
#     derivar_de_posiciones().
#
# El lector de archivos sigue el mismo contrato que el de series manuales:
# leer primero sin tocar la base, devolver lo leido Y lo descartado, y
# guardar solo despues de que el operador haya visto ambas cosas.
# ---------------------------------------------------------------------------
from __future__ import annotations

import datetime as dt
import io
import logging
import re

import pandas as pd

from src.db.connection import get_connection
from src.shared import tabular

logger = logging.getLogger(__name__)

LADOS = ("compra", "venta")
ORIGENES = ("excel", "manual", "posiciones")

# Como puede venir llamada cada columna. La clave es el nombre normalizado
# por tabular.clave_col (sin tildes, minusculas, sin separadores).
_ALIAS = {
    "fecha": ("fecha", "date", "fechaoperacion", "fechanegociacion", "dia",
              "tradedate"),
    "fondo": ("fondo", "tipofondo", "cartera", "portafolio", "fund"),
    "lado": ("lado", "operacion", "tipo", "tipooperacion", "side", "compraventa",
             "buysell"),
    "instrumento": ("instrumento", "valor", "activo", "nemotecnico", "nemonico",
                    "descripcion", "security", "isin", "ticker"),
    "cantidad": ("cantidad", "nominal", "nominales", "unidades", "titulos",
                 "quantity", "qty"),
    "precio": ("precio", "price", "preciolimpio", "cotizacion"),
    "monto": ("monto", "importe", "montototal", "valorefectivo", "efectivo",
              "amount", "total"),
    "moneda": ("moneda", "divisa", "currency", "codigoisomoneda"),
    "contraparte": ("contraparte", "counterparty", "broker", "intermediario",
                    "agente"),
    "fecha_liquidacion": ("fechaliquidacion", "liquidacion", "settlementdate",
                          "settle", "fechavalor"),
    "referencia": ("referencia", "id", "idoperacion", "numerooperacion",
                   "folio", "tradeid", "operacion_id"),
    "nota": ("nota", "notas", "observacion", "observaciones", "comentario"),
}
# Sin estas no hay operacion que registrar.
_OBLIGATORIAS = ("fecha", "fondo", "lado", "instrumento", "cantidad")

_COMPRA = ("compra", "compras", "c", "b", "buy", "bought", "adquisicion")
_VENTA = ("venta", "ventas", "v", "s", "sell", "sold", "sale")

_CAMPOS = ("referencia", "fecha", "fondo", "lado", "instrumento", "entity_id",
           "cantidad", "precio", "monto", "moneda", "contraparte",
           "fecha_liquidacion", "origen", "nota")


# ---- Normalizacion de un valor suelto -------------------------------------

def _texto(v) -> str | None:
    if v is None or (isinstance(v, float) and v != v):
        return None
    t = str(v).strip()
    return t or None


def normalizar_lado(v) -> str:
    """
    'C', 'compra', 'BUY' -> 'compra'. Lo que no se reconozca se rechaza
    en vez de suponerse: adivinar el lado invierte el signo de la
    operacion, que es el peor error posible en este dato.
    """
    t = (_texto(v) or "").lower()
    t = tabular.sin_tildes(t)
    if t in _COMPRA:
        return "compra"
    if t in _VENTA:
        return "venta"
    raise ValueError(
        f"No se reconoce el lado '{_texto(v) or ''}'. Usa compra o venta "
        "(tambien vale C/V, buy/sell).")


def normalizar_moneda(v) -> str:
    """PEN por defecto, y S/ y soles entendidos como lo mismo."""
    t = (_texto(v) or "").upper().replace("/", "").replace(".", "")
    if not t:
        return "PEN"
    equivalencias = {"S": "PEN", "SOLES": "PEN", "SOL": "PEN", "NUEVOSSOLES": "PEN",
                     "US$": "USD", "USS": "USD", "DOLARES": "USD", "DOLAR": "USD",
                     "$": "USD"}
    return equivalencias.get(t, t[:8])


def _fecha(v, campo: str):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    f = tabular.fecha_flexible(_texto(v) or "")
    if f is None:
        raise ValueError(f"No se entiende la {campo} '{_texto(v) or ''}'.")
    return f


def _numero(v, campo: str, coma_decimal=None, obligatorio=True):
    if v is None or (isinstance(v, float) and v != v) or str(v).strip() == "":
        if obligatorio:
            raise ValueError(f"Falta {campo}.")
        return None
    if isinstance(v, (int, float)):
        return float(v)
    n = tabular.num_flexible(str(v), coma_decimal)
    if n is None:
        raise ValueError(f"No se entiende {campo}: '{v}'.")
    return float(n)


def _validar(op: dict) -> dict:
    """
    Deja una operacion lista para guardar, o explica por que no lo esta.

    El monto es el unico campo que se deduce cuando falta, y solo desde
    cantidad * precio. Al reves no: de un monto y una cantidad saldria un
    precio que la mesa no negocio, porque el monto suele llevar comisiones
    y devengado dentro.
    """
    fecha = _fecha(op.get("fecha"), "fecha")
    lado = normalizar_lado(op.get("lado"))
    instrumento = _texto(op.get("instrumento"))
    if not instrumento:
        raise ValueError("Falta el instrumento.")
    try:
        fondo = int(op.get("fondo"))
    except (TypeError, ValueError):
        raise ValueError(f"El fondo '{op.get('fondo')}' no es un numero.")

    cantidad = _numero(op.get("cantidad"), "la cantidad")
    if cantidad <= 0:
        raise ValueError("La cantidad tiene que ser mayor que cero. El lado "
                         "(compra o venta) es lo que dice la direccion.")
    precio = _numero(op.get("precio"), "el precio", obligatorio=False)
    monto = _numero(op.get("monto"), "el monto", obligatorio=False)
    if monto is None:
        if precio is None:
            raise ValueError("Falta el monto y no hay precio con el que "
                             "calcularlo.")
        monto = cantidad * precio
    if monto < 0:
        raise ValueError("El monto no puede ser negativo: el lado es lo que "
                         "dice si entra o sale dinero.")

    liquidacion = (_fecha(op["fecha_liquidacion"], "fecha de liquidacion")
                   if _texto(op.get("fecha_liquidacion")) else None)
    if liquidacion and liquidacion < fecha:
        raise ValueError(f"La liquidacion ({liquidacion}) no puede ser anterior "
                         f"a la operacion ({fecha}).")

    origen = _texto(op.get("origen")) or "manual"
    if origen not in ORIGENES:
        raise ValueError(f"Origen '{origen}' desconocido.")

    return {
        "referencia": _texto(op.get("referencia")),
        "fecha": fecha,
        "fondo": fondo,
        "lado": lado,
        "instrumento": instrumento,
        "entity_id": op.get("entity_id"),
        "cantidad": cantidad,
        "precio": precio,
        "monto": monto,
        "moneda": normalizar_moneda(op.get("moneda")),
        "contraparte": _texto(op.get("contraparte")),
        "fecha_liquidacion": liquidacion,
        "origen": origen,
        "nota": _texto(op.get("nota")),
    }


# ---- Alta, baja y lectura --------------------------------------------------

_INSERTA = """
INSERT INTO tradebook (referencia, fecha, fondo, lado, instrumento, entity_id,
                       cantidad, precio, monto, moneda, contraparte,
                       fecha_liquidacion, origen, nota)
VALUES (%(referencia)s, %(fecha)s, %(fondo)s, %(lado)s, %(instrumento)s,
        %(entity_id)s, %(cantidad)s, %(precio)s, %(monto)s, %(moneda)s,
        %(contraparte)s, %(fecha_liquidacion)s, %(origen)s, %(nota)s)
"""
# Solo alcanza a las filas que traen referencia; el indice unico es parcial.
_UPSERT = _INSERTA + """
ON CONFLICT (referencia) WHERE referencia IS NOT NULL DO UPDATE SET
    fecha = EXCLUDED.fecha, fondo = EXCLUDED.fondo, lado = EXCLUDED.lado,
    instrumento = EXCLUDED.instrumento, entity_id = EXCLUDED.entity_id,
    cantidad = EXCLUDED.cantidad, precio = EXCLUDED.precio,
    monto = EXCLUDED.monto, moneda = EXCLUDED.moneda,
    contraparte = EXCLUDED.contraparte,
    fecha_liquidacion = EXCLUDED.fecha_liquidacion,
    origen = EXCLUDED.origen, nota = EXCLUDED.nota,
    actualizado_en = CURRENT_TIMESTAMP
"""


def registrar(op: dict) -> dict:
    """Registers one operation. Returns it as stored."""
    fila = _validar(op)
    with get_connection() as conn:
        conn.execute(_UPSERT if fila["referencia"] else _INSERTA, fila)
        nueva = conn.execute(
            "SELECT * FROM tradebook ORDER BY operacion_id DESC LIMIT 1"
        ).fetchone() if not fila["referencia"] else conn.execute(
            "SELECT * FROM tradebook WHERE referencia = %s", (fila["referencia"],)
        ).fetchone()
    logger.info(f"operacion registrada: {fila['fecha']} {fila['lado']} "
                f"{fila['instrumento']}")
    return _a_dict(nueva)


def actualizar(operacion_id: int, op: dict) -> dict:
    """Corrects a stored operation, keeping its id."""
    fila = _validar(op)
    fila["operacion_id"] = int(operacion_id)
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM tradebook WHERE operacion_id = %s",
                            (operacion_id,)).fetchone():
            raise ValueError(f"No existe la operacion {operacion_id}.")
        conn.execute("""
            UPDATE tradebook SET
                referencia = %(referencia)s, fecha = %(fecha)s, fondo = %(fondo)s,
                lado = %(lado)s, instrumento = %(instrumento)s,
                entity_id = %(entity_id)s, cantidad = %(cantidad)s,
                precio = %(precio)s, monto = %(monto)s, moneda = %(moneda)s,
                contraparte = %(contraparte)s,
                fecha_liquidacion = %(fecha_liquidacion)s, nota = %(nota)s,
                actualizado_en = CURRENT_TIMESTAMP
            WHERE operacion_id = %(operacion_id)s""", fila)
        return _a_dict(conn.execute(
            "SELECT * FROM tradebook WHERE operacion_id = %s",
            (operacion_id,)).fetchone())


def borrar(operacion_id: int) -> dict:
    """Removes one operation. Nothing references it, so nothing guards it."""
    with get_connection() as conn:
        fila = conn.execute("SELECT * FROM tradebook WHERE operacion_id = %s",
                            (operacion_id,)).fetchone()
        if not fila:
            raise ValueError(f"No existe la operacion {operacion_id}.")
        conn.execute("DELETE FROM tradebook WHERE operacion_id = %s",
                     (operacion_id,))
    return _a_dict(fila)


def _a_dict(fila) -> dict:
    if fila is None:
        return {}
    d = dict(fila)
    for k in ("fecha", "fecha_liquidacion", "creado_en", "actualizado_en"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("cantidad", "precio", "monto"):
        if d.get(k) is not None:
            d[k] = float(d[k])
    return d


def leer(desde=None, hasta=None, fondo=None, lado=None, contraparte=None,
         instrumento=None, limite: int | None = 500) -> list[dict]:
    """Operations matching the filters, newest first."""
    donde, args = [], []
    if desde:
        donde.append("fecha >= %s"); args.append(desde)
    if hasta:
        donde.append("fecha <= %s"); args.append(hasta)
    if fondo is not None:
        donde.append("fondo = %s"); args.append(int(fondo))
    if lado:
        donde.append("lado = %s"); args.append(normalizar_lado(lado))
    if contraparte:
        donde.append("contraparte ILIKE %s"); args.append(f"%{contraparte}%")
    if instrumento:
        donde.append("instrumento ILIKE %s"); args.append(f"%{instrumento}%")
    sql = "SELECT * FROM tradebook"
    if donde:
        sql += " WHERE " + " AND ".join(donde)
    sql += " ORDER BY fecha DESC, operacion_id DESC"
    if limite:
        sql += f" LIMIT {int(limite)}"
    with get_connection() as conn:
        return [_a_dict(f) for f in conn.execute(sql, tuple(args)).fetchall()]


def estado() -> dict:
    """What the book holds, for the header and the empty states."""
    with get_connection() as conn:
        base = conn.execute("""
            SELECT COUNT(*) AS filas, MIN(fecha) AS desde, MAX(fecha) AS hasta,
                   COUNT(DISTINCT contraparte) AS contrapartes,
                   COUNT(DISTINCT instrumento) AS instrumentos
            FROM tradebook""").fetchone()
        fondos = [f["fondo"] for f in conn.execute(
            "SELECT DISTINCT fondo FROM tradebook ORDER BY fondo").fetchall()]
        monedas = [f["moneda"] for f in conn.execute(
            "SELECT DISTINCT moneda FROM tradebook ORDER BY moneda").fetchall()]
        origenes = {f["origen"]: f["n"] for f in conn.execute(
            "SELECT origen, COUNT(*) AS n FROM tradebook GROUP BY origen").fetchall()}
    d = dict(base)
    d["desde"] = str(d["desde"]) if d["desde"] else None
    d["hasta"] = str(d["hasta"]) if d["hasta"] else None
    d.update(fondos=fondos, monedas=monedas, origenes=origenes)
    return d


# ---- Carga por archivo -----------------------------------------------------

def leer_archivo(datos, hoja=None) -> dict:
    """
    Excel or CSV -> the operations it holds, WITHOUT touching the DB.

    Returns what was read and what was discarded, row by row, so the
    operator decides with both in front of them. Format is recognized by
    content, not by extension.
    """
    if tabular.es_excel(datos):
        filas, nombre_hoja, hojas = tabular.filas_de_excel(datos, hoja)
        origen_fmt = "excel"
        textos = [str(c).strip() for f in filas for c in f
                  if isinstance(c, str) and re.fullmatch(r"-?[\d.,\s]+", c.strip())
                  and re.search(r"\d", c)]
        coma_decimal = tabular.estilo_decimal(textos)
        # Mismo criterio que el lector de series: un separador decimal mal
        # supuesto no se nota y multiplica por mil.
        if coma_decimal is None and any("," in t or "." in t for t in textos):
            raise ValueError(
                "No se pudo decidir si la coma o el punto es el separador "
                "decimal del archivo. Da formato numerico a las celdas en "
                "Excel, o exporta a CSV, y vuelve a subirlo.")
    else:
        filas, _sep, coma_decimal = tabular.filas_de_csv(datos)
        origen_fmt, nombre_hoja, hojas = "csv", None, []

    icab = tabular.fila_cabecera(
        filas, lambda c: tabular.clave_col(c) in _ALIAS["fecha"])
    if icab is None:
        vistas = [str(c) for f in filas[:3] for c in f
                  if str(c).strip() and str(c) != "nan"]
        raise ValueError(
            "Falta la columna 'fecha'. No se encontro una fila de encabezados "
            f"en las primeras filas. Se leyo: {', '.join(vistas[:10]) or 'nada'}")

    avisos = []
    if icab:
        avisos.append(f"Los encabezados estaban en la fila {icab + 1}; "
                      "lo anterior se ignoro.")
    cabecera = tabular.limpiar_cabecera(filas[icab])
    claves = [tabular.clave_col(c) for c in cabecera]
    icol = {campo: next((i for i, c in enumerate(claves) if c in alias), None)
            for campo, alias in _ALIAS.items()}

    faltan = [c for c in _OBLIGATORIAS if icol[c] is None]
    if faltan:
        raise ValueError(
            f"Faltan columnas obligatorias: {', '.join(faltan)}. La cabecera "
            f"leida fue: {', '.join(c for c in cabecera if c)}")
    if icol["monto"] is None and icol["precio"] is None:
        raise ValueError("Hace falta la columna 'monto' o la de 'precio' para "
                         "saber cuanto se opero.")

    def celda(fila, campo):
        i = icol[campo]
        if i is None or i >= len(fila):
            return None
        v = fila[i]
        return None if (isinstance(v, float) and v != v) else v

    operaciones, descartadas = [], []
    for n, fila in enumerate(filas[icab + 1:], start=icab + 2):
        if all(v is None or (isinstance(v, float) and v != v)
               or str(v).strip() == "" for v in fila):
            continue
        crudo = {campo: celda(fila, campo) for campo in _ALIAS}
        try:
            for campo in ("cantidad", "precio", "monto"):
                crudo[campo] = _numero(crudo[campo], campo, coma_decimal,
                                       obligatorio=(campo == "cantidad"))
            op = _validar({**crudo, "origen": "excel"})
            op["_fila"] = n
            operaciones.append(op)
        except ValueError as exc:
            descartadas.append({"fila": n, "motivo": str(exc),
                                "texto": " | ".join(str(c) for c in fila[:6])})

    return {
        "formato": origen_fmt, "hoja": nombre_hoja, "hojas": hojas,
        "columnas": {k: (cabecera[i] if i is not None else None)
                     for k, i in icol.items()},
        "leidas": len(operaciones), "descartadas": descartadas,
        "avisos": avisos,
        "operaciones": [{k: (str(v) if isinstance(v, dt.date) else v)
                         for k, v in o.items()} for o in operaciones],
        "resumen": _resumen_lote(operaciones),
    }


def _resumen_lote(operaciones: list[dict]) -> dict:
    """Lo que el operador necesita ver ANTES de confirmar la carga."""
    if not operaciones:
        return {"desde": None, "hasta": None, "fondos": [], "monedas": [],
                "compras": 0, "ventas": 0, "con_referencia": 0}
    fechas = [o["fecha"] for o in operaciones]
    return {
        "desde": str(min(fechas)), "hasta": str(max(fechas)),
        "fondos": sorted({o["fondo"] for o in operaciones}),
        "monedas": sorted({o["moneda"] for o in operaciones}),
        "compras": sum(1 for o in operaciones if o["lado"] == "compra"),
        "ventas": sum(1 for o in operaciones if o["lado"] == "venta"),
        "con_referencia": sum(1 for o in operaciones if o["referencia"]),
    }


def importar(datos, hoja=None) -> dict:
    """
    Reads the file and SAVES it. The rows that carry a reference upsert
    on it; the ones that do not are inserted, because there is no way to
    tell a genuine repeat trade from a re-upload of the same one.
    """
    informe = leer_archivo(datos, hoja)
    if not informe["leidas"]:
        informe.update(guardadas=0, actualizadas=0, insertadas=0)
        return informe

    # Se revalida contra el diccionario, no contra lo serializado, para no
    # depender de como quedaron las fechas al convertirlas a texto.
    filas = [_validar({**o, "origen": "excel"}) for o in informe["operaciones"]]
    con_ref = [f["referencia"] for f in filas if f["referencia"]]
    with get_connection() as conn:
        ya_estaban = set()
        if con_ref:
            ya_estaban = {f["referencia"] for f in conn.execute(
                "SELECT referencia FROM tradebook WHERE referencia = ANY(%s)",
                (con_ref,)).fetchall()}
        for fila in filas:
            conn.execute(_UPSERT if fila["referencia"] else _INSERTA, fila)
    actualizadas = len(ya_estaban)
    informe.update(guardadas=len(filas), actualizadas=actualizadas,
                   insertadas=len(filas) - actualizadas)
    informe.pop("operaciones", None)
    logger.info(f"tradebook: {len(filas)} operacion(es) cargadas "
                f"({actualizadas} ya existian y se actualizaron).")
    return informe


def plantilla(filas: int = 8) -> bytes:
    """The template, with the column names the reader recognizes."""
    hoy = dt.date.today()
    ejemplo = pd.DataFrame({
        "referencia": [""] * filas,
        "fecha": [hoy] + [""] * (filas - 1),
        "fondo": [2] + [""] * (filas - 1),
        "lado": ["compra"] + [""] * (filas - 1),
        "instrumento": ["PERU 3.55 03/31"] + [""] * (filas - 1),
        "cantidad": [1000000] + [""] * (filas - 1),
        "precio": [98.45] + [""] * (filas - 1),
        "monto": [984500] + [""] * (filas - 1),
        "moneda": ["USD"] + [""] * (filas - 1),
        "contraparte": ["BCP"] + [""] * (filas - 1),
        "fecha_liquidacion": [hoy] + [""] * (filas - 1),
        "nota": [""] * filas,
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        ejemplo.to_excel(w, index=False, sheet_name="operaciones")
    return buf.getvalue()


def exportar(**filtros) -> bytes:
    """The filtered book as a spreadsheet."""
    filtros.setdefault("limite", None)
    df = pd.DataFrame(leer(**filtros))
    if df.empty:
        df = pd.DataFrame(columns=list(_CAMPOS))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="tradebook")
    return buf.getvalue()


# ---- Derivadas de las posiciones ------------------------------------------

# Flujos que mueven la cantidad SIN que haya habido una operacion. Si en
# ese dia y ese papel hay alguno, la variacion deja de ser evidencia de una
# compra o una venta.
_FLUJOS_SIN_OPERACION = (
    ("monto_acciones_liberadas", "acciones liberadas"),
    ("monto_rescates", "rescate o vencimiento"),
    ("monto_intereses_vencimiento_cupon", "cupon o vencimiento"),
)


def derivar_de_posiciones(desde=None, hasta=None, fondo=None) -> dict:
    """
    PROPOSES operations from day-to-day changes in holdings. It saves
    nothing: what it returns is meant to be reviewed first.

    A change in quantity is not a trade. The same delta is produced by a
    split, a maturity, a redemption or a corporate action, and the
    holdings feed carries those as separate cash flows on the same row.
    So every proposal says whether one of those flows was present that
    day, and those come back flagged: they are the ones the operator has
    to look at, not the ones to wave through.

    The price is the day's valuation price, not a traded price. It is
    offered because it is the best estimate available, and marked as an
    estimate because it is not what the desk paid.
    """
    donde = ["p.cantidad IS NOT NULL", "p.cantidad_anterior IS NOT NULL",
             "p.cantidad <> p.cantidad_anterior"]
    args: list = []
    if desde:
        donde.append("p.date >= %s"); args.append(desde)
    if hasta:
        donde.append("p.date <= %s"); args.append(hasta)
    if fondo is not None:
        donde.append("f.procode LIKE %s"); args.append(f"%{int(fondo)}%")

    columnas_flujo = ", ".join(f"p.{c}" for c, _ in _FLUJOS_SIN_OPERACION)
    sql = f"""
        SELECT p.date, p.portfolio_id, f.procode, f.display_name,
               p.security_entity_id, e.name AS instrumento,
               p.codigo_iso_moneda, p.cantidad, p.cantidad_anterior,
               p.precio_pen, {columnas_flujo}
        FROM fact_positions_securities p
        JOIN dim_portfolio f ON f.portfolio_id = p.portfolio_id
        LEFT JOIN dim_entity e ON e.entity_id = p.security_entity_id
        WHERE {' AND '.join(donde)}
        ORDER BY p.date DESC, e.name
        LIMIT 2000
    """
    with get_connection() as conn:
        filas = conn.execute(sql, tuple(args)).fetchall()

    propuestas, dudosas = [], 0
    for f in filas:
        delta = float(f["cantidad"]) - float(f["cantidad_anterior"])
        motivos = [etiqueta for col, etiqueta in _FLUJOS_SIN_OPERACION
                   if f.get(col) not in (None, 0)]
        precio = float(f["precio_pen"]) if f["precio_pen"] is not None else None
        propuestas.append({
            "fecha": str(f["date"]),
            "fondo": _fondo_de_procode(f["procode"]),
            "cartera": f["display_name"] or f["procode"],
            "lado": "compra" if delta > 0 else "venta",
            "instrumento": f["instrumento"] or f"entity {f['security_entity_id']}",
            "entity_id": f["security_entity_id"],
            "cantidad": abs(delta),
            "precio": precio,
            "precio_estimado": True,
            "monto": abs(delta) * precio if precio is not None else None,
            "moneda": f["codigo_iso_moneda"] or "PEN",
            "origen": "posiciones",
            "sospechosa": bool(motivos),
            "motivos": motivos,
        })
        dudosas += bool(motivos)

    return {
        "propuestas": propuestas,
        "total": len(propuestas),
        "sospechosas": dudosas,
        "nota": ("Son movimientos de tenencia, no operaciones observadas. "
                 "Las marcadas traen ademas un flujo (cupon, rescate o "
                 "acciones liberadas) ese mismo dia, asi que la variacion "
                 "puede no ser una compra ni una venta."),
    }


def _fondo_de_procode(procode: str) -> int | None:
    """El numero de fondo que lleve el codigo de cartera, si lo lleva."""
    m = re.search(r"(\d)", str(procode or ""))
    return int(m.group(1)) if m else None


def guardar_derivadas(propuestas: list[dict]) -> dict:
    """
    Stores reviewed proposals, marked origen='posiciones' so the row
    keeps saying it was inferred rather than observed.
    """
    guardadas, rechazadas = 0, []
    with get_connection() as conn:
        for p in propuestas or []:
            try:
                fila = _validar({**p, "origen": "posiciones"})
            except ValueError as exc:
                rechazadas.append({"instrumento": p.get("instrumento"),
                                   "motivo": str(exc)})
                continue
            conn.execute(_INSERTA, fila)
            guardadas += 1
    return {"guardadas": guardadas, "rechazadas": rechazadas}
