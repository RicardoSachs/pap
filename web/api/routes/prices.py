
# web/api/routes/prices.py
# ---------------------------------------------------------------------------
# /api/prices : price history for one security, split by source.
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from web.api.services import prices as svc

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("")
def get_prices(
    entity_id: int = Query(..., description="security to chart"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    sources: str | None = Query(None, description="comma-separated source filter"),
) -> dict:
    src_list = [s.strip() for s in sources.split(",")] if sources else None
    result = svc.get_price_series(entity_id, date_from, date_to, src_list)
    if result["entity"] is None:
        raise HTTPException(status_code=404, detail=f"entity_id {entity_id} not found")
    return result

