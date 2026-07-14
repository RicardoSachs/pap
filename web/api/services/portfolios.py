
# web/api/services/portfolios.py
# ---------------------------------------------------------------------------
# Portfolios service : portfolio list + available position dates.
# dim_portfolio uses `procode` (the house internal-code name); fact_positions
# uses a `date` column.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from src.db.connection import get_connection

logger = logging.getLogger(__name__)


def list_portfolios() -> list[dict]:
    """All portfolios, for the portfolio picker."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT portfolio_id, procode, source, portfolio_type,
                      display_name, base_currency, status
               FROM dim_portfolio
               ORDER BY display_name"""
        )
        return [dict(row) for row in cur.fetchall()]


def get_position_dates(portfolio_id: int) -> list[str]:
    """Distinct snapshot dates that have positions, most recent first (ISO strings)."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT DISTINCT date
               FROM fact_positions
               WHERE portfolio_id = %s
               ORDER BY date DESC""",
            (portfolio_id,),
        )
        return [row["date"].isoformat() for row in cur.fetchall()]

