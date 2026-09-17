# web/api/routes/contribution.py
# ---------------------------------------------------------------------------
# /api/portfolios/{id}/contribution : per-holding contribution to portfolio
# return over (from, to], read from fact_contribution.
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
    basis: str = Query("linked", pattern="^(linked|pnl)$",
                       description="linked = Carino-linked (ties to cuota); pnl = PnL / start AUM"),
) -> dict:
    result = svc.get_contribution(portfolio_id, date_from, date_to, basis)
    if result.get("portfolio") is None:
        raise HTTPException(status_code=404, detail=f"portfolio {portfolio_id} not found")
    return result
