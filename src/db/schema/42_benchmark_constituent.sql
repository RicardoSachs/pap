-- 42_benchmark_constituent.sql
-- ---------------------------------------------------------------
-- benchmark_constituent: the basket of one benchmark version - which
-- priced series it holds and with what weight at the version's
-- effective_from.
--
-- Grain: (version_id, series_id). A constituent is identified by the
-- SERIES that prices it (series_registry), not by the entity: an
-- entity can carry several series, and the one that prices the leg
-- is the choice that defines the basket. The entity is derived from
-- the series when holdings are materialized (fact_positions_model).
--
-- fx_series_id optionally names a second priced series whose level
-- multiplies the constituent's (currency conversion into the index
-- currency); NULL means no conversion.
--
-- Weights are stored normalized to sum 1 per version; the writer
-- (src/pipelines/analytics/benchmark/definitions.py) validates and
-- normalizes, accepting 100-based input. Under buy_and_hold the stored
-- weight is the weight AT effective_from only: between rebalances
-- holdings drift with prices.
--
-- Append-only like its version: rows are inserted with the version and
-- never changed. DOUBLE PRECISION: analytical weights, no cent-exact
-- reconciliation.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS benchmark_constituent (
    version_id    INTEGER NOT NULL REFERENCES dim_benchmark_version (version_id),
    series_id     INTEGER NOT NULL REFERENCES series_registry (series_id),

    label         TEXT NOT NULL CHECK (length(trim(label)) > 0),
    weight        DOUBLE PRECISION NOT NULL CHECK (weight > 0),
    fx_series_id  INTEGER REFERENCES series_registry (series_id),

    PRIMARY KEY (version_id, series_id)
);

CREATE INDEX IF NOT EXISTS idx_benchmark_constituent_series
    ON benchmark_constituent (series_id);
