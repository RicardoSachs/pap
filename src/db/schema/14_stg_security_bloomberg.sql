-- =============================================================
-- stg_security_bloomberg
-- Raw security attributes as returned by Bloomberg API calls.
-- Long format: one row per (id, field, loaded_at)
-- Populated by pipelines/dim/bloomberg/security/extract.py.
-- Resolution step reads this table and writes to dim_security
-- and dim_entity_identifiers.
-- Rows are never deleted after resolution - retained for audit
-- and re-resolution if priority rules change.
-- =============================================================

CREATE TABLE IF NOT EXISTS stg_security_bloomberg (
    stg_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parsekyable TEXT NOT NULL,
    field TEXT NOT NULL,
    value TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Allow multiple loads over time - uniqueness is per ticker/field/loaded_at
    UNIQUE (parsekyable, field, loaded_at)
);

CREATE INDEX IF NOT EXISTS idx_stg_security_bloomberg_ticker
    ON stg_security_bloomberg (parsekyable);

CREATE INDEX IF NOT EXISTS idx_stg_security_bloomberg_field
    ON stg_security_bloomberg (field);

CREATE INDEX IF NOT EXISTS idx_stg_security_bloomberg_loaded
    ON stg_security_bloomberg (loaded_at);
