
# web/api/services/contribution_providers.py
# ---------------------------------------------------------------------------
# Contribution data-access providers.
# ---------------------------------------------------------------------------
# DerivedContributionProvider computes contribution on the fly from
# vw_positions_unified x fact_prices (no fact_contribution table exists):
#   return_i        = price_i(d1) / price_i(d0) - 1
#   contribution_i  = weight_i(d0) * return_i
# Prices are resolved through series_registry (entity_id, field='PX_LAST', source).
#
# Only position_type='security' rows are entity-resolved, so only they can be
# priced. Deposits/cash/net receivables are returned with return=0 and
# priced=false - their weight is visible but portfolio_return only sums priced
# contributions (understated, visibly). Forwards (in_nav=FALSE) are excluded
# entirely: their MTM already sits inside the net_receivable rows.
#
# A FactContributionProvider seam remains for a hypothetical precomputed table;
# get_contribution_provider() falls back to derived whenever that table is absent
# or empty. Force via env CONTRIBUTION_PROVIDER=derived|fact.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import os
from typing import Protocol

import psycopg

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

# asset_class: position_type for non-security rows; securities split by which
# extension table they live in.
_ASSET_CLASS = """
    CASE WHEN u.position_type <> 'security' THEN u.position_type
         WHEN eq.security_id IS NOT NULL    THEN 'equity'
         WHEN bd.security_id IS NOT NULL    THEN 'bond'
         WHEN fnd.security_id IS NOT NULL
              OR e.entity_type = 'fund'     THEN 'fund'
         ELSE 'security' END
"""


class ContributionProvider(Protocol):
    def get_contribution(self, portfolio_id: int, date_from: str, date_to: str, source: str | None) -> dict: ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _portfolio(cur: psycopg.Cursor, portfolio_id: int) -> dict | None:
    cur.execute(
        "SELECT portfolio_id, procode, display_name, base_currency FROM dim_portfolio WHERE portfolio_id = %s",
        (portfolio_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _bucket_contribution(holdings: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for h in holdings:
        k = h["asset_class"] or "unknown"
        b = agg.setdefault(k, {"asset_class": k, "weight": 0.0, "contribution": 0.0})
        b["weight"] += h["weight"]
        b["contribution"] += h["contribution"]
    rows = sorted(agg.values(), key=lambda r: r["contribution"], reverse=True)
    for r in rows:
        r["weight"] = round(r["weight"], 6)
        r["contribution"] = round(r["contribution"], 6)
    return rows


def _shape(portfolio: dict, date_from: str, date_to: str, source: str | None,
           snapshot_date, holdings: list[dict]) -> dict:
    portfolio_return = round(sum(h["contribution"] for h in holdings), 6)
    holdings = sorted(holdings, key=lambda h: h["contribution"], reverse=True)
    return {
        "portfolio": portfolio,
        "period": {"from": date_from, "to": date_to},
        "snapshot_date": snapshot_date.isoformat() if hasattr(snapshot_date, "isoformat") else snapshot_date,
        "source": source,
        "portfolio_return": portfolio_return,
        "holdings": holdings,
        "by_asset_class": _bucket_contribution(holdings),
    }


def _price_at(cur: psycopg.Cursor, entity_id: int, on_or_before: str, source: str | None) -> float | None:
    """Latest price for entity on/before a date, via series_registry. Prefers
    `source`, else bloomberg, else any."""
    if source:
        cur.execute(
            """SELECT fp.price FROM fact_prices fp
               JOIN series_registry sr ON sr.series_id = fp.series_id
               WHERE sr.entity_id = %s AND sr.domain = 'prices'
                 AND fp.date <= %s::date AND sr.source = %s
               ORDER BY fp.date DESC LIMIT 1""",
            (entity_id, on_or_before, source),
        )
        row = cur.fetchone()
        if row:
            return row["price"]
    cur.execute(
        """SELECT fp.price FROM fact_prices fp
           JOIN series_registry sr ON sr.series_id = fp.series_id
           WHERE sr.entity_id = %s AND sr.domain = 'prices' AND fp.date <= %s::date
           ORDER BY (sr.source = 'bloomberg') DESC, fp.date DESC LIMIT 1""",
        (entity_id, on_or_before),
    )
    row = cur.fetchone()
    return row["price"] if row else None


# ---------------------------------------------------------------------------
# Derived provider (current): vw_positions_unified x fact_prices
# ---------------------------------------------------------------------------
class DerivedContributionProvider:
    def get_contribution(self, portfolio_id, date_from, date_to, source=None) -> dict:
        with get_connection() as conn:
            cur = conn.cursor()
            portfolio = _portfolio(cur, portfolio_id)
            if portfolio is None:
                return {"portfolio": None}

            cur.execute(
                "SELECT MAX(date) AS d FROM vw_positions_unified WHERE portfolio_id = %s AND date <= %s::date",
                (portfolio_id, date_from),
            )
            snap = cur.fetchone()["d"]
            if snap is None:
                return _shape(portfolio, date_from, date_to, source, None, [])

            cur.execute(
                f"""SELECT u.position_type,
                           u.security_entity_id AS entity_id,
                           COALESCE(s.security_name, s.name, e.name,
                                    u.position_type || ' ' || u.position_key) AS display_name,
                           {_ASSET_CLASS} AS asset_class,
                           eq.sector AS sector,
                           u.weight
                    FROM vw_positions_unified u
                    LEFT JOIN dim_entity e ON e.entity_id = u.security_entity_id
                    LEFT JOIN dim_security        s   ON s.entity_id    = e.entity_id
                    LEFT JOIN dim_security_equity eq  ON eq.security_id  = s.security_id
                    LEFT JOIN dim_security_fund   fnd ON fnd.security_id = s.security_id
                    LEFT JOIN dim_security_bond   bd  ON bd.security_id  = s.security_id
                    WHERE u.portfolio_id = %s AND u.date = %s AND u.in_nav""",
                (portfolio_id, snap),
            )
            positions = [dict(row) for row in cur.fetchall()]

            holdings: list[dict] = []
            for pos in positions:
                p0 = p1 = None
                if pos["entity_id"] is not None:
                    p0 = _price_at(cur, pos["entity_id"], date_from, source)
                    p1 = _price_at(cur, pos["entity_id"], date_to, source)
                priced = bool(p0 and p1)
                ret = (p1 / p0 - 1.0) if priced else 0.0
                weight = float(pos["weight"]) if pos["weight"] is not None else 0.0
                holdings.append({
                    "entity_id": pos["entity_id"],
                    "position_type": pos["position_type"],
                    "display_name": pos["display_name"],
                    "asset_class": pos["asset_class"],
                    "sector": pos["sector"],
                    "priced": priced,
                    "weight": round(weight, 6),
                    "return": round(ret, 6),
                    "contribution": round(weight * ret, 6),
                })

        return _shape(portfolio, date_from, date_to, source, snap, holdings)


# ---------------------------------------------------------------------------
# Fact provider (dormant): would read a precomputed fact_contribution table.
# Not part of the pgetl schema -> selection falls back to derived.
# ---------------------------------------------------------------------------
class FactContributionProvider:
    def get_contribution(self, portfolio_id, date_from, date_to, source=None) -> dict:
        with get_connection() as conn:
            cur = conn.cursor()
            portfolio = _portfolio(cur, portfolio_id)
            if portfolio is None:
                return {"portfolio": None}
            sql = """
                SELECT c.entity_id,
                       COALESCE(s.security_name, s.name, e.name) AS display_name,
                       e.entity_type, c.weight, c.period_return AS return, c.contribution
                FROM fact_contribution c
                JOIN dim_entity e ON e.entity_id = c.entity_id
                LEFT JOIN dim_security s ON s.entity_id = e.entity_id
                WHERE c.portfolio_id = %s AND c.period_start = %s::date AND c.period_end = %s::date
            """
            params: list = [portfolio_id, date_from, date_to]
            if source:
                sql += " AND c.source = %s"
                params.append(source)
            cur.execute(sql, params)
            holdings = [{
                "entity_id": r["entity_id"],
                "display_name": r["display_name"],
                "asset_class": r.get("entity_type"),
                "sector": None,
                "weight": round(r["weight"] or 0.0, 6),
                "return": round(r["return"] or 0.0, 6),
                "contribution": round(r["contribution"] or 0.0, 6),
            } for r in cur.fetchall()]
        return _shape(portfolio, date_from, date_to, source, date_from, holdings)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
def _fact_table_has_data() -> bool:
    """True if a fact_contribution table exists and holds rows. In pgetl it does
    not exist, so the SELECT raises -> rolled back -> treated as 'no data'."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM fact_contribution LIMIT 1")
            return cur.fetchone() is not None
    except Exception as exc:
        logger.debug(f"fact_contribution probe -> derived provider: {exc}")
        return False


def get_contribution_provider() -> ContributionProvider:
    override = os.environ.get("CONTRIBUTION_PROVIDER", "").lower()
    if override == "fact":
        return FactContributionProvider()
    if override == "derived":
        return DerivedContributionProvider()
    return FactContributionProvider() if _fact_table_has_data() else DerivedContributionProvider()

