
# web/api/routes/contribution.py
# ---------------------------------------------------------------------------
# /api/portfolios/{id}/contribution : per-holding contribution to portfolio return.
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from web.api.services import contribution as svc

router = APIRouter(prefix="/api/portfolios", tags=["contribution"])


@router.get("/{portfolio_id}/contribution")
def contribution(
    portfolio_id: int,
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
    source: str | None = Query(None, description="price source; default bloomberg/any"),
) -> dict:
    result = svc.get_contribution(portfolio_id, date_from, date_to, source)
    if result.get("portfolio") is None:
        raise HTTPException(status_code=404, detail=f"portfolio {portfolio_id} not found")
    return result

