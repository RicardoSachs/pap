
# web/api/routes/spp_carga.py
# ---------------------------------------------------------------------------
# /api/spp : write routes of the SPP tablero (phase 2). Everything that
# reaches the database through here either validates before writing or runs
# in the background task that leaves a trail. The historical load goes in two
# deliberate steps - review, then load - because writing thousands of dates
# without having seen what they bring is the kind of operation one only
# regrets afterwards.
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import logging
import os
import subprocess

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse

from src.configs.machine_config import machine_id, scraper_enabled
from src.pipelines.prices.sbs.valor_cuota import benchmark as bench
from src.pipelines.prices.sbs.valor_cuota.registro import registrar_valores
from src.pipelines.prices.sbs.valor_cuota.run import (
    MODOS_CARGA, cargar_historico, revisar_historico, run_daily, ultima_corrida)
from web.api.routes._spp_comun import XLSX, es_si, fecha_iso, leer_archivo
from web.api.services.spp_tarea import (
    TAREA_WINDOWS, con_bitacora, guardar_subida, lanzar, leer_subida)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/spp", tags=["spp-carga"])


# ---- Extraccion -----------------------------------------------------------

@router.post("/extraer")
def post_extraer(datos: dict | None = None) -> JSONResponse:
    """Launches the SBS scrape in the background task (opens Chrome)."""
    if not scraper_enabled():
        return JSONResponse(
            {"ok": False, "motivo":
             f"El scraper no esta habilitado en esta maquina ({machine_id()}). "
             "Activa scraper_enabled: true en "
             "%USERPROFILE%\\Documents\\Tools\\config\\market_data_config.yaml "
             "y reinicia la API (la configuracion se cachea al arrancar)."},
            status_code=503)
    refrescar = bool((datos or {}).get("refrescar"))
    ok, motivo = lanzar("extraccion SBS",
                        con_bitacora(run_daily, refresh=refrescar))
    return JSONResponse({"ok": ok, "motivo": motivo},
                        status_code=200 if ok else 409)


@router.get("/programado")
def get_programado() -> dict:
    """What Windows says about the scheduled task, and how the last
    unattended run went."""
    return {"tarea": _tarea_windows(), "ultima": ultima_corrida(),
            "nombre": TAREA_WINDOWS}


def _tarea_windows() -> dict:
    """
    Queried via PowerShell, not schtasks: Get-ScheduledTaskInfo property
    names are stable, while schtasks output is translated per system
    language.
    """
    if os.name != "nt":
        return {"disponible": False, "motivo": "Solo en Windows."}
    guion = (
        f"$t = Get-ScheduledTask -TaskName '{TAREA_WINDOWS}' -ErrorAction SilentlyContinue; "
        "if (-not $t) { '{\"registrada\":false}' } else { "
        "$i = $t | Get-ScheduledTaskInfo; "
        "[pscustomobject]@{ registrada=$true; estado=[string]$t.State; "
        "  proxima=[string]$i.NextRunTime; ultima=[string]$i.LastRunTime; "
        "  resultado=$i.LastTaskResult; omitidas=$i.NumberOfMissedRuns; "
        "  disparo=[string]($t.Triggers | ForEach-Object { $_.StartBoundary }) "
        "} | ConvertTo-Json -Compress }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", guion],
                           capture_output=True, text=True, timeout=25)
        datos = json.loads((r.stdout or "").strip() or '{"registrada":false}')
        datos["disponible"] = True
        return datos
    except Exception as exc:
        return {"disponible": False, "motivo": str(exc)[:200]}


# ---- Registro manual ------------------------------------------------------

@router.post("/valor")
def post_valor(datos: dict) -> JSONResponse:
    """
    Manual registration of one AFP on one date, all its funds at once.
    `valores` is keyed by fund: {"0": 15.87, "2": null, ...} - null
    deletes that value, an absent fund is left as is.
    """
    try:
        resultado = registrar_valores(
            datos.get("fecha"), datos.get("afp"),
            datos.get("valores") or {},
            datos.get("metrica") or "valor_cuota")
        return JSONResponse({"ok": True, "resultado": resultado})
    except (ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("registro manual")
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=500)


# ---- Carga historica (dos pasos) ------------------------------------------

@router.post("/historico/revisar")
async def post_historico_revisar(archivo: UploadFile = File(...)) -> JSONResponse:
    """
    First half: review the Excel without writing. The file is kept in
    memory under a vale so confirming loads exactly what was reviewed.
    """
    crudo, error = await leer_archivo(archivo)
    if error:
        return error
    try:
        informe = revisar_historico(crudo)
    except (ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("revision del historico")
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=500)

    vale = guardar_subida(crudo, archivo.filename)
    informe["archivo"] = archivo.filename
    informe["bytes"] = len(crudo)
    return JSONResponse({"ok": True, "vale": vale, "informe": informe})


@router.post("/historico/cargar")
def post_historico_cargar(datos: dict) -> JSONResponse:
    """Second half: write the reviewed file, in the chosen mode."""
    vale = datos.get("vale")
    modo = (datos.get("modo") or "faltantes").strip()
    if modo not in MODOS_CARGA:
        return JSONResponse({"ok": False, "motivo": f"Modo no valido: {modo}"},
                            status_code=400)
    guardado = leer_subida(vale)
    if guardado is None:
        return JSONResponse(
            {"ok": False, "motivo": "El archivo revisado ya no esta en memoria. "
                                    "Vuelve a subirlo."},
            status_code=410)

    ok, motivo = lanzar(f"carga historica ({modo})",
                        con_bitacora(cargar_historico,
                                     contenido=guardado["datos"], modo=modo))
    return JSONResponse({"ok": ok, "motivo": motivo},
                        status_code=200 if ok else 409)


# ---- Benchmark ------------------------------------------------------------

@router.get("/benchmark")
def get_benchmark() -> dict:
    return {"estado": bench.estado_benchmark()}


@router.get("/benchmark/fecha")
def get_benchmark_fecha(fecha: str) -> JSONResponse:
    try:
        return JSONResponse(bench.valores_de(fecha))
    except (ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=400)


@router.post("/benchmark/valor")
def post_benchmark_valor(datos: dict) -> JSONResponse:
    try:
        resultado = bench.registrar_benchmark(datos.get("fecha"),
                                              datos.get("valores") or {})
        return JSONResponse({"ok": True, "resultado": resultado})
    except (ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("registro de benchmark")
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=500)


@router.post("/benchmark/archivo")
async def post_benchmark_archivo(archivo: UploadFile = File(...),
                                 revisar: str = Form(""),
                                 refrescar: str = Form("")) -> JSONResponse:
    """
    Benchmark load by file. With revisar=1 only reports what was read;
    nothing reaches the base without having been shown first.
    """
    crudo, error = await leer_archivo(archivo)
    if error:
        return error
    solo_revisar = es_si(revisar)
    con_refresco = es_si(refrescar)
    try:
        if solo_revisar:
            informe = bench.leer_archivo_benchmark(crudo)
            informe.pop("df", None)
        else:
            informe = bench.importar_benchmark(crudo, refrescar=con_refresco)
        informe["archivo"] = archivo.filename
        return JSONResponse({"ok": True, "revisado": solo_revisar,
                             "informe": informe})
    except (ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("carga de benchmark")
        return JSONResponse({"ok": False, "motivo": str(exc)}, status_code=500)


@router.get("/benchmark/plantilla")
def get_benchmark_plantilla() -> Response:
    return Response(bench.plantilla_benchmark(), media_type=XLSX,
                    headers={"Content-Disposition":
                             "attachment; filename=plantilla_benchmark.xlsx"})


@router.get("/benchmark/exportar")
def get_benchmark_exportar(desde: str | None = None,
                           hasta: str | None = None) -> Response:
    return Response(bench.exportar_benchmark_datos(fecha_iso(desde), fecha_iso(hasta)),
                    media_type=XLSX,
                    headers={"Content-Disposition":
                             "attachment; filename=benchmark_diario.xlsx"})
