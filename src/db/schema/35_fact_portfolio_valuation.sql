-- 35_fact_portfolio_valuation.sql
-- ---------------------------------------------------------------
-- fact_portfolio_valuation: daily fund-level valuation from the IDI feed.
--
-- Grain: (portfolio_id, date, source) - one row per fund per date. This is a
-- PORTFOLIO-level fact (keyed on dim_portfolio), NOT a position fact: it holds
-- the fund NAV (valor_cuota) and AUM (valor_cartera) that CierreIDI reports.
-- Derived from the holdings staging by de-duping the NAV/AUM that is
-- denormalized onto every valorization line.
--
-- Used as the authoritative AUM denominator: vw_positions_unified joins here on
-- (portfolio_id, date) to derive weight = market_value / valor_cartera for
-- every position type (that's why weight is not materialized on the position
-- facts).
--
-- Upsert policy: ON CONFLICT DO UPDATE (restatements land).
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_portfolio_valuation (
    portfolio_id                      INTEGER NOT NULL REFERENCES dim_portfolio(portfolio_id),
    date                              DATE    NOT NULL,
    source                            TEXT    NOT NULL,

    valor_cuota                       NUMERIC(18, 8) NOT NULL,   -- NAV per quota
    valor_cartera                     NUMERIC(18, 4) NOT NULL,   -- AUM

    loaded_at                         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (portfolio_id, date, source)
);

CREATE INDEX IF NOT EXISTS idx_fact_portfolio_valuation_date
    ON fact_portfolio_valuation (date);
