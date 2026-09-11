# src/pipelines/prices/sbs/valor_cuota/benchmark.py
# ---------------------------------------------------------------
# Benchmark per fund type: READ side only.
#
# There is ONE benchmark per fund type, common to all AFPs, and only
# for the funds config/afps.yaml declares (Fund 0 is capital-
# protected and has no market comparable). Its levels live as series
# SPP_BENCH_F{n} / PX_LAST / source 'benchmark' in fact_prices, and
# since the 2026-09 redesign they are written by exactly ONE hand:
# the recalculation in benchmark_composicion.py (composition of
# priced components -> chained index). The manual and file loaders
# that used to live here are gone on purpose - levels are calculated,
# never keyed in; what IS keyed in is component prices, in
# src/pipelines/prices/manual/series.py.
#
# This module keeps the reading: the wide frame the tablero charts,
# the coverage summary, and the Excel export of the stored series.
# ---------------------------------------------------------------

import io
import logging

import pandas as pd

from src.db.connection import get_connection
from src.pipelines.prices.sbs.valor_cuota import afps as reg

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


# ---- Export ---------------------------------------------------------

def exportar_benchmark_datos(desde=None, hasta=None) -> bytes:
    """The calculated benchmark as an in-memory Excel, one column per
    fund, most recent first."""
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
