# src/pipelines/prices/sbs/valor_cuota/benchmark_composicion.py
# ---------------------------------------------------------------
# Composite benchmark: a versioned basket of priced series per fund
# type, and the calculation that turns it into the SPP_BENCH_F{n}
# level series in fact_prices.
#
# Semantics (the user's choices, deliberately):
#   - weights DRIFT between rebalances (buy-and-hold): the stored
#     peso is the allocation AT the rebalance date; afterwards each
#     holding floats with its price until the next composition.
#   - components price from any store ('bloomberg' registry, 'fact'
#     spine or 'manual' keyed-in series), optionally multiplied by
#     an FX series.
#   - recalcular() REGENERATES the whole benchmark series from the
#     first composition (base 100), replacing whatever was loaded
#     by hand - the composition is the source of truth.
#
# The chaining math lives in encadenar(), a pure function over
# plain dicts, so the arithmetic is testable without a database.
# ---------------------------------------------------------------

import datetime as dt
import logging

import pandas as pd

from src.db.connection import get_connection
from src.pipelines.prices.sbs.valor_cuota import afps as reg
from src.pipelines.prices.sbs.valor_cuota.loader import UPSERT_CORRIGE

logger = logging.getLogger(__name__)

BASE_INDICE = 100.0
FUENTES = ("bloomberg", "fact", "manual")


# ---- Definicion: un benchmark por fondo, con nombre ------------------

def leer_definiciones() -> list[dict]:
    """Los benchmarks declarados, con su cobertura y cuantos rebalanceos
    tienen. Incluye los fondos que todavia no tienen nombre propio."""
    with get_connection() as conn:
        declarados = {f["fondo"]: f for f in conn.execute(
            "SELECT fondo, nombre, descripcion FROM benchmark ORDER BY fondo"
        ).fetchall()}
        composiciones = {f["fondo"]: f["n"] for f in conn.execute(
            "SELECT fondo, COUNT(DISTINCT vigente_desde) AS n "
            "FROM benchmark_composicion GROUP BY fondo").fetchall()}
        fondos = reg.fondos_benchmark(conn)
        salida = []
        for f in fondos:
            d = declarados.get(f)
            serie = reg.series_map(conn).get((reg.procode_bench(f), "PX_LAST"))
            puntos = 0
            if serie:
                puntos = conn.execute(
                    "SELECT COUNT(*) AS n FROM fact_prices WHERE series_id = %s",
                    (serie["series_id"],)).fetchone()["n"]
            salida.append({
                "fondo": f,
                "nombre": (d["nombre"] if d else reg.nombre_benchmark(f, conn)),
                "descripcion": (d["descripcion"] if d else None),
                "declarado": d is not None,
                "rebalanceos": composiciones.get(f, 0),
                "puntos": int(puntos),
            })
    return salida


def guardar_definicion(fondo: int, nombre: str, descripcion=None) -> dict:
    """
    Crea o renombra el benchmark de un fondo.

    Declararlo es tambien lo que HABILITA a ese fondo a tener uno: la
    serie de niveles se registra aqui mismo, sin tocar
    config/afps.yaml. El nombre viaja a dim_entity.name, que es de
    donde lo leen el grafico y el libro.
    """
    fondo = int(fondo)
    if fondo not in reg.fondos():
        raise ValueError(
            f"El Fondo {fondo} no existe. Fondos: "
            + ", ".join(str(x) for x in reg.fondos()) + ".")
    nombre = str(nombre or "").strip()
    if not nombre:
        raise ValueError("El benchmark necesita un nombre.")
    descripcion = str(descripcion).strip() or None if descripcion else None

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO benchmark (fondo, nombre, descripcion)
            VALUES (%s, %s, %s)
            ON CONFLICT (fondo) DO UPDATE
                SET nombre = EXCLUDED.nombre,
                    descripcion = COALESCE(EXCLUDED.descripcion,
                                           benchmark.descripcion),
                    actualizado_en = CURRENT_TIMESTAMP
            """, (fondo, nombre, descripcion))
        # Registra la serie del fondo recien habilitado y pone el nombre
        # en la entidad, para que el resto del tablero lo vea.
        reg.register_series(conn)
        conn.execute(
            "UPDATE dim_entity SET name = %s WHERE procode = %s AND entity_type = 'index'",
            (nombre, reg.procode_bench(fondo)))
    logger.info(f"benchmark Fondo {fondo}: '{nombre}'.")
    return {"fondo": fondo, "nombre": nombre}


def borrar_definicion(fondo: int) -> dict:
    """
    Quita el NOMBRE del benchmark de un fondo; no toca sus composiciones
    ni la serie calculada, que siguen ahi si vuelve a declararse.
    """
    fondo = int(fondo)
    with get_connection() as conn:
        n = conn.execute("DELETE FROM benchmark WHERE fondo = %s",
                         (fondo,)).rowcount
    return {"fondo": fondo, "borrados": n}


# ---- Composiciones (CRUD versionado) --------------------------------

def leer_composiciones(fondo: int | None = None) -> list[dict]:
    """Baskets grouped by (fondo, vigente_desde), newest first."""
    sql = """
        SELECT fondo, vigente_desde, etiqueta, fuente, ref_id, peso,
               fx_fuente, fx_ref_id
        FROM benchmark_composicion
    """
    params: list = []
    if fondo is not None:
        sql += " WHERE fondo = %s"
        params.append(int(fondo))
    sql += " ORDER BY fondo, vigente_desde DESC, etiqueta"
    with get_connection() as conn:
        filas = conn.execute(sql, params).fetchall()

    grupos: dict[tuple, dict] = {}
    for f in filas:
        clave = (f["fondo"], f["vigente_desde"])
        g = grupos.setdefault(clave, {
            "fondo": f["fondo"], "vigente_desde": str(f["vigente_desde"]),
            "componentes": []})
        g["componentes"].append({
            "etiqueta": f["etiqueta"], "fuente": f["fuente"],
            "ref_id": f["ref_id"], "peso": float(f["peso"]),
            "fx_fuente": f["fx_fuente"], "fx_ref_id": f["fx_ref_id"]})
    return list(grupos.values())


def guardar_composicion(fondo: int, vigente_desde, componentes: list[dict]) -> dict:
    """
    Saves ONE basket (all its components) effective from a date.
    Re-saving the same (fondo, fecha) replaces that basket atomically;
    other effective dates are untouched - history is never edited.

    Weights are validated (>0, no duplicate refs) and NORMALIZED to
    sum 1, accepting 100-based input (60/30/10 == 0.6/0.3/0.1).
    """
    fondo = int(fondo)
    if fondo not in reg.fondos_benchmark():
        raise ValueError(
            f"El Fondo {fondo} no lleva benchmark. Solo "
            + ", ".join(f"Fondo {x}" for x in reg.fondos_benchmark()) + ".")
    fecha = pd.to_datetime(vigente_desde).date()
    if fecha > dt.date.today():
        raise ValueError("La fecha de vigencia no puede ser futura.")
    if not componentes:
        raise ValueError("La composicion no puede estar vacia.")

    limpios, vistos = [], set()
    total = 0.0
    for c in componentes:
        fuente = str(c.get("fuente") or "").strip()
        if fuente not in FUENTES:
            raise ValueError(f"Fuente no valida: {fuente}. "
                             "Usa bloomberg, fact o manual.")
        try:
            ref_id = int(c.get("ref_id"))
        except (TypeError, ValueError):
            raise ValueError(f"ref_id no valido para '{c.get('etiqueta')}'.")
        peso = float(c.get("peso") or 0)
        if peso <= 0:
            raise ValueError(f"El peso de '{c.get('etiqueta')}' debe ser mayor que cero.")
        if (fuente, ref_id) in vistos:
            raise ValueError(f"Componente repetido en la canasta: {c.get('etiqueta')}.")
        vistos.add((fuente, ref_id))
        fx_fuente = (str(c["fx_fuente"]).strip()
                     if c.get("fx_fuente") else None)
        fx_ref_id = int(c["fx_ref_id"]) if c.get("fx_ref_id") else None
        if (fx_fuente is None) != (fx_ref_id is None):
            raise ValueError(f"FX incompleto en '{c.get('etiqueta')}': "
                             "fuente y serie van juntos.")
        if fx_fuente is not None and fx_fuente not in FUENTES:
            raise ValueError(f"Fuente FX no valida: {fx_fuente}.")
        etiqueta = str(c.get("etiqueta") or "").strip()
        if not etiqueta:
            raise ValueError("Cada componente necesita una etiqueta (ticker).")
        limpios.append({"etiqueta": etiqueta, "fuente": fuente, "ref_id": ref_id,
                        "peso": peso, "fx_fuente": fx_fuente,
                        "fx_ref_id": fx_ref_id})
        total += peso

    # Accept 1-based or 100-based totals; anything else is a typo, not
    # a convention.
    if not (abs(total - 1.0) < 1e-6 or abs(total - 100.0) < 1e-4):
        raise ValueError(
            f"Los pesos suman {total:g}; deben sumar 1 (o 100).")
    for c in limpios:
        c["peso"] = c["peso"] / total

    with get_connection() as conn:
        _validar_referencias(conn, limpios, fondo)
        conn.execute(
            "DELETE FROM benchmark_composicion WHERE fondo = %s AND vigente_desde = %s",
            (fondo, fecha))
        for c in limpios:
            conn.execute(
                """
                INSERT INTO benchmark_composicion (
                    fondo, vigente_desde, etiqueta, fuente, ref_id, peso,
                    fx_fuente, fx_ref_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (fondo, fecha, c["etiqueta"], c["fuente"], c["ref_id"],
                 round(c["peso"], 6), c["fx_fuente"], c["fx_ref_id"]))

    logger.info(f"benchmark composicion: Fondo {fondo} desde {fecha} - "
                f"{len(limpios)} componente(s) guardados.")
    return {"fondo": fondo, "vigente_desde": str(fecha),
            "componentes": len(limpios)}


def borrar_composicion(fondo: int, vigente_desde) -> dict:
    fecha = pd.to_datetime(vigente_desde).date()
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM benchmark_composicion WHERE fondo = %s AND vigente_desde = %s",
            (int(fondo), fecha))
    return {"fondo": int(fondo), "vigente_desde": str(fecha),
            "borrados": cur.rowcount}


def _validar_referencias(conn, componentes: list[dict], fondo: int) -> None:
    """Every referenced series (price and FX legs) must exist, and none of
    them may be the benchmark this composition defines."""
    propia = reg.series_map(conn).get((reg.procode_bench(fondo), "PX_LAST"))
    sid_propia = propia["series_id"] if propia else None
    for c in componentes:
        # A benchmark that holds itself recomposes on every recalculation:
        # _armar_periodos reads the levels written by the previous run
        # (before the DELETE), so the index drifts a little further each
        # time, with no error and nothing to notice.
        if (sid_propia is not None and c["fuente"] == "fact"
                and c["ref_id"] == sid_propia):
            raise ValueError(
                f"El benchmark del Fondo {fondo} no puede ser componente de "
                "si mismo.")
        pares = [(c["fuente"], c["ref_id"], c["etiqueta"])]
        if c["fx_ref_id"] is not None:
            pares.append((c["fx_fuente"], c["fx_ref_id"], f"FX de {c['etiqueta']}"))
        for fuente, ref_id, nombre in pares:
            if fuente == "bloomberg":
                fila = conn.execute(
                    "SELECT 1 FROM bloomberg_serie WHERE serie_id = %s",
                    (ref_id,)).fetchone()
            elif fuente == "manual":
                fila = conn.execute(
                    "SELECT 1 FROM serie_manual WHERE serie_id = %s",
                    (ref_id,)).fetchone()
            else:
                fila = conn.execute(
                    "SELECT 1 FROM series_registry WHERE series_id = %s",
                    (ref_id,)).fetchone()
            if fila is None:
                raise ValueError(
                    f"La serie de '{nombre}' (fuente {fuente}, id {ref_id}) "
                    "no existe.")


# ---- Precios --------------------------------------------------------

def usos_de(conn, fuente: str, ref_id: int) -> tuple[list[dict], list[dict]]:
    """
    Where a priced series is used by the benchmark, split into the
    baskets in force and the superseded ones.

    The split is the whole point. This table is VERSIONED: a rebalance
    inserts a new basket instead of editing rows, so a component dropped
    years ago still has rows here forever. Counting all of them together
    and telling the operator to "take it out of the basket" names
    something they cannot find - it is not in the current basket. What
    they can act on is the fund and the date of the version that still
    holds it.

    Returns (vigentes, historicos), each row with fondo and vigente_desde.
    """
    filas = conn.execute(
        """
        SELECT c.fondo, c.vigente_desde,
               c.vigente_desde = (SELECT MAX(v.vigente_desde)
                                  FROM benchmark_composicion v
                                  WHERE v.fondo = c.fondo) AS vigente
        FROM benchmark_composicion c
        WHERE (c.fuente = %s AND c.ref_id = %s)
           OR (c.fx_fuente = %s AND c.fx_ref_id = %s)
        ORDER BY c.fondo, c.vigente_desde
        """, (fuente, ref_id, fuente, ref_id)).fetchall()
    return ([f for f in filas if f["vigente"]],
            [f for f in filas if not f["vigente"]])


def motivo_en_uso(nombre: str, vigentes: list[dict], historicos: list[dict]) -> str:
    """The refusal, written so the next step is obvious."""
    def lista(filas):
        return ", ".join(f"fondo {f['fondo']} (desde {f['vigente_desde']})"
                         for f in filas)

    if vigentes:
        aviso = (f"'{nombre}' esta en la canasta vigente del benchmark: "
                 f"{lista(vigentes)}. Quitala de esa canasta antes de borrarla.")
        if historicos:
            aviso += (f" Tambien aparece en {len(historicos)} version(es) "
                      "anterior(es).")
        return aviso
    # Solo en versiones superadas: decirle "quitala de la canasta" seria
    # mandarlo a buscar algo que ya no esta ahi.
    return (f"'{nombre}' ya no esta en ninguna canasta vigente, pero si en "
            f"{len(historicos)} version(es) anterior(es) del benchmark: "
            f"{lista(historicos)}. Borrarla dejaria esos tramos sin poder "
            "recalcularse. Si ya no necesitas reproducirlos, borra primero "
            "esas versiones de la composicion.")


def _precios(conn, fuente: str, ref_id: int) -> dict:
    """{date: price} of one series, whole history."""
    if fuente == "bloomberg":
        filas = conn.execute(
            "SELECT fecha AS d, valor AS v FROM bloomberg_dato "
            "WHERE serie_id = %s ORDER BY fecha", (ref_id,)).fetchall()
    elif fuente == "manual":
        filas = conn.execute(
            "SELECT fecha AS d, valor AS v FROM serie_manual_dato "
            "WHERE serie_id = %s ORDER BY fecha", (ref_id,)).fetchall()
    else:
        filas = conn.execute(
            "SELECT date AS d, price AS v FROM fact_prices "
            "WHERE series_id = %s ORDER BY date", (ref_id,)).fetchall()
    return {f["d"]: float(f["v"]) for f in filas}


# ---- La matematica: encadenado con deriva ---------------------------

def encadenar(periodos: list[dict], base: float = BASE_INDICE) -> list[tuple]:
    """
    PURE chaining of a drifting (buy-and-hold) composite index.

    periodos: [{ 'desde': date, 'componentes': [
                   {'etiqueta': str, 'peso': float, 'precios': {date: px}}
               ]}], ordered by desde. Each period runs until the next
    one starts (the last runs to its components' final price).

    At each period start the index capital splits by peso into
    holdings (units = peso * I / price); between rebalances the index
    is the mark-to-market of those fixed units, so weights drift.
    Prices forward-fill inside the grid (union of component dates);
    a component with no price at or before a period start fails loud
    naming itself - a silently dropped leg would misprice the index.

    Returns [(date, level)] across all periods, base at the first
    period's start.
    """
    niveles: list[tuple] = []
    indice = base

    for k, periodo in enumerate(periodos):
        desde = periodo["desde"]
        hasta = periodos[k + 1]["desde"] if k + 1 < len(periodos) else None
        comps = periodo["componentes"]
        if not comps:
            raise ValueError(f"Composicion vacia desde {desde}.")

        # Common grid: component dates within [desde, hasta] - the next
        # rebalance date INCLUDED.
        #
        # That day belongs to the OLD basket: the new one takes over from
        # the following close. Ending the period the day before instead
        # meant the next period struck its holdings at the previous
        # close's level and priced them at the rebalance date, so the
        # index came out flat that day and the real return was lost -
        # once per rebalance, always.
        grid = sorted({d for c in comps for d in c["precios"]
                       if d >= desde and (hasta is None or d <= hasta)})
        if not grid or grid[0] != desde:
            # The period must start pricing AT its rebalance date; the
            # holdings are struck there.
            grid = [desde] + [d for d in grid if d > desde]
        if hasta is not None and grid[-1] != hasta:
            # Nobody quoted exactly on the handover date: carry the last
            # known prices to it, so the baton always changes hands there.
            grid.append(hasta)

        # Forward-filled price per component per grid date.
        def precio_en(c, d):
            px = None
            for dd in sorted(c["precios"]):
                if dd > d:
                    break
                px = c["precios"][dd]
            return px

        holdings = []
        for c in comps:
            p0 = precio_en(c, desde)
            if p0 is None or p0 <= 0:
                raise ValueError(
                    f"'{c['etiqueta']}' no tiene precio en o antes del "
                    f"rebalanceo del {desde}.")
            holdings.append((c, (c["peso"] * indice) / p0))

        for d in grid:
            valor = 0.0
            for c, unidades in holdings:
                px = precio_en(c, d)
                if px is None:
                    raise ValueError(
                        f"'{c['etiqueta']}' no tiene precio en o antes de {d}.")
                valor += unidades * px
            indice = valor
            niveles.append((d, indice))

    # A rebalance date closes one period and opens the next at the
    # same level: keep the LAST computation for a duplicated date.
    unicos: dict = {}
    for d, v in niveles:
        unicos[d] = v
    return sorted(unicos.items())


def _armar_periodos(conn, fondo: int) -> list[dict]:
    """DB compositions -> the plain structures encadenar() consumes,
    with the FX leg folded into each component's prices."""
    grupos = [g for g in leer_composiciones(fondo)]
    grupos.sort(key=lambda g: g["vigente_desde"])
    if not grupos:
        raise ValueError(f"El Fondo {fondo} no tiene ninguna composicion declarada.")

    cache: dict[tuple, dict] = {}

    def precios_de(fuente, ref_id):
        clave = (fuente, ref_id)
        if clave not in cache:
            cache[clave] = _precios(conn, fuente, ref_id)
        return cache[clave]

    periodos = []
    for g in grupos:
        comps = []
        for c in g["componentes"]:
            px = precios_de(c["fuente"], c["ref_id"])
            if c["fx_ref_id"] is not None:
                fx = precios_de(c["fx_fuente"], c["fx_ref_id"])
                # Component priced in benchmark currency: px * fx,
                # forward-filling the FX leg onto the price dates.
                fx_fechas = sorted(fx)
                convertidos, i = {}, 0
                ultimo_fx = None
                for d in sorted(px):
                    while i < len(fx_fechas) and fx_fechas[i] <= d:
                        ultimo_fx = fx[fx_fechas[i]]
                        i += 1
                    if ultimo_fx is not None:
                        convertidos[d] = px[d] * ultimo_fx
                px = convertidos
            comps.append({"etiqueta": c["etiqueta"], "peso": c["peso"],
                          "precios": px})
        periodos.append({"desde": dt.date.fromisoformat(g["vigente_desde"]),
                         "componentes": comps})
    return periodos


# ---- Regeneracion ---------------------------------------------------

def recalcular(fondo: int, log=logger.info) -> dict:
    """
    Regenerates the SPP_BENCH_F{fondo} level series in fact_prices
    from the declared compositions: base 100 at the first rebalance,
    drifting holdings between rebalances, chained across them.

    REPLACES the whole stored series (the composition is the source
    of truth - the user chose full regeneration over anchoring to the
    hand-loaded history). Runs in one transaction: a failed recalc
    leaves the previous series untouched.
    """
    fondo = int(fondo)
    with get_connection() as conn:
        serie = reg.series_map(conn).get((reg.procode_bench(fondo), "PX_LAST"))
        if serie is None:
            raise ValueError(
                f"No hay serie de benchmark registrada para el Fondo {fondo}. "
                "Corre scripts/run_sbs_valor_cuota.py --solo-registro.")
        sid = serie["series_id"]

        periodos = _armar_periodos(conn, fondo)
        log(f"Fondo {fondo}: {len(periodos)} composicion(es), desde "
            f"{periodos[0]['desde']}.")
        niveles = encadenar(periodos)
        log(f"Indice calculado: {len(niveles)} fechas "
            f"({niveles[0][0]} a {niveles[-1][0]}), nivel final "
            f"{niveles[-1][1]:,.4f}.")

        borrados = conn.execute(
            "DELETE FROM fact_prices WHERE series_id = %s", (sid,)).rowcount
        cur = conn.cursor()
        cur.executemany(UPSERT_CORRIGE,
                        [(sid, d, v, "benchmark") for d, v in niveles])
    log(f"Serie reemplazada: {borrados} niveles previos fuera, "
        f"{len(niveles)} nuevos.")
    return {"fondo": fondo, "fechas": len(niveles),
            "desde": str(niveles[0][0]), "hasta": str(niveles[-1][0]),
            "nivel_final": round(niveles[-1][1], 6),
            "reemplazados": borrados}


# ---- Catalogo para la UI --------------------------------------------

def series_disponibles(q: str = "") -> dict:
    """Pickable series for the composition editor, all three stores."""
    q = f"%{q.strip()}%" if q.strip() else "%"
    with get_connection() as conn:
        man = conn.execute(
            """
            SELECT s.serie_id, s.nombre, s.moneda, s.descripcion,
                   COUNT(d.fecha) AS puntos
            FROM serie_manual s
            LEFT JOIN serie_manual_dato d USING (serie_id)
            WHERE s.nombre ILIKE %s OR COALESCE(s.descripcion, '') ILIKE %s
            GROUP BY s.serie_id ORDER BY s.nombre LIMIT 50
            """, (q, q)).fetchall()
        bbg = conn.execute(
            """
            SELECT serie_id, ticker, campo, intervalo, descripcion
            FROM bloomberg_serie
            WHERE ticker ILIKE %s OR COALESCE(descripcion, '') ILIKE %s
            ORDER BY ticker LIMIT 50
            """, (q, q)).fetchall()
        fact = conn.execute(
            """
            SELECT sr.series_id, e.procode, e.name, sr.field, sr.source
            FROM series_registry sr
            JOIN dim_entity e ON e.entity_id = sr.entity_id
            WHERE sr.source <> %s
              AND (e.procode ILIKE %s OR COALESCE(e.name, '') ILIKE %s)
            ORDER BY e.procode LIMIT 50
            """, (reg.SOURCE_BENCH, q, q)).fetchall()
    return {
        "bloomberg": [{"ref_id": r["serie_id"],
                       "etiqueta": r["ticker"],
                       "detalle": f"{r['campo']} · {r['intervalo']}"
                                  + (f" · {r['descripcion']}" if r["descripcion"] else "")}
                      for r in bbg],
        "fact": [{"ref_id": r["series_id"],
                  "etiqueta": r["procode"],
                  "detalle": f"{r['field']} · {r['source']}"
                             + (f" · {r['name']}" if r["name"] else "")}
                 for r in fact],
        "manual": [{"ref_id": r["serie_id"],
                    "etiqueta": r["nombre"],
                    "detalle": f"{r['puntos']} punto(s)"
                               + (f" · {r['moneda']}" if r["moneda"] else "")
                               + (f" · {r['descripcion']}" if r["descripcion"] else "")}
                   for r in man],
    }
