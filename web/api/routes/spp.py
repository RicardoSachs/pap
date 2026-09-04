
# web/api/routes/spp.py
# ---------------------------------------------------------------------------
# /api/spp : read-only routes of the SPP valor cuota tablero (config, estado,
# series, ventanas, posiciones, libro, CSV export). Write operations (manual
# registry, uploads, extraction trigger) stay CLI/scheduler-side in phase 1.
#
# URL parameters come from the browser and can be anything: readers clamp
# integers and validate metrics against the allowlist so a ?limite=-1 or a
# ?meses=abc never becomes a 500 (df.tail(-1) would return almost the whole
# book - the opposite of a limit).
# ---------------------------------------------------------------------------
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Query, Response

from web.api.services import spp as svc

router = APIRouter(prefix="/api/spp", tags=["spp"])


def _entero(crudo, por_defecto: int, minimo: int, maximo: int) -> int:
    try:
        v = int(str(crudo).strip())
    except (TypeError, ValueError):
        return por_defecto
    return max(minimo, min(maximo, v))


def _fecha(crudo) -> str | None:
    """
    ISO date from the URL, or None. Same philosophy as _entero: malformed
    browser input is treated as absent, never forwarded into a ::date cast
    or pd.to_datetime where it would become a 500.
    """
    try:
        return date.fromisoformat(str(crudo).strip()).isoformat() if crudo else None
    except ValueError:
        return None


def _nombre_seguro(nombre: str, por_defecto: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9_.-]", "_", str(nombre or "")).strip("._-")
    return limpio[:120] or por_defecto


@router.get("/config")
def get_config() -> dict:
    return svc.config()


@router.get("/estado")
def get_estado() -> dict:
    return svc.estado()


@router.get("/serie")
def get_serie(
    fondo: str = Query("2"),
    afps: str = Query("", description="comma-separated display names"),
    metrica: str = Query("valor_cuota"),
    desde: str | None = Query(None),
    hasta: str | None = Query(None),
) -> dict:
    pedidas = [a.strip().upper() for a in afps.split(",") if a.strip()]
    return svc.serie(_entero(fondo, 2, 0, 99), pedidas, metrica,
                     _fecha(desde), _fecha(hasta))


@router.get("/ventanas")
def get_ventanas(fecha: str | None = Query(None),
                 metrica: str = Query("valor_cuota")) -> dict:
    return svc.ventanas(_fecha(fecha), metrica)


@router.get("/posiciones")
def get_posiciones(fecha: str | None = Query(None),
                   meses: str = Query("24"),
                   metrica: str = Query("valor_cuota")) -> dict:
    return svc.posiciones(_fecha(fecha), _entero(meses, 24, 1, 120), metrica)


@router.get("/tabla")
def get_tabla(limite: str = Query("60"),
              metrica: str = Query("valor_cuota"),
              fondo: str = Query("todos")) -> dict:
    crudo = limite.strip().lower()
    lim = None if crudo in ("todas", "todos") else _entero(crudo, 60, 1, 5000)
    return svc.tabla(lim, metrica.strip(), fondo.strip().lower())


@router.get("/exportar")
def get_exportar(metrica: str = Query("todas"),
                 fondo: str = Query("todos"),
                 limite: str = Query(""),
                 desde: str | None = Query(None),
                 hasta: str | None = Query(None)) -> Response:
    crudo = limite.strip().lower()
    lim = None if crudo in ("", "todas", "todos") else _entero(crudo, 60, 1, 5000)
    fondo_arg = fondo.strip().lower()

    partes = ["spp",
              f"F{fondo_arg}" if fondo_arg != "todos" else "todos_los_fondos",
              metrica.strip(),
              f"{lim}filas" if lim else "serie_completa"]
    nombre = _nombre_seguro("_".join(partes), "spp")

    datos = svc.exportar_csv(metrica.strip(), fondo_arg, lim,
                             _fecha(desde), _fecha(hasta))
    return Response(
        content=datos, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'})
