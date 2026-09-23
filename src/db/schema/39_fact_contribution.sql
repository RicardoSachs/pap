-- 39_fact_contribution.sql
-- ---------------------------------------------------------------
-- fact_contribution: daily per-holding contribution to fund return,
-- derived from fact_positions_securities x fact_portfolio_valuation.
-- Analytical fact (no staging, no vendor): rebuilt per date range by
-- src/pipelines/analytics/contribution/run.py (DELETE range, then one
-- INSERT ... SELECT).
--
-- Grain: (portfolio_id, date, source, method, position_type, position_key)
--   method         'fms'    - FMS's own PEN valuation (accounting PnL)
--                  'market' - reserved: fact_prices x FX; not built
--   position_type  'security' - entity-resolved, one row per holding
--                  'residual' - one row per fund-day: everything not
--                  attributed to a security (deposits, cash, forward
--                  MTM, fees, sold-out positions FMS dropped)
--
-- Measures, day t against the previous IDI snapshot t-1 (diagnostic
-- block 1 confirmed *_anterior IS the previous snapshot):
--   weight_prev   importe_anterior_pen / valor_cartera(t-1)
--   pnl_pen       importe_pen - importe_anterior_pen
--                 + monto_ordenes_renta   (trade cash; negative on buys)
--                 + monto_dividendos + monto_intereses_vencimiento_cupon
--                 + monto_rescates        (income / redemptions; positive)
--                 monto_acciones_liberadas EXCLUDED: free shares carry no
--                 cash and their value already sits in importe_pen.
--   return_pen    pnl_pen / importe_anterior_pen  (NULL on a new position)
--   contribution  pnl_pen / valor_cartera(t-1)
--
-- Residual row: fund_return - SUM(security contribution), with
-- fund_return = valor_cuota(t) / valor_cuota(t-1) - 1. By construction
-- SUM(contribution) per (portfolio, date) = fund_return, so any period
-- aggregate ties out to the cuota. Period linking (Carino) lives in
-- the API (web/api/services/contribution.py), not in the table.
--
-- Diagnostics behind these choices:
--   src/pipelines/positions/fms/holdings/queries/diagnose_contribution_inputs.sql
-- NUMERIC, positions convention.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_contribution (
    portfolio_id        INTEGER NOT NULL REFERENCES dim_portfolio(portfolio_id),
    date                DATE    NOT NULL,
    source              TEXT    NOT NULL,
    method              TEXT    NOT NULL CHECK (method IN ('fms', 'market')),
    position_type       TEXT    NOT NULL,
    position_key        TEXT    NOT NULL,
    security_entity_id  INTEGER REFERENCES dim_entity(entity_id),

    weight_prev         NUMERIC(20, 12),
    return_pen          NUMERIC(20, 12),
    pnl_pen             NUMERIC(18, 4),
    contribution        NUMERIC(20, 12) NOT NULL,

    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (portfolio_id, date, source, method, position_type, position_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_contribution_entity
    ON fact_contribution (security_entity_id);
