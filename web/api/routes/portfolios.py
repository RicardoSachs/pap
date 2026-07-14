
# web/api/routes/portfolios.py
# ---------------------------------------------------------------------------
# /api/portfolios : portfolio list + available position snapshot dates.
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter

from web.api.services import portfolios as svc

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


@router.get("")
def list_portfolios() -> list[dict]:
    return svc.list_portfolios()


@router.get("/{portfolio_id}/dates")
def position_dates(portfolio_id: int) -> list[str]:
    return svc.get_position_dates(portfolio_id)

