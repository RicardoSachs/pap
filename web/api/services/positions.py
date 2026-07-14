
# web/api/services/positions.py
# ---------------------------------------------------------------------------
# Positions service : enriched holdings for a portfolio on a given date.
# Joins fact_positions (security_entity_id, date, source) -> dim_entity (+
# dim_security / extensions) for names + derived asset_class, and returns the
# per-holding rows plus summary buckets for the breakdown chart.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

_ASSET_CLASS = """
    CASE WHEN e.entity_type = 'cash'    THEN 'cash'
         WHEN eq.security_id IS NOT NULL THEN 'equity'
         WHEN bd.security_id IS NOT NULL THEN 'bond'
         WHEN fnd.security_id IS NOT NULL OR e.entity_type = 'fund' THEN 'fund'
         ELSE 'security' END
"""


def get_holdings(portfolio_id: int, reference_date: str | None = None) -> dict:
    """Return enriched holdings + summary for a portfolio on a date.

    If reference_date is omitted, uses the latest available snapshot; otherwise
    snaps to the latest snapshot on/before it.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """SELECT portfolio_id, procode, source, portfolio_type,
                      display_name, base_currency, status
               FROM dim_portfolio WHERE portfolio_id = %s""",
            (portfolio_id,),
        )
        pf_row = cur.fetchone()
        if pf_row is None:
            return {"portfolio": None, "reference_date": None, "holdings": [], "summary": {}}
        portfolio = dict(pf_row)

        if reference_date is None:
            cur.execute("SELECT MAX(date) AS d FROM fact_positions WHERE portfolio_id = %s", (portfolio_id,))
        else:
            cur.execute(
                "SELECT MAX(date) AS d FROM fact_positions WHERE portfolio_id = %s AND date <= %s::date",
                (portfolio_id, reference_date),
            )
        snap = cur.fetchone()["d"]

        cur.execute(
            f"""SELECT p.security_entity_id AS entity_id,
                       COALESCE(s.security_name, s.name, e.name) AS display_name,
                       {_ASSET_CLASS} AS asset_class,
                       eq.sector AS sector,
                       p.source, p.quantity, p.market_value, p.weight, p.price_used, p.currency
                FROM fact_positions p
                JOIN dim_entity e ON e.entity_id = p.security_entity_id
                LEFT JOIN dim_security        s   ON s.entity_id   = e.entity_id
                LEFT JOIN dim_security_equity eq  ON eq.security_id = s.security_id
                LEFT JOIN dim_security_fund   fnd ON fnd.security_id = s.security_id
                LEFT JOIN dim_security_bond   bd  ON bd.security_id = s.security_id
                WHERE p.portfolio_id = %s AND p.date = %s
                ORDER BY p.market_value DESC""",
            (portfolio_id, snap),
        )
        holdings = [dict(row) for row in cur.fetchall()]

    total_mv = sum(h["market_value"] or 0.0 for h in holdings)
    return {
        "portfolio": portfolio,
        "reference_date": snap.isoformat() if snap else None,
        "total_market_value": round(total_mv, 2),
        "holdings": holdings,
        "summary": {
            "by_asset_class": _bucket(holdings, "asset_class"),
            "by_currency": _bucket(holdings, "currency"),
        },
    }


def _bucket(holdings: list[dict], key: str) -> list[dict]:
    """Aggregate market_value + weight by a holding attribute, descending."""
    agg: dict[str, dict] = {}
    for h in holdings:
        k = h.get(key) or "unknown"
        b = agg.setdefault(k, {"key": k, "market_value": 0.0, "weight": 0.0})
        b["market_value"] += h["market_value"] or 0.0
        b["weight"] += h["weight"] or 0.0
    rows = sorted(agg.values(), key=lambda r: r["market_value"], reverse=True)
    for r in rows:
        r["market_value"] = round(r["market_value"], 2)
        r["weight"] = round(r["weight"], 6)
    return rows

