-- 43_fact_positions_model.sql
-- ---------------------------------------------------------------
-- fact_positions_model: dated holdings produced by a MODEL, not
-- observed from a custodian. Today: the constituents of a benchmark,
-- materialized from its definition versions and fact_prices by
-- src/pipelines/analytics/benchmark/materialize.py. Tomorrow (pending
-- doc item 6): estimated peer holdings, same table, same lineage.
--
-- Grain: (portfolio_id, date, entity_id, version_id, source). The
-- version_id is IN the key on purpose: a restatement writes new rows
-- under the new version and the rows the old version produced stay -
-- materialized rows are never deleted. vw_positions_model_current
-- (below) picks, per (portfolio, date), the rows of the highest
-- version_id, which is what a reader wants by default; the full table
-- is what an auditor wants.
--
-- Notional is EXPLICIT and unitless: the index level, base 100 at the
-- first version. market_value_pen is the constituent's share of that
-- level, so SUM(market_value_pen) per date = the level, and the
-- companion fact_portfolio_valuation row (valor_cartera = level) makes
-- vw_positions_unified's weight = market_value / valor_cartera
-- arithmetic work unchanged if this fact is ever folded into it.
-- The column keeps the positions-domain name so the shape matches.
--
-- A dedicated fact, not fact_positions_securities: that table's
-- columns are FMS-specific (importes anteriores, cash flows) and mean
-- nothing for a model holding.
--
-- DOUBLE PRECISION: analytical fact, no cent-exact reconciliation.
-- Upsert policy: ON CONFLICT DO UPDATE within the same version (a
-- re-run of one version refreshes its own rows); other versions' rows
-- are never touched.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_positions_model (
    portfolio_id      INTEGER NOT NULL REFERENCES dim_portfolio (portfolio_id),
    date              DATE    NOT NULL,
    entity_id         INTEGER NOT NULL REFERENCES dim_entity (entity_id),
    version_id        INTEGER NOT NULL REFERENCES dim_benchmark_version (version_id),
    source            TEXT    NOT NULL DEFAULT 'model',

    units             DOUBLE PRECISION NOT NULL,      -- struck at the period start
    price             DOUBLE PRECISION NOT NULL,      -- after the FX leg, if any
    market_value_pen  DOUBLE PRECISION NOT NULL,      -- units * price (share of the level)
    weight            DOUBLE PRECISION NOT NULL,      -- market_value_pen / level

    loaded_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (portfolio_id, date, entity_id, version_id, source)
);

CREATE INDEX IF NOT EXISTS idx_fact_positions_model_portfolio_date
    ON fact_positions_model (portfolio_id, date);

CREATE INDEX IF NOT EXISTS idx_fact_positions_model_entity
    ON fact_positions_model (entity_id);

-- The reader's face of the table: per (portfolio, date, source) the
-- rows of the highest version_id, i.e. the current restatement.
CREATE OR REPLACE VIEW vw_positions_model_current AS
SELECT p.*
FROM fact_positions_model p
JOIN (
    SELECT portfolio_id, date, source, MAX(version_id) AS version_id
    FROM fact_positions_model
    GROUP BY portfolio_id, date, source
) latest USING (portfolio_id, date, source, version_id);
