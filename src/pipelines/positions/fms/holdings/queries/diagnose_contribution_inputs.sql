-- diagnose_contribution_inputs.sql
-- ---------------------------------------------------------------
-- Office-run diagnostic (Postgres / DBeaver). NOT part of the pipeline.
--
-- Settles the FMS semantics that fact_contribution depends on, before
-- the pipeline is written. Four independent blocks; run each, paste
-- the results back. Each block says what a "good" answer looks like.
-- ---------------------------------------------------------------

-- 1. Is *_anterior the previous IDI snapshot?
--    good: gap ~ 0 on every row (then AUM_prev = valuation at prev_date).
--    bad:  systematic gaps -> anterior is a different date basis.
WITH d AS (
    SELECT portfolio_id, source, date,
           SUM(importe_pen)          AS imp,
           SUM(importe_anterior_pen) AS imp_ant
    FROM fact_positions_securities
    WHERE date >= CURRENT_DATE - 30
    GROUP BY 1, 2, 3
)
SELECT d.portfolio_id, d.date, p.date AS prev_date,
       d.imp_ant, p.imp AS imp_prev_snapshot, d.imp_ant - p.imp AS gap
FROM d
JOIN LATERAL (
    SELECT * FROM d p
    WHERE p.portfolio_id = d.portfolio_id AND p.source = d.source AND p.date < d.date
    ORDER BY p.date DESC LIMIT 1
) p ON TRUE
ORDER BY 1, 2;

-- 2. Flow columns: sign and meaning.
--    Rows where quantity changed. Which monto column matches
--    qty_change_at_px (trade cash), and with which sign? Is
--    monto_acciones_liberadas a cash amount or a memo of free shares?
SELECT date, portfolio_id, security_entity_id,
       cantidad_anterior, cantidad,
       (cantidad - cantidad_anterior) * precio_pen                 AS qty_change_at_px,
       importe_pen - importe_anterior_pen                          AS d_importe,
       cantidad_anterior * (precio_pen - precio_anterior_pen)      AS price_effect,
       monto_ordenes_renta, monto_acciones_liberadas, monto_rescates,
       monto_dividendos, monto_intereses_vencimiento_cupon
FROM fact_positions_securities
WHERE date >= CURRENT_DATE - 60
  AND cantidad IS DISTINCT FROM cantidad_anterior
ORDER BY ABS(cantidad - cantidad_anterior) * precio_pen DESC
LIMIT 40;

-- 3. Income days: does the price effect show the ex-div / coupon drop,
--    so monto_* must be ADDED back to get total return?
SELECT date, portfolio_id, security_entity_id,
       cantidad_anterior * (precio_pen - precio_anterior_pen)      AS price_effect,
       importe_pen - importe_anterior_pen                          AS d_importe,
       monto_dividendos, monto_intereses_vencimiento_cupon, monto_rescates
FROM fact_positions_securities
WHERE COALESCE(monto_dividendos, 0) <> 0
   OR COALESCE(monto_intereses_vencimiento_cupon, 0) <> 0
   OR COALESCE(monto_rescates, 0) <> 0
ORDER BY date DESC
LIMIT 40;

-- 4. Sold-out positions: does FMS keep a row on the day quantity hits 0?
--    good: rows exist (sale-day PnL is capturable).
--    none: the sale-day move lands in the residual.
SELECT date, portfolio_id, security_entity_id, cantidad_anterior, importe_anterior_pen, precio_pen
FROM fact_positions_securities
WHERE cantidad = 0 AND cantidad_anterior > 0
ORDER BY date DESC
LIMIT 20;

-- 5. Tie-out preview: fund return from valor_cuota vs securities
--    price effect + income over prior AUM. The residual column is what
--    fact_contribution would book as position_type = 'residual'
--    (deposits, cash, forwards MTM, fees). Expect it to be small but
--    non-zero; a residual that tracks forward MTM swings is expected.
WITH v AS (
    SELECT portfolio_id, source, date, valor_cuota, valor_cartera,
           LAG(valor_cuota)   OVER w AS cuota_prev,
           LAG(valor_cartera) OVER w AS aum_prev
    FROM fact_portfolio_valuation
    WINDOW w AS (PARTITION BY portfolio_id, source ORDER BY date)
),
s AS (
    SELECT portfolio_id, source, date,
           SUM(cantidad_anterior * (precio_pen - precio_anterior_pen))            AS price_effect,
           SUM(COALESCE(monto_dividendos, 0)
             + COALESCE(monto_intereses_vencimiento_cupon, 0))                    AS income
    FROM fact_positions_securities
    GROUP BY 1, 2, 3
)
SELECT v.portfolio_id, v.date,
       v.valor_cuota / v.cuota_prev - 1                                           AS fund_ret,
       (s.price_effect + s.income) / v.aum_prev                                   AS securities_contrib,
       v.valor_cuota / v.cuota_prev - 1 - (s.price_effect + s.income) / v.aum_prev AS residual
FROM v
JOIN s USING (portfolio_id, source, date)
WHERE v.date >= CURRENT_DATE - 30 AND v.cuota_prev IS NOT NULL
ORDER BY 1, 2;
