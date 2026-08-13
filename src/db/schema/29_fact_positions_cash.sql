-- 29_fact_positions_cash.sql
-- ---------------------------------------------------------------
-- fact_positions_cash: current-account cash balances.
--
-- Grain: (portfolio_id, codigo_institucion, codigo_iso_moneda, date,
-- source) - one row per portfolio per institution (bank) per currency
-- per date per source. FMS identifies a cash account by institution, and
-- a fund holds cash across several banks per currency, so both institution
-- and currency are part of the grain. codigo_institucion is the FMS code
-- (IdEntidad); nombre_institucion is the readable name (Institucion).
--
-- Interest: current accounts may be remunerated; tasa_interes and
-- interes_acumulado are nullable (null for non-remunerated accounts).
-- Cash has NO maturity - that is what separates it from deposits.
--
-- Not entity-resolved: cash does NOT point at dim_entity. This is the
-- deliberate Model A choice - cash gets its own per-type fact table
-- rather than synthetic per-currency dim_entity rows flowing through
-- fact_positions. (The web layer still reads cash via entity_type in
-- a few services; re-pointing it at this table is a tracked follow-up.)
--
-- Source-unified: source is on the PK so the same (portfolio,
-- currency, date) could later carry cash from another source.
--
-- Upsert policy: ON CONFLICT DO UPDATE - a re-run restates the balance.
--
-- soles: monto_total_soles (MontoTotalSoles) comes directly from the FMS
-- source; cash provides the soles amount, so there is NO FX-spot column
-- (unlike forwards). saldo_contable is the balance in the account currency.
-- Downstream NAV/exposure rollups use monto_total_soles.
--
-- NUMERIC precision: monetary NUMERIC(18, 4), matching the positions
-- domain (cent-exact vs the project-wide DOUBLE PRECISION default).
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_positions_cash (
    -- Grain
    portfolio_id                  INTEGER NOT NULL REFERENCES dim_portfolio(portfolio_id),
    codigo_institucion            TEXT    NOT NULL,             -- institution code (IdEntidad)
    codigo_iso_moneda             TEXT    NOT NULL,
    date                          DATE    NOT NULL,
    source                        TEXT    NOT NULL,             -- 'fms' | ...

    -- Institution
    nombre_institucion            TEXT,                         -- display name (Institucion)

    -- Balance (source currency + soles, both from FMS directly)
    saldo_contable                NUMERIC(18, 4) NOT NULL,      -- accounting balance in codigo_iso_moneda (SaldoContable)
    monto_total_soles             NUMERIC(18, 4) NOT NULL,      -- total amount in soles (MontoTotalSoles)

    -- Interest (nullable - not every account is remunerated)
    tasa_interes                  NUMERIC(12, 8),               -- account interest rate
    interes_acumulado             NUMERIC(18, 4),               -- cumulative interest to date

    -- Audit
    loaded_at                     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (portfolio_id, codigo_institucion, codigo_iso_moneda, date, source)
);

CREATE INDEX IF NOT EXISTS idx_fact_positions_cash_date
    ON fact_positions_cash (date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_cash_portfolio
    ON fact_positions_cash (portfolio_id, date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_cash_moneda
    ON fact_positions_cash (codigo_iso_moneda);

CREATE INDEX IF NOT EXISTS idx_fact_positions_cash_institucion
    ON fact_positions_cash (codigo_institucion);
