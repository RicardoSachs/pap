-- 33_fact_positions_securities.sql
-- ---------------------------------------------------------------
-- fact_positions_securities: valued security holdings from the IDI feed.
-- Supersedes the old empty fact_positions (file 23), which was a reserved
-- shell — fact_positions (bare) stays reserved for a future rollup.
--
-- Grain: (portfolio_id, security_entity_id, date, source) - one row per fund
-- per security per date. ENTITY-RESOLVED: codigo_sbs -> dim_entity via
-- dim_entity_identifiers (id_type='sbs'); security attributes (name, class,
-- currency) live on dim_security. This is the only entity-resolved positions
-- fact (deposits/cash/forwards/net_receivables are not).
--
-- Measures: importe_pen (market value = cantidad * precio_pen) is the stock;
-- the *_anterior columns are the prior-day stock (FMS's change basis, for
-- daily PnL); monto_* are per-day cash FLOWS (coupons, income, splits,
-- dividends, redemptions) — sum flows over a range, do NOT sum stocks.
--
-- Upsert policy: ON CONFLICT DO UPDATE (restatements land).
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_positions_securities (
    -- Grain
    portfolio_id                      INTEGER NOT NULL REFERENCES dim_portfolio(portfolio_id),
    security_entity_id                INTEGER NOT NULL REFERENCES dim_entity(entity_id),
    date                              DATE    NOT NULL,
    source                            TEXT    NOT NULL,

    -- Attributes
    codigo_iso_moneda                 TEXT,
    ind_clase                         INTEGER,                  -- 145 FI / 146 equity

    -- Stock measures
    importe_pen                       NUMERIC(18, 4) NOT NULL,  -- market value in soles
    cantidad                          NUMERIC(24, 8),
    precio_pen                        NUMERIC(18, 8),
    cantidad_anterior                 NUMERIC(24, 8),
    precio_anterior_pen               NUMERIC(18, 8),
    importe_anterior_pen              NUMERIC(18, 4),

    -- Cash flows (per day)
    monto_intereses_vencimiento_cupon NUMERIC(18, 4),
    monto_ordenes_renta               NUMERIC(18, 4),
    monto_acciones_liberadas          NUMERIC(18, 4),
    monto_dividendos                  NUMERIC(18, 4),
    monto_rescates                    NUMERIC(18, 4),

    -- Audit
    loaded_at                         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (portfolio_id, security_entity_id, date, source)
);

CREATE INDEX IF NOT EXISTS idx_fact_positions_securities_date
    ON fact_positions_securities (date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_securities_portfolio
    ON fact_positions_securities (portfolio_id, date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_securities_entity
    ON fact_positions_securities (security_entity_id);
