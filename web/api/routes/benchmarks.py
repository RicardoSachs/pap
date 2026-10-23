# web/api/routes/benchmarks.py
# ---------------------------------------------------------------------------
# /api/benchmarks : the composite indices (benchmarks, targets) - which
# exist, their versioned definitions, the changelog, the series catalog a
# basket draws from (every price source, found by procode, name, ticker or
# ISIN, with coverage). The writes - declare and assign, append a version,
# materialize, register a ticker - arrive in the next commit.
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response

from web.api.routes._spp_common import XLSX, iso_date
from web.api.services import benchmarks as svc

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])



def _not_found(procode: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No hay un benchmark llamado {procode}.")


# ---- Reads ---------------------------------------------------------------------

@router.get("")
def list_benchmarks() -> dict:
    return {"benchmarks": svc.list_benchmarks()}


@router.get("/series")
def get_series_catalog(q: str = Query(""),
                       limit: int = Query(50, ge=1, le=200)) -> dict:
    """Pickable constituent series (the pipeline spine, no model series),
    with their coverage."""
    return {"series": svc.series_catalog(q, limit)}


@router.get("/{procode}")
def get_benchmark(procode: str) -> dict:
    bench = svc.get(procode)
    if bench is None:
        raise _not_found(procode)
    return bench


@router.get("/{procode}/versions")
def get_versions(procode: str) -> dict:
    try:
        return {"versions": svc.versions(procode)}
    except LookupError:
        raise _not_found(procode) from None


@router.get("/{procode}/changelog")
def get_changelog(procode: str) -> dict:
    try:
        return {"changelog": svc.changelog(procode)}
    except LookupError:
        raise _not_found(procode) from None


@router.get("/{procode}/levels")
def get_levels(procode: str,
               date_from: str | None = Query(None, alias="from"),
               date_to: str | None = Query(None, alias="to")) -> dict:
    """The level series as [date, level] points, for the chart."""
    result = svc.levels_points(procode, iso_date(date_from), iso_date(date_to))
    if result is None:
        raise _not_found(procode)
    return result


@router.get("/{procode}/table")
def get_table(procode: str,
              limit: int = Query(60, ge=0, le=20000, description="0 = the whole book")) -> dict:
    """The index day by day, over the book's date grid (a missing day shows)."""
    result = svc.benchmark_table(procode, limit or None)
    if result is None:
        raise _not_found(procode)
    return result


@router.get("/{procode}/export")
def get_export(procode: str,
               date_from: str | None = Query(None, alias="from"),
               date_to: str | None = Query(None, alias="to")) -> Response:
    if svc.get(procode) is None:
        raise _not_found(procode)
    return Response(svc.export_xlsx(procode, iso_date(date_from), iso_date(date_to)),
                    media_type=XLSX,
                    headers={"Content-Disposition": f"attachment; filename={procode}_levels.xlsx"})
