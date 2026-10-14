# web/api/routes/spp_write.py
# ---------------------------------------------------------------------------
# /api/spp : write routes of the SPP tablero. Everything that reaches the
# database through here either validates before writing or runs in the
# background task that leaves a log. The historical load goes in two
# deliberate steps - review, then load - because writing thousands of
# dates without having seen what they bring is the kind of operation one
# only regrets afterwards.
#
# Errors are HTTPException with the reason in `detail`: 400 for a request
# the pipeline refuses, 409 when the task slot is busy, 410 for an expired
# upload token, 503 when this machine may not scrape.
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.configs.machine_config import machine_id, scraper_enabled
from src.pipelines.prices.sbs.valor_cuota.manual import register_values
from src.pipelines.prices.sbs.valor_cuota.run import (
    LOAD_MODES, load_history, review_history, run_daily)
from web.api.routes._spp_common import read_upload
from web.api.services import spp_task as task

router = APIRouter(prefix="/api/spp", tags=["spp-write"])


class ScrapeRequest(BaseModel):
    force: bool = False


class ManualValues(BaseModel):
    """One AFP on one date, all its funds at once. `values` is keyed by
    fund: {"0": 15.87, "2": null} - null deletes that value, an absent
    fund is left as it is."""
    date: str
    afp: str
    metric: str = "valor_cuota"
    values: dict[str, float | None]


class HistoryLoad(BaseModel):
    token: str
    mode: str = "missing"


def _launch(action: str, func) -> dict:
    try:
        task.launch(action, func)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"ok": True, "action": action}


# ---- The background task ----------------------------------------------------
# One task slot for the whole SPP tablero (SBS scrape, history load,
# benchmark materialization); the frontend hook polls this.

@router.get("/task")
def get_task() -> dict:
    return task.status()


@router.post("/scrape")
def post_scrape(body: ScrapeRequest | None = None) -> dict:
    """Launches the SBS scrape in the background task (opens Chrome)."""
    if not scraper_enabled():
        raise HTTPException(
            status_code=503,
            detail=f"El scraper no esta habilitado en esta maquina ({machine_id()}). "
                   "Pon SCRAPER_ENABLED=true en el archivo .env del proyecto y "
                   "reinicia la API (la configuracion se cachea al arrancar).")
    force = bool(body and body.force)
    return _launch("extraccion SBS", task.with_log(run_daily, force=force))


# ---- Manual registration -----------------------------------------------------

@router.post("/values")
def post_values(body: ManualValues) -> dict:
    try:
        result = register_values(body.date, body.afp, body.values, body.metric)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"ok": True, "result": result}


# ---- Historical load (two steps) ---------------------------------------------

@router.post("/history/review")
async def post_history_review(file: UploadFile = File(...)) -> dict:
    """
    First half: review the Excel without writing. The file is kept in
    memory under a token so confirming loads exactly what was reviewed.
    """
    raw = await read_upload(file)
    try:
        report = review_history(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    token = task.store_upload(raw, file.filename)
    report["file"] = file.filename
    report["bytes"] = len(raw)
    return {"ok": True, "token": token, "report": report}


@router.post("/history/load")
def post_history_load(body: HistoryLoad) -> dict:
    """Second half: write the reviewed file, in the chosen mode."""
    if body.mode not in LOAD_MODES:
        raise HTTPException(status_code=400, detail=f"Modo no valido: {body.mode}")
    stored = task.read_upload(body.token)
    if stored is None:
        raise HTTPException(
            status_code=410,
            detail="El archivo revisado ya no esta en memoria. Vuelve a subirlo.")
    return _launch(f"carga historica ({body.mode})",
                   task.with_log(load_history, content=stored["data"], mode=body.mode))
