# web/api/services/positions.py
# ---------------------------------------------------------------------------
# Positions service : enriched holdings for a portfolio on a given date.
#
# Reads vw_positions_unified (Architecture B consolidation view over the five
# per-type position facts). Only position_type='security' rows are entity-
# resolved; the other types (deposit, cash, forward, net_receivable) display
# as position_type + position_key and take asset_class = position_type.
#
# weight comes from the view (market_value_pen / valor_cartera, the
# authoritative AUM from fact_portfolio_valuation) - NULL when the valuation
# row is missing, never recomputed over the holdings.
#
# in_nav=FALSE rows (forwards) are returned for display but EXCLUDED from
# total_market_value and the summary buckets: FMS embeds forward MTM inside
# CuentaCobrarPagar, so the net_receivable rows already carry it and summing
# forwards too would double-count (see 36_vw_positions_unified.sql).
#
# All PEN values: market_value is market_value_pen (soles), so by_currency
# means exposure by currency of denomination, valued in soles.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

# asset_class: position_type for non-security rows; securities split by which
# extension table they live in (no stored asset_class column in the schema).
_ASSET_CLASS = """
    CASE WHEN u.position_type <> 'security' THEN u.position_type
         WHEN eq.security_id IS NOT NULL    THEN 'equity'
         WHEN bd.security_id IS NOT NULL    THEN 'bond'
         WHEN fnd.security_id IS NOT NULL
              OR e.entity_type = 'fund'     THEN 'fund'
         ELSE 'security' END
"""

_NUMERIC_FIELDS = ("quantity", "price_used", "market_value", "weight")


def _floats(row: dict) -> dict:
    """NUMERIC columns arrive as Decimal; JSON + downstream math want float."""
    for k in _NUMERIC_FIELDS:
        if row.get(k) is not None:
            row[k] = float(row[k])
    return row


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
            cur.execute(
                "SELECT MAX(date) AS d FROM fact_portfolio_valuation WHERE portfolio_id = %s",
                (portfolio_id,),
            )
        else:
            cur.execute(
                "SELECT MAX(date) AS d FROM fact_portfolio_valuation WHERE portfolio_id = %s AND date <= %s::date",
                (portfolio_id, reference_date),
            )
        snap = cur.fetchone()["d"]

        cur.execute(
            f"""SELECT u.position_type,
                       u.position_key,
                       u.security_entity_id AS entity_id,
                       COALESCE(s.security_name, s.name, e.name,
                                u.position_type || ' ' || u.position_key) AS display_name,
                       {_ASSET_CLASS} AS asset_class,
                       eq.sector AS sector,
                       u.source,
                       fs.cantidad   AS quantity,
                       fs.precio_pen AS price_used,
                       u.market_value_pen AS market_value,
                       u.weight,
                       u.codigo_iso_moneda AS currency,
                       u.in_nav
                FROM vw_positions_unified u
                LEFT JOIN dim_entity e ON e.entity_id = u.security_entity_id
                LEFT JOIN dim_security        s   ON s.entity_id    = e.entity_id
                LEFT JOIN dim_security_equity eq  ON eq.security_id  = s.security_id
                LEFT JOIN dim_security_fund   fnd ON fnd.security_id = s.security_id
                LEFT JOIN dim_security_bond   bd  ON bd.security_id  = s.security_id
                LEFT JOIN fact_positions_securities fs
                       ON u.position_type = 'security'
                      AND fs.portfolio_id = u.portfolio_id
                      AND fs.security_entity_id = u.security_entity_id
                      AND fs.date = u.date
                      AND fs.source = u.source
                WHERE u.portfolio_id = %s AND u.date = %s
                ORDER BY u.market_value_pen DESC NULLS LAST""",
            (portfolio_id, snap),
        )
        holdings = [_floats(dict(row)) for row in cur.fetchall()]

    nav_rows = [h for h in holdings if h["in_nav"]]
    total_mv = sum(h["market_value"] or 0.0 for h in nav_rows)
    return {
        "portfolio": portfolio,
        "reference_date": snap.isoformat() if snap else None,
        "total_market_value": round(total_mv, 2),
        "holdings": holdings,
        "summary": {
            "by_asset_class": _bucket(nav_rows, "asset_class"),
            "by_currency": _bucket(nav_rows, "currency"),
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
