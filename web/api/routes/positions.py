
# web/api/routes/positions.py
# ---------------------------------------------------------------------------
# /api/portfolios/{id}/holdings : enriched holdings for the positioning dashboard.
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from web.api.services import positions as svc

router = APIRouter(prefix="/api/portfolios", tags=["positions"])


@router.get("/{portfolio_id}/holdings")
def holdings(
    portfolio_id: int,
    date: str | None = Query(None, description="snapshot date; defaults to latest"),
) -> dict:
    result = svc.get_holdings(portfolio_id, date)
    if result["portfolio"] is None:
        raise HTTPException(status_code=404, detail=f"portfolio {portfolio_id} not found")
    return result

