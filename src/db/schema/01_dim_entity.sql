-- =============================================================
-- dim_entity
-- Anchor table for all entities (securities, macro variables, etc.)
-- One row per unique real-world entity regardless of domain.
-- =============================================================

CREATE TABLE IF NOT EXISTS dim_entity (
    entity_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    procode TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('security', 'macro', 'index', 'fund')),
    name TEXT,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
