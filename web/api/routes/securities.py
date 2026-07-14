
# web/api/routes/securities.py
# ---------------------------------------------------------------------------
# /api/securities : security picker for the price-viewer dashboard.
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter, Query

from web.api.services import securities as svc

router = APIRouter(prefix="/api/securities", tags=["securities"])


@router.get("")
def list_securities(
    search: str | None = Query(None, description="filter by name / ticker / ISIN"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    return svc.list_securities(search=search, limit=limit)

