-- 34_fact_positions_deposits.sql
-- ---------------------------------------------------------------
-- fact_positions_deposits: time-deposit holdings from the IDI feed.
--
-- Grain: (portfolio_id, id_orden_inversion, date, source) - one row per fund
-- per deposit order per date. The order id is the key: a deposit's codigo_sbs
-- is the generic '60…' marker, not unique per deposit. NOT entity-resolved
-- (Model A - own table). A deposit has a MATURITY (fecha_vencimiento) - that
-- is what separates it from cash.
--
-- Terms: tasa (rate), dias_vigencia (term in days), fecha_vencimiento (derived
-- from IdSecuencialFechaVencimiento). importe_pen is the deposit's valued
-- amount in soles.
--
-- Upsert policy: ON CONFLICT DO UPDATE (restatements land).
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_positions_deposits (
    -- Grain
    portfolio_id                      INTEGER NOT NULL REFERENCES dim_portfolio(portfolio_id),
    id_orden_inversion                INTEGER NOT NULL,          -- the deposit order (key)
    date                              DATE    NOT NULL,
    source                            TEXT    NOT NULL,

    -- Attributes
    codigo_sbs                        TEXT,                      -- generic '60…' marker
    codigo_iso_moneda                 TEXT    NOT NULL,

    -- Value + terms
    importe_pen                       NUMERIC(18, 4) NOT NULL,   -- deposit value in soles
    tasa                              NUMERIC(12, 8),            -- rate
    dias_vigencia                     INTEGER,                   -- term (days)
    fecha_vencimiento                 DATE,                      -- maturity

    -- Audit
    loaded_at                         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (portfolio_id, id_orden_inversion, date, source)
);

CREATE INDEX IF NOT EXISTS idx_fact_positions_deposits_date
    ON fact_positions_deposits (date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_deposits_portfolio
    ON fact_positions_deposits (portfolio_id, date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_deposits_vencimiento
    ON fact_positions_deposits (fecha_vencimiento)
    WHERE fecha_vencimiento IS NOT NULL;
