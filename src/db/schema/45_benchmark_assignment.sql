-- 45_benchmark_assignment.sql
-- ---------------------------------------------------------------
-- benchmark_assignment: which entity a benchmark is the benchmark OF.
--
-- A composite index is declared against something - here the house's
-- fund of a given type (dim_entity 'fund', e.g. SPP_PROFUTURO_F2) - and
-- the tablero shows it inside that fund's block of the return tables.
-- The link is NOT dim_portfolio.parent_entity_id: that column bridges
-- the benchmark portfolio to its OWN entity, the one that carries the
-- level series (see src/pipelines/analytics/benchmark/definitions.py),
-- and every join of the analytics module reads it that way.
--
-- Grain: one assignment per benchmark (an index measures one thing);
-- assigning again replaces it (definitions.assign). It is a link, not
-- a definition, so it carries no history: the versions and the levels
-- of the benchmark do not change with where it is shown.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS benchmark_assignment (
    portfolio_id INTEGER PRIMARY KEY REFERENCES dim_portfolio (portfolio_id),
    entity_id    INTEGER NOT NULL REFERENCES dim_entity (entity_id),
    assigned_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_benchmark_assignment_entity
    ON benchmark_assignment (entity_id);
