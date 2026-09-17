# src/pipelines/analytics/contribution/run.py
# ---------------------------------------------------------------
# Daily contribution: fact_positions_securities x fact_portfolio_valuation
# -> fact_contribution (method 'fms'). See 39_fact_contribution.sql for
# the formulas and the residual-row convention.
#
# run_full(start_date, end_date): DELETE the range, then one set-based
# INSERT ... SELECT. Idempotent; restated holdings re-run cleanly. The
# LAG over fact_portfolio_valuation runs on the whole (small) table so a
# range's first day still sees its previous snapshot.
#
# This is Postgres-to-Postgres, so the row-by-row iterrows convention
# for vendor loads does not apply - there is no DataFrame.
#
# check(start_date, end_date): asserts SUM(contribution) per fund-day
# equals the cuota return (exercises the residual math). Office-runnable.
# ---------------------------------------------------------------

import logging
from datetime import date

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

METHOD = "fms"

_VALUATION_CTE = """
WITH v AS (
    SELECT portfolio_id, source, date,
           valor_cuota / LAG(valor_cuota) OVER w - 1 AS fund_return,
           LAG(valor_cartera) OVER w                  AS aum_prev
    FROM fact_portfolio_valuation
    WINDOW w AS (PARTITION BY portfolio_id, source ORDER BY date)
),
day AS (
    SELECT * FROM v
    WHERE date BETWEEN %(start)s AND %(end)s AND aum_prev > 0
)
"""

_INSERT_SQL = _VALUATION_CTE + """,
sec AS (
    SELECT s.portfolio_id, s.source, s.date, s.security_entity_id,
           d.aum_prev,
           COALESCE(s.importe_anterior_pen, 0)         AS importe_prev,
           s.importe_pen - COALESCE(s.importe_anterior_pen, 0)
             + COALESCE(s.monto_ordenes_renta, 0)
             + COALESCE(s.monto_dividendos, 0)
             + COALESCE(s.monto_intereses_vencimiento_cupon, 0)
             + COALESCE(s.monto_rescates, 0)           AS pnl_pen
    FROM fact_positions_securities s
    JOIN day d USING (portfolio_id, source, date)
),
agg AS (
    SELECT portfolio_id, source, date,
           SUM(importe_prev) AS importe_prev,
           SUM(pnl_pen)      AS pnl_pen
    FROM sec
    GROUP BY 1, 2, 3
)
INSERT INTO fact_contribution
    (portfolio_id, date, source, method, position_type, position_key,
     security_entity_id, weight_prev, return_pen, pnl_pen, contribution)
SELECT portfolio_id, date, source, %(method)s, 'security', security_entity_id::text,
       security_entity_id,
       importe_prev / aum_prev,
       pnl_pen / NULLIF(importe_prev, 0),
       pnl_pen,
       pnl_pen / aum_prev
FROM sec
UNION ALL
SELECT d.portfolio_id, d.date, d.source, %(method)s, 'residual', 'residual',
       NULL,
       1 - COALESCE(a.importe_prev, 0) / d.aum_prev,
       (d.fund_return * d.aum_prev - COALESCE(a.pnl_pen, 0))
           / NULLIF(d.aum_prev - COALESCE(a.importe_prev, 0), 0),
       d.fund_return * d.aum_prev - COALESCE(a.pnl_pen, 0),
       d.fund_return - COALESCE(a.pnl_pen, 0) / d.aum_prev
FROM day d
LEFT JOIN agg a USING (portfolio_id, source, date)
"""

_CHECK_SQL = _VALUATION_CTE + """
SELECT d.portfolio_id, d.date,
       d.fund_return - SUM(c.contribution) AS gap
FROM day d
JOIN fact_contribution c
  ON c.portfolio_id = d.portfolio_id AND c.source = d.source
 AND c.date = d.date AND c.method = %(method)s
GROUP BY 1, 2, d.fund_return
ORDER BY ABS(d.fund_return - SUM(c.contribution)) DESC
LIMIT 5
"""


def run_full(start_date: date, end_date: date) -> int:
    """Rebuild fact_contribution (method 'fms') for the date range. Idempotent."""
    params = {"start": start_date, "end": end_date, "method": METHOD}
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM fact_contribution WHERE method = %(method)s AND date BETWEEN %(start)s AND %(end)s",
            params,
        )
        deleted = cur.rowcount
        cur.execute(_INSERT_SQL, params)
        inserted = cur.rowcount
    logger.info(f"fact_contribution {start_date}..{end_date}: deleted={deleted} inserted={inserted}")
    return inserted


def check(start_date: date, end_date: date, tol: float = 1e-9) -> None:
    """Fail loud if any fund-day's contributions do not sum to the cuota return."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_CHECK_SQL, {"start": start_date, "end": end_date, "method": METHOD})
        rows = cur.fetchall()
    worst = max((abs(float(r["gap"])) for r in rows), default=0.0)
    logger.info(f"tie-out {start_date}..{end_date}: fund-days={len(rows)} worst_gap={worst:.2e}")
    assert worst < tol, f"contribution tie-out failed, worst gap {worst:.2e}: {rows[0]}"
