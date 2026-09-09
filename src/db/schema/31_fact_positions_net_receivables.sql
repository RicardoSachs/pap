-- 31_fact_positions_net_receivables.sql
-- ---------------------------------------------------------------
-- fact_positions_net_receivables: net receivable / payable balances.
--
-- Grain: (portfolio_id, codigo_iso_moneda, date, source) - one row per
-- portfolio per currency per as-of date per source. Both legs are stored:
-- monto_cobrar (receivables) and monto_pagar (payables), each a positive
-- magnitude. Net = monto_cobrar - monto_pagar, derived downstream (a view /
-- rollup), not materialized here.
--
-- Not entity-resolved: like cash, this does NOT point at dim_entity
-- (Model A - own per-type fact table). No maturity (that's deposits).
--
-- POINT-IN-TIME: `date` is the as-of day the open balance was computed for,
-- reconstructed from FMS.CuentaCobrarPagar. A past day is a live
-- recomputation, so re-running restates it (ON CONFLICT DO UPDATE) - see the
-- feed's run notes on the trailing-window refresh.
--
-- Soles legs: monto_*_soles converted at the FMS MonedaCambio rate as-of
-- `date`; NULLABLE - NULL means the FMS FX rate was missing for a non-PEN
-- currency (fails visible, never silently valued at 1.0). tipo_cambio is
-- PROVENANCE for the soles figures only (1 for PEN rows) - fact_prices is
-- the system's FX historian; never read rates from this table.
--
-- NUMERIC precision: monetary NUMERIC(18, 4), matching the positions
-- domain (cent-exact vs the project-wide DOUBLE PRECISION default).
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_positions_net_receivables (
    -- Grain
    portfolio_id                  INTEGER NOT NULL REFERENCES dim_portfolio(portfolio_id),
    codigo_iso_moneda             TEXT    NOT NULL,
    date                          DATE    NOT NULL,
    source                        TEXT    NOT NULL,             -- 'fms' | ...

    -- Legs (both positive; net = cobrar - pagar, derived downstream)
    monto_cobrar                  NUMERIC(18, 4) NOT NULL,      -- receivables (CxC), original currency
    monto_pagar                   NUMERIC(18, 4) NOT NULL,      -- payables (CxP), original currency
    monto_cobrar_soles            NUMERIC(18, 4),               -- CxC in PEN (NULL = missing FMS FX rate)
    monto_pagar_soles             NUMERIC(18, 4),               -- CxP in PEN (NULL = missing FMS FX rate)
    tipo_cambio                   NUMERIC(18, 8),               -- FMS rate used (provenance only; 1 for PEN)

    -- Audit
    loaded_at                     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (portfolio_id, codigo_iso_moneda, date, source)
);

CREATE INDEX IF NOT EXISTS idx_fact_positions_net_receivables_date
    ON fact_positions_net_receivables (date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_net_receivables_portfolio
    ON fact_positions_net_receivables (portfolio_id, date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_net_receivables_moneda
    ON fact_positions_net_receivables (codigo_iso_moneda);
