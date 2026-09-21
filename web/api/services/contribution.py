# web/api/services/contribution.py
# ---------------------------------------------------------------------------
# Contribution service: period aggregate over fact_contribution (daily rows,
# see 39_fact_contribution.sql). Nothing is derived from prices here.
#
# Period = days d with from < d <= to. Two bases:
#   linked  Carino linking: each day's contribution scaled by k_t / K with
#           k_t = ln(1+r_t)/r_t and K = ln(1+R)/R, so per-holding contributions
#           sum EXACTLY to the compounded fund return R over the period.
#   pnl     SUM(pnl_pen) / AUM at the period start. The accountant's view;
#           does not tie to the cuota return when AUM moves with flows.
#
# weight = average of daily weight_prev over the period (0 on days not held);
# return = compounded daily return_pen over the days held.
#
# Daily measures are cast to float8 before LN/EXP: NUMERIC transcendental
# math in Postgres is ~100x slower and this runs over holdings x days rows.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from src.db.connection import get_connection
from web.api.services.positions import _ASSET_CLASS

logger = logging.getLogger(__name__)

METHOD = "fms"
RESIDUAL_NAME = "Residual (cash, deposits, forwards, fees)"

_DAY_CTE = """
WITH day AS (
    SELECT date, SUM(contribution)::float8 AS r
    FROM fact_contribution
    WHERE portfolio_id = %(pid)s AND method = %(method)s
      AND date > %(d0)s::date AND date <= %(d1)s::date
    GROUP BY date
),
tot AS (
    SELECT COUNT(*) AS n_days,
           EXP(SUM(LN(1 + r))) - 1 AS big_r
    FROM day WHERE r > -1
)
"""

_TOTAL_SQL = _DAY_CTE + "SELECT n_days, big_r FROM tot"

_HOLDINGS_SQL = _DAY_CTE + f""",
k AS (
    SELECT date, CASE WHEN r = 0 THEN 1 WHEN r <= -1 THEN NULL ELSE LN(1 + r) / r END AS kt
    FROM day
),
kk AS (
    SELECT n_days, CASE WHEN big_r = 0 THEN 1 ELSE LN(1 + big_r) / big_r END AS big_k
    FROM tot
),
agg AS (
    SELECT c.position_type, c.position_key, c.security_entity_id,
           SUM(c.weight_prev::float8) / kk.n_days                                        AS weight,
           EXP(SUM(LN(1 + c.return_pen::float8)) FILTER (WHERE c.return_pen > -1)) - 1   AS return,
           SUM(c.pnl_pen)                                                                 AS pnl_pen,
           SUM(c.contribution::float8 * k.kt / kk.big_k)                                  AS contribution
    FROM fact_contribution c
    JOIN k ON k.date = c.date
    CROSS JOIN kk
    WHERE c.portfolio_id = %(pid)s AND c.method = %(method)s
      AND c.date > %(d0)s::date AND c.date <= %(d1)s::date
    GROUP BY 1, 2, 3, kk.n_days
)
SELECT u.position_type, u.position_key, u.security_entity_id AS entity_id,
       COALESCE(s.security_name, s.name, e.name, %(residual_name)s) AS display_name,
       {_ASSET_CLASS} AS asset_class,
       eq.sector AS sector,
       u.weight, u.return, u.pnl_pen, u.contribution
FROM agg u
LEFT JOIN dim_entity          e   ON e.entity_id    = u.security_entity_id
LEFT JOIN dim_security        s   ON s.entity_id    = e.entity_id
LEFT JOIN dim_security_equity eq  ON eq.security_id  = s.security_id
LEFT JOIN dim_security_fund   fnd ON fnd.security_id = s.security_id
LEFT JOIN dim_security_bond   bd  ON bd.security_id  = s.security_id
"""

_AUM_AT_SQL = """
SELECT valor_cartera, date FROM fact_portfolio_valuation
WHERE portfolio_id = %s AND date <= %s::date
ORDER BY date DESC LIMIT 1
"""


def get_contribution(portfolio_id: int, date_from: str, date_to: str, basis: str = "linked") -> dict:
    """Return {portfolio, period, basis, days, portfolio_return, aum, aum_date, holdings[], by_asset_class[]}.

    aum is valor_cartera at the latest snapshot on/before `to`, so the page
    needs no separate holdings call for its AUM tile.
    """
    params = {"pid": portfolio_id, "method": METHOD, "d0": date_from, "d1": date_to,
              "residual_name": RESIDUAL_NAME}
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT portfolio_id, procode, display_name, base_currency FROM dim_portfolio WHERE portfolio_id = %s",
            (portfolio_id,),
        )
        row = cur.fetchone()
        if row is None:
            return {"portfolio": None}
        portfolio = dict(row)

        cur.execute(_TOTAL_SQL, params)
        tot = cur.fetchone()
        n_days, big_r = int(tot["n_days"]), _f(tot["big_r"])

        cur.execute(_HOLDINGS_SQL, params)
        holdings = [_row(r) for r in cur.fetchall()]

        cur.execute(_AUM_AT_SQL, (portfolio_id, date_to))
        end = cur.fetchone()

        if basis == "pnl":
            cur.execute(_AUM_AT_SQL, (portfolio_id, date_from))
            aum = cur.fetchone()
            aum_start = _f(aum["valor_cartera"]) if aum else None
            for h in holdings:
                h["contribution"] = round(h["pnl_pen"] / aum_start, 6) if aum_start else 0.0
            big_r = round(sum(h["contribution"] for h in holdings), 6)

    holdings.sort(key=lambda h: h["contribution"], reverse=True)
    return {
        "portfolio": portfolio,
        "period": {"from": date_from, "to": date_to},
        "basis": basis,
        "method": METHOD,
        "days": n_days,
        "portfolio_return": round(big_r, 6) if big_r is not None else 0.0,
        "aum": round(_f(end["valor_cartera"]), 2) if end else None,
        "aum_date": end["date"].isoformat() if end else None,
        "holdings": holdings,
        "by_asset_class": _bucket(holdings),
    }


def _f(x) -> float | None:
    return None if x is None else float(x)


def _row(r: dict) -> dict:
    return {
        "entity_id": r["entity_id"],
        "position_type": r["position_type"],
        "position_key": r["position_key"],
        "display_name": r["display_name"],
        "asset_class": r["asset_class"],
        "sector": r["sector"],
        "weight": round(_f(r["weight"]) or 0.0, 6),
        "return": round(_f(r["return"]), 6) if r["return"] is not None else None,
        "pnl_pen": round(_f(r["pnl_pen"]) or 0.0, 2),
        "contribution": round(_f(r["contribution"]) or 0.0, 6),
    }


def _bucket(holdings: list[dict]) -> list[dict]:
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
