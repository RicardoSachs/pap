# src/pipelines/prices/sbs/valor_cuota/benchmark.py
# ---------------------------------------------------------------
# Benchmark per fund type: reading, manual registration and file
# import. Ported from the monitor onto the long model.
#
# There is ONE benchmark per fund type, common to all AFPs, and only
# for the funds config/afps.yaml declares (Fund 0 is capital-
# protected and has no market comparable). The SBS does not publish
# it: it enters by file or by hand, as series SPP_BENCH_F{n} /
# PX_LAST / source 'benchmark' in fact_prices.
#
# File loads NEVER delete: new dates insert, existing values are only
# replaced with refrescar=True, and an empty cell in the file is a
# row that never reaches the loader. Deleting is always a manual act
# in the registration form.
#
# Canonical file format - one row per date, one column per fund:
#     fecha,fondo1,fondo2,fondo3
#     2026-08-20,128.4471000,142.8830000,151.2094000
# Also accepted without configuring anything: separator , ; or tab,
# decimal comma or point, dd/mm/yyyy dates, headers written as f1 /
# fondo 1 / benchmark 1 / bench_f1, missing columns, and the long
# format fecha,fondo,valor.
# ---------------------------------------------------------------

import datetime as dt
import io
import logging

import pandas as pd

from src.db.connection import get_connection
from src.pipelines.prices.sbs.valor_cuota import afps as reg
from src.pipelines.prices.sbs.valor_cuota.loader import (
    UPSERT_CORRIGE, UPSERT_NADA)
from src.pipelines.prices.sbs.valor_cuota.registro import (
    escribir_fecha, limpiar_valores, validar_fecha)
from src.shared import tabular

logger = logging.getLogger(__name__)


def columna_bench(fondo: int) -> str:
    return f"bench_f{int(fondo)}"


def _series_bench(conn) -> dict[int, int]:
    """fondo -> series_id for the benchmark series."""
    out = {}
    for (procode, field), s in reg.series_map(conn).items():
        if field == "PX_LAST" and s["source"] == reg.SOURCE_BENCH:
            try:
                out[int(procode.rsplit("_F", 1)[1])] = s["series_id"]
            except (IndexError, ValueError):
                continue
    return out


# ---- Lectura --------------------------------------------------------

def leer_bench(desde=None, hasta=None) -> pd.DataFrame:
    """Wide DataFrame: fecha x bench_f{n}, ascending by date."""
    sql = """
        SELECT e.procode, fp.date, fp.price
        FROM fact_prices fp
        JOIN series_registry sr ON sr.series_id = fp.series_id
        JOIN dim_entity e ON e.entity_id = sr.entity_id
        WHERE e.procode LIKE 'SPP\\_BENCH\\_%%' AND sr.source = %s
    """
    params: list = [reg.SOURCE_BENCH]
    if desde:
        sql += " AND fp.date >= %s::date"
        params.append(str(pd.to_datetime(desde).date()))
    if hasta:
        sql += " AND fp.date <= %s::date"
        params.append(str(pd.to_datetime(hasta).date()))
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    if not rows:
        return pd.DataFrame(columns=["fecha"])
    df = pd.DataFrame([
        {"fecha": r["date"],
         "col": columna_bench(int(r["procode"].rsplit("_F", 1)[1])),
         "valor": r["price"]}
        for r in rows
    ])
    df = (df.pivot_table(index="fecha", columns="col", values="valor",
                         aggfunc="last")
          .sort_index().reset_index())
    df.columns.name = None
    return df


def valores_de(fecha) -> dict:
    """{fondo: valor|None} on one date, plus whether the date exists."""
    fecha = pd.to_datetime(fecha).date()
    with get_connection() as conn:
        series = _series_bench(conn)
        ids = list(series.values())
        rows = conn.execute(
            "SELECT series_id, price FROM fact_prices "
            "WHERE date = %s AND series_id = ANY(%s)",
            (fecha, ids)).fetchall() if ids else []
    por_serie = {r["series_id"]: float(r["price"]) for r in rows}
    valores = {f: por_serie.get(sid) for f, sid in series.items()}
    return {"fecha": str(fecha), "valores": valores,
            "existe": any(v is not None for v in valores.values())}


def estado_benchmark() -> dict:
    """Coverage summary, in the same language as the rest of the tablero."""
    df = leer_bench()
    fondos_b = reg.fondos_benchmark()
    base = {"tabla": "fact_prices", "fondos": fondos_b,
            "filas": len(df), "desde": None, "hasta": None, "series": []}
    if df.empty:
        return base
    base.update(desde=str(df["fecha"].min()), hasta=str(df["fecha"].max()))
    for f in fondos_b:
        col = columna_bench(f)
        if col not in df.columns:
            base["series"].append({"fondo": f, "puntos": 0, "valor": None,
                                   "fecha": None, "inicio": None, "var_bps": None})
            continue
        s = df[["fecha", col]].dropna(subset=[col])
        if s.empty:
            base["series"].append({"fondo": f, "puntos": 0, "valor": None,
                                   "fecha": None, "inicio": None, "var_bps": None})
            continue
        ultimo = float(s[col].iloc[-1])
        previo = float(s[col].iloc[-2]) if len(s) > 1 else None
        base["series"].append({
            "fondo": f, "puntos": int(len(s)), "valor": ultimo,
            "fecha": str(s["fecha"].iloc[-1]), "inicio": str(s["fecha"].iloc[0]),
            "var_bps": None if not previo else round((ultimo / previo - 1) * 10000, 1)})
    return base


# ---- Registro manual ------------------------------------------------

def registrar_benchmark(fecha, valores: dict) -> dict:
    """
    Manual registration of one date, all funds at once. Same grammar as
    the valor cuota form - the shared limpiar_valores/escribir_fecha in
    registro.py carry the rules: None deletes that value, an absent
    fund is left alone, and a date with nothing left leaves the table
    on its own.
    """
    fecha = validar_fecha(fecha)
    fondos_b = reg.fondos_benchmark()

    def validar_fondo(f: int) -> None:
        if f not in fondos_b:
            raise ValueError(
                f"El Fondo {f} no lleva benchmark. Solo "
                + ", ".join(f"Fondo {x}" for x in fondos_b) + ".")

    limpios = limpiar_valores(valores, validar_fondo, "El benchmark")

    with get_connection() as conn:
        series = _series_bench(conn)
        faltan = [f for f in limpios if f not in series]
        if faltan:
            raise ValueError(
                f"No hay serie de benchmark registrada para Fondo {faltan}. "
                "Corre scripts/run_sbs_valor_cuota.py --solo-registro.")
        resultado = escribir_fecha(conn, fecha, limpios,
                                   serie_de=lambda f: series[f],
                                   ids_fecha=list(series.values()))
    return {"fecha": str(fecha), **resultado}


# ---- Carga por archivo ----------------------------------------------

def _fondo_de_cabecera(texto: str):
    """Fund number a header names, or None."""
    import re
    c = tabular.clave_col(texto)
    m = re.fullmatch(r"(?:bench(?:mark)?)?(?:fondo|f)?([0-9]{1,2})", c)
    return int(m.group(1)) if m else None


def _fila_cabecera(filas: list, limite: int = 12):
    """First row that names the date column."""
    return tabular.fila_cabecera(
        filas, lambda c: tabular.clave_col(c) in ("fecha", "date", "dia", "periodo"),
        limite)


def leer_archivo_benchmark(datos, hoja=None) -> dict:
    """
    Excel or CSV -> benchmark DataFrame, without touching the DB.
    Returns the frame plus everything that was deduced and everything
    that was discarded, so it can be shown before saving. Format is
    recognized by content, not extension.
    """
    fondos_b = reg.fondos_benchmark()
    if tabular.es_excel(datos):
        filas, nombre_hoja, hojas = tabular.filas_de_excel(datos, hoja)
        origen, sep = "excel", None
        # Excel numbers arrive typed; text-formatted cells are still
        # ambiguous, so the decimal style is deduced from the sheet.
        import re
        textos = [str(c).strip() for f in filas for c in f
                  if isinstance(c, str) and re.fullmatch(r"-?[\d.,\s]+", c.strip())
                  and re.search(r"\d", c)]
        coma_decimal = tabular.estilo_decimal(textos)
    else:
        filas, sep, coma_decimal = tabular.filas_de_csv(datos)
        origen, nombre_hoja, hojas = "csv", None, []

    avisos, omitidas = [], []
    icab = _fila_cabecera(filas)
    if icab is None:
        vistas = [str(c) for f in filas[:3] for c in f if str(c).strip()
                  and str(c) != "nan"]
        raise ValueError(
            "Falta la columna 'fecha'. No se encontro una fila de encabezados en "
            f"las primeras filas del archivo. Se leyo: {', '.join(vistas[:10]) or 'nada'}")
    if icab:
        avisos.append(f"Los encabezados estaban en la fila {icab + 1}; "
                      "lo anterior se ignoro.")

    cabecera = tabular.limpiar_cabecera(filas[icab])
    claves = [tabular.clave_col(c) for c in cabecera]
    icol_fecha = next(i for i, c in enumerate(claves)
                      if c in ("fecha", "date", "dia", "periodo"))

    # Long format: fecha, fondo, valor.
    i_fondo = claves.index("fondo") if "fondo" in claves else None
    i_valor = next((i for i, c in enumerate(claves)
                    if c in ("valor", "benchmark", "bench", "indice", "nivel")), None)
    largo = i_fondo is not None and i_valor is not None

    porcol = {}
    if not largo:
        for i, c in enumerate(cabecera):
            if i == icol_fecha or not c:
                continue
            f = _fondo_de_cabecera(c)
            if f is None:
                avisos.append(f"Se ignoro la columna '{c}': no nombra ningun fondo.")
            elif f not in fondos_b:
                avisos.append(f"Se ignoro la columna '{c}': el Fondo {f} no lleva "
                              "benchmark.")
            else:
                porcol[i] = f
        if not porcol:
            raise ValueError(
                "Ninguna columna nombra un fondo con benchmark. Se esperaba "
                + ", ".join(f"fondo{f}" for f in fondos_b)
                + ". La cabecera leida fue: "
                + ", ".join(c for c in cabecera if c))

    hoy = dt.date.today()
    por_fecha: dict[dt.date, dict[int, float]] = {}
    repetidas = 0

    def vacia(v):
        return v is None or (isinstance(v, float) and v != v) or str(v).strip() == ""

    for n, fila in enumerate(filas[icab + 1:], start=icab + 2):
        if all(vacia(x) for x in fila):
            continue
        if len(fila) <= icol_fecha:
            omitidas.append({"linea": n, "motivo": "fila incompleta"})
            continue
        f = tabular.fecha_flexible(fila[icol_fecha])
        if f is None:
            omitidas.append({"linea": n,
                             "motivo": f"fecha ilegible: {str(fila[icol_fecha])[:24]}"})
            continue
        if f > hoy:
            omitidas.append({"linea": n, "motivo": f"fecha futura: {f}"})
            continue

        if largo:
            try:
                num = int(float(str(fila[i_fondo]).strip()))
            except (ValueError, IndexError, TypeError):
                omitidas.append({"linea": n, "motivo": "fondo ilegible"})
                continue
            if num not in fondos_b:
                omitidas.append({"linea": n,
                                 "motivo": f"el Fondo {num} no lleva benchmark"})
                continue
            crudo = fila[i_valor] if len(fila) > i_valor else None
            pares = [(num, tabular.num_flexible(crudo, coma_decimal))]
        else:
            pares = [(fo, tabular.num_flexible(fila[i] if len(fila) > i else None,
                                               coma_decimal))
                     for i, fo in porcol.items()]

        utiles = {}
        for fo, v in pares:
            if v is None:
                continue
            if v <= 0:
                omitidas.append({"linea": n,
                                 "motivo": f"fondo{fo} no es positivo: {v}"})
                continue
            utiles[fo] = v
        if not utiles:
            continue
        # In long format a date takes one row per fund: that is NOT a
        # repeat. A repeat is the same fund appearing twice.
        ya = por_fecha.setdefault(f, {})
        repetidas += sum(1 for fo in utiles if fo in ya)
        ya.update(utiles)

    if repetidas:
        avisos.append(f"{repetidas} valor(es) venian repetidos para la misma "
                      "fecha y fondo; manda la ultima lectura.")
    if not por_fecha:
        raise ValueError("No se pudo leer ningun valor valido. Revisa el formato: "
                         "se esperaba 'fecha' y una columna por fondo.")

    df = (pd.DataFrame([{"fecha": f, **{columna_bench(fo): v for fo, v in vals.items()}}
                        for f, vals in por_fecha.items()])
          .sort_values("fecha").reset_index(drop=True))
    cols = [columna_bench(f) for f in fondos_b if columna_bench(f) in df.columns]
    df = df[["fecha"] + cols]

    salida = {"df": df,
              "muestra": _muestra(df, cols),
              "origen": origen,
              "formato": "largo" if largo else "ancho",
              "columnas": cols, "filas": len(df),
              "desde": str(df["fecha"].min()), "hasta": str(df["fecha"].max()),
              "celdas": int(df[cols].notna().sum().sum()),
              "omitidas": omitidas[:25], "total_omitidas": len(omitidas),
              "avisos": avisos}
    if origen == "excel":
        salida["hoja"] = nombre_hoja
        salida["hojas"] = hojas
    else:
        salida["separador"] = {"\t": "tabulacion"}.get(sep, sep)
        salida["decimal"] = "coma" if coma_decimal else "punto"
    return salida


def _muestra(df: pd.DataFrame, cols: list, filas: int = 15) -> dict:
    """Last rows read, most recent first - the visual half of the review."""
    if df.empty or not cols:
        return {"columnas": [], "filas": [], "total": 0}
    ultimas = df.sort_values("fecha", ascending=False).head(filas)
    return {
        "columnas": ["Fondo " + c.split("_f")[1] for c in cols],
        "filas": [[str(r["fecha"])] +
                  [None if pd.isna(r[c]) else float(r[c]) for c in cols]
                  for _, r in ultimas.iterrows()],
        "total": int(len(df)),
    }


def guardar_bench(df: pd.DataFrame, fuente: str = "csv",
                  refrescar: bool = False) -> dict:
    """
    Writes a benchmark frame without ever deleting. New (fund, date)
    rows insert; existing ones are only replaced with refrescar=True.
    An empty cell in the source is a row that never reaches here.
    """
    if df.empty:
        return {"nuevas": 0, "actualizadas": 0, "celdas": 0, "sin_cambio": 0}

    with get_connection() as conn:
        series = _series_bench(conn)
        ids = list(series.values())
        # Existing values, not just dates: under refrescar the DO UPDATE
        # rowcount is 1 for every row, so honest nuevas/actualizadas/
        # sin_cambio counts require comparing against what is stored -
        # the whole point of the review-then-load audit. An identical
        # value is skipped entirely (no write, no count).
        existentes: dict[tuple, float] = {}
        if ids:
            for r in conn.execute(
                    "SELECT series_id, date, price FROM fact_prices "
                    "WHERE series_id = ANY(%s)", (ids,)).fetchall():
                existentes[(r["series_id"], r["date"])] = float(r["price"])
        fechas_previas = {d for (_, d) in existentes}

        nuevas_fechas: set = set()
        celdas = celdas_conocidas = sin_cambio = 0
        for _, fila in df.iterrows():
            fecha = pd.to_datetime(fila["fecha"]).date()
            for f, sid in series.items():
                col = columna_bench(f)
                v = fila.get(col)
                if v is None or pd.isna(v):
                    continue
                v = float(v)
                previo = existentes.get((sid, fecha))
                if previo is None:
                    conn.execute(UPSERT_NADA, (sid, fecha, v, fuente))
                    celdas += 1
                    if fecha not in fechas_previas:
                        nuevas_fechas.add(fecha)
                elif refrescar and abs(previo - v) > 1e-9:
                    conn.execute(UPSERT_CORRIGE, (sid, fecha, v, fuente))
                    celdas += 1
                    celdas_conocidas += 1
                else:
                    sin_cambio += 1

    res = {"nuevas": len(nuevas_fechas),
           "actualizadas": celdas_conocidas,
           "celdas": celdas, "sin_cambio": sin_cambio}
    logger.info(f"benchmark: {res['celdas']} celdas escritas, "
                f"{res['nuevas']} fechas nuevas, {res['sin_cambio']} sin cambio.")
    return res


def importar_benchmark(datos, refrescar: bool = False, hoja=None) -> dict:
    """Reads the file and saves it. Returns both halves' detail."""
    lectura = leer_archivo_benchmark(datos, hoja=hoja)
    guardado = guardar_bench(lectura["df"], fuente=lectura["origen"],
                             refrescar=refrescar)
    lectura.pop("df")
    guardado["celdas_escritas"] = guardado.pop("celdas", 0)
    lectura.update(guardado)
    lectura["refrescar"] = bool(refrescar)
    return lectura


def plantilla_benchmark(filas: int = 10) -> bytes:
    """Empty Excel with the right header and the last business days."""
    dias = list(pd.bdate_range(end=dt.date.today(), periods=max(1, filas)).date)
    datos = {"fecha": dias}
    for f in reg.fondos_benchmark():
        datos[f"fondo{f}"] = [None] * len(dias)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(datos).to_excel(w, sheet_name="Benchmark", index=False)
    return buf.getvalue()


def exportar_benchmark_datos(desde=None, hasta=None) -> bytes:
    """
    The benchmark as an in-memory Excel, in the SAME format it imports:
    what you download can be re-uploaded untouched, which is the
    simplest way to correct a stretch or move the series elsewhere.
    """
    df = leer_bench(desde, hasta)
    fondos_b = reg.fondos_benchmark()
    cols = [columna_bench(f) for f in fondos_b if columna_bench(f) in df.columns]
    if df.empty:
        df = pd.DataFrame(columns=["fecha"] + [columna_bench(f) for f in fondos_b])
        cols = [columna_bench(f) for f in fondos_b]
    df = df[["fecha"] + cols].rename(
        columns={columna_bench(f): f"fondo{f}" for f in fondos_b})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.sort_values("fecha", ascending=False).to_excel(
            w, sheet_name="Benchmark", index=False)
    return buf.getvalue()
