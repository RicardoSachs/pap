
-- =============================================================
-- dim_security
-- Domain-specific attributes for entity_type = 'security'
-- SCD Type 1 for now: attributes are overwritten in place.
-- =============================================================

CREATE TABLE IF NOT EXISTS dim_security (
    security_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_id INTEGER NOT NULL UNIQUE REFERENCES dim_entity (entity_id),
    -- parsekyable TEXT,
    -- isin TEXT,
    ticker TEXT,
    name TEXT,
    short_name TEXT,
    security_name TEXT,
    sec_num_des TEXT,
    currency TEXT,
    country TEXT,
    exchange TEXT,
    market_sector TEXT,
    security_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
