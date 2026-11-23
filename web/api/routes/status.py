# web/api/routes/status.py
# ---------------------------------------------------------------------------
# /api/status : feed freshness, latest job runs and scheduler heartbeats,
# each with a traffic-light level (web/api/services/status.py).
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter

from web.api.services import status as svc

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("")
def get_status() -> dict:
    return svc.get_status()
