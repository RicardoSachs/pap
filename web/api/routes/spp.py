# web/api/routes/spp.py
# ---------------------------------------------------------------------------
# /api/spp : read routes of the SPP valor cuota tablero (config, status,
# series, windows, positions, book table, CSV export). Writes live in
# spp_write.py.
#
# URL parameters come from the browser and can be anything: integers are
# clamped by Query bounds and metrics are validated against the allowlist,
# so a ?limit=-1 or a ?months=abc never becomes a 500.
# ---------------------------------------------------------------------------
from __future__ import annotations

import re

from fastapi import APIRouter, Query, Response

from web.api.routes._spp_common import iso_date
from web.api.services import spp as svc

router = APIRouter(prefix="/api/spp", tags=["spp"])


def _safe_name(name: str, default: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "")).strip("._-")
    return clean[:120] or default


@router.get("/config")
def get_config() -> dict:
    return svc.config()


@router.get("/status")
def get_status() -> dict:
    return svc.status()


@router.get("/scrape/last")
def get_last_scrape() -> dict:
    """The last unattended scrape, from job_runs (the scheduler job acquire_spp)."""
    return {"run": svc.last_scheduled_run()}


@router.get("/series")
def get_series(
    fund: int = Query(2, ge=0, le=99),
    afps: str = Query("", description="comma-separated display names"),
    metric: str = Query("valor_cuota"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> dict:
    requested = [a.strip().upper() for a in afps.split(",") if a.strip()]
    return svc.series(fund, requested, metric, iso_date(date_from), iso_date(date_to))


@router.get("/windows")
def get_windows(date: str | None = Query(None),
                metric: str = Query("valor_cuota")) -> dict:
    return svc.windows(iso_date(date), metric)


@router.get("/positions")
def get_positions(date: str | None = Query(None),
                  months: int = Query(24, ge=1, le=120),
                  metric: str = Query("valor_cuota")) -> dict:
    return svc.positions(iso_date(date), months, metric)


@router.get("/table")
def get_table(limit: int = Query(60, ge=0, le=20000, description="0 = the whole book"),
              metric: str = Query("valor_cuota"),
              fund: str = Query("all")) -> dict:
    return svc.table(limit or None, metric.strip(), fund.strip().lower())


@router.get("/export")
def get_export(metric: str = Query("all"),
               fund: str = Query("all"),
               limit: int = Query(0, ge=0, le=20000, description="0 = the whole book"),
               date_from: str | None = Query(None, alias="from"),
               date_to: str | None = Query(None, alias="to")) -> Response:
    fund_arg = fund.strip().lower()
    parts = ["spp",
             f"F{fund_arg}" if fund_arg != "all" else "all_funds",
             metric.strip(),
             f"{limit}rows" if limit else "full_series"]
    name = _safe_name("_".join(parts), "spp")
    data = svc.export_csv(metric.strip(), fund_arg, limit or None,
                          iso_date(date_from), iso_date(date_to))
    return Response(
        content=data, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
