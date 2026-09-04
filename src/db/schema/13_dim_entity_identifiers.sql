-- =============================================================
-- dim_entity_identifiers
-- Maps internal entity_id to all vendor-specific identifiers.
-- One row per (entity_id, id_type, source) combination.
-- Universal translator between internal surrogate keys and
-- vendor-native identifiers used by pipeline extractors.
-- Populated from seeds/identifiers.csv and enrichment pipelines.
-- =============================================================

CREATE TABLE IF NOT EXISTS dim_entity_identifiers (
    entity_id INTEGER NOT NULL REFERENCES dim_entity (entity_id),
    id_type TEXT NOT NULL, -- parsekyable / isin / cusip / sedol / codigo_sbs
    id_value TEXT NOT NULL,
    source TEXT NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (entity_id, id_type, source)
);

-- Fast lookup by value: resolves entity_id from a vendor identifier
CREATE INDEX IF NOT EXISTS idx_entity_identifiers_value
    ON dim_entity_identifiers (id_type, id_value);

-- Fast lookup by entity; retrieves all identifiers for a given entity
CREATE INDEX IF NOT EXISTS idx_entity_identifiers_entity
    ON dim_entity_identifiers (entity_id);
