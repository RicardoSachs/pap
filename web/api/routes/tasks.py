# web/api/routes/tasks.py
# ---------------------------------------------------------------------------
# /api/tasks : the background task slot the dashboards share (SBS scrape,
# history load, benchmark materialization). One read: the current state,
# which every write view polls until `active` goes false. The writes that
# launch a task live with their module (spp_write, benchmarks).
# ---------------------------------------------------------------------------
from __future__ import annotations

from fastapi import APIRouter

from web.api.services import task_slot as task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/current")
def get_current() -> dict:
    return task.status()
