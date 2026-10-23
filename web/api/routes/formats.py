# web/api/routes/formats.py
# ---------------------------------------------------------------------------
# /api/formats/{key} : which columns each upload site expects, derived
# from the readers themselves. One route for every site because the screen
# that consumes it is one: the help icon next to each upload field.
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from web.api.services import formats as svc

router = APIRouter(prefix="/api/formats", tags=["formats"])


@router.get("")
def list_formats() -> dict:
    return {"formats": sorted(svc.FORMATS)}


@router.get("/{key}")
def get_format(key: str) -> dict:
    try:
        return svc.describe(key)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un formato llamado '{key}'. Los que hay: "
                   + ", ".join(sorted(svc.FORMATS))) from None
