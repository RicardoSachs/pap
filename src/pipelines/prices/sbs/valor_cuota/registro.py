# src/pipelines/prices/sbs/valor_cuota/registro.py
# ---------------------------------------------------------------
# Manual registration of valor cuota values: one AFP, one date, all
# its funds at once, in a single transaction - either every fund
# enters or none does.
#
# The monitor's wide-table semantics translate cleanly to long
# format: writing a value is an upsert on (series_id, date) with
# source='manual'; CLEARING a value is deleting that row (no NULL
# cells exist here), and a date with no values left is simply a date
# with no rows - it leaves the book by itself, no cleanup pass.
# ---------------------------------------------------------------

import datetime as dt
import logging

import pandas as pd

from src.db.connection import get_connection
from src.pipelines.prices.sbs.valor_cuota import afps as reg
from src.pipelines.prices.sbs.valor_cuota.afps import METRICA_FIELD

logger = logging.getLogger(__name__)


def registrar_valores(fecha, afp: str, valores: dict,
                      metrica: str = "valor_cuota") -> dict:
    """
    Registers or corrects ALL of one AFP's funds on one date.

    `valores` is keyed by fund type. None deletes that value; a fund
    absent from the dict is left as is. Everything happens in one
    transaction.
    """
    clave = reg.clave_de(afp)
    if not clave:
        raise ValueError(f"AFP no registrada: {afp}. Agregala en config/afps.yaml.")
    nombre = reg.nombre_de(clave)
    if metrica not in METRICA_FIELD:
        raise ValueError(f"Metrica no valida: {metrica}")
    fecha = pd.to_datetime(fecha).date()
    if fecha > dt.date.today():
        raise ValueError("La fecha no puede ser futura.")

    limpios: dict[int, float | None] = {}
    for f, v in (valores or {}).items():
        f = int(f)
        if f not in reg.fondos():
            raise ValueError(f"Tipo de fondo no valido: {f}")
        if not reg.opera(clave, f):
            raise ValueError(
                f"{nombre} no opera el Fondo {f} segun config/afps.yaml.")
        if v is None or v == "":
            limpios[f] = None
        else:
            v = float(v)
            if v <= 0:
                raise ValueError(f"El valor del Fondo {f} debe ser mayor que cero.")
            limpios[f] = v
    if not limpios:
        raise ValueError("No se recibio ningun valor.")

    field = METRICA_FIELD[metrica]

    with get_connection() as conn:
        series_map = reg.series_map(conn)

        def serie_id(fondo: int) -> int:
            s = series_map.get((reg.procode(clave, fondo), field))
            if s is None:
                raise ValueError(
                    f"No hay serie registrada para {nombre} F{fondo} / {metrica}. "
                    "Corre scripts/run_sbs_valor_cuota.py --solo-registro.")
            return s["series_id"]

        spp_ids = [s["series_id"] for s in series_map.values()
                   if s["source"] == reg.SOURCE_SBS]
        existia = _fecha_existe(conn, spp_ids, fecha)

        guardados, borrados = {}, []
        for f, v in limpios.items():
            sid = serie_id(f)
            if v is None:
                cur = conn.execute(
                    "DELETE FROM fact_prices WHERE series_id = %s AND date = %s",
                    (sid, fecha))
                if cur.rowcount > 0:
                    borrados.append(f)
            else:
                conn.execute(
                    """
                    INSERT INTO fact_prices (series_id, date, price, source)
                    VALUES (%s, %s, %s, 'manual')
                    ON CONFLICT (series_id, date) DO UPDATE SET
                        price = EXCLUDED.price, source = EXCLUDED.source
                    """,
                    (sid, fecha, v))
                guardados[f] = v

        fila_borrada = existia and not _fecha_existe(conn, spp_ids, fecha)

    logger.info(f"registro manual: {nombre} {metrica} {fecha} - "
                f"{len(guardados)} guardados, {len(borrados)} borrados.")
    return {"fecha": str(fecha), "afp": nombre, "metrica": metrica,
            "guardados": guardados, "borrados": borrados,
            "fila_nueva": not existia, "fila_borrada": fila_borrada}


def _fecha_existe(conn, series_ids: list[int], fecha) -> bool:
    """Whether any SPP fund series (any metric) has a row on that date."""
    if not series_ids:
        return False
    row = conn.execute(
        "SELECT 1 FROM fact_prices WHERE date = %s AND series_id = ANY(%s) LIMIT 1",
        (fecha, series_ids)).fetchone()
    return row is not None
