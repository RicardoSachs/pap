-- =============================================================
-- series_registry
-- Operational registry. One row per ticker-field-source combination
-- This is the spine of the system: pipelines query here at runtime
-- to determine what to process and how
-- =============================================================

CREATE TABLE IF NOT EXISTS series_registry (
    series_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES dim_entity (entity_id),

    -- Series identity
    field TEXT NOT NULL,
    domain TEXT NOT NULL CHECK (domain IN ('prices', 'fundamentals', 'macro')),
    source TEXT NOT NULL,

    -- Scheduling and pipeline behavior
    frequency TEXT NOT NULL,
    default_start_date DATE,
    status TEXT NOT NULL DEFAULT 'backfill-pending'
        CHECK (status IN ('backfill-pending', 'active', 'suspended', 'inactive', 'error-hold')),

    -- Release metadata
    release_pattern TEXT CHECK (release_pattern IN ('fixed', 'irregular', 'poll') OR release_pattern IS NULL),
    release_lag_days INTEGER,
    allow_revisions BOOLEAN NOT NULL DEFAULT FALSE,
    revision_lookback INTEGER,

    -- Audit and operational tracking
    last_run_at TIMESTAMPTZ,
    last_run_status TEXT CHECK (last_run_status IN ('success', 'failure', 'partial') OR last_run_status IS NULL),
    last_loaded_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (entity_id, field, source)
);

CREATE INDEX IF NOT EXISTS idx_series_registry_domain
    ON series_registry (domain);

CREATE INDEX IF NOT EXISTS idx_series_registry_status
    ON series_registry (status);

CREATE INDEX IF NOT EXISTS idx_series_registry_frequency
    ON series_registry (frequency);

CREATE INDEX IF NOT EXISTS idx_series_registry_entity
    ON series_registry (entity_id);
