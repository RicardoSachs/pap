-- 13_dim_entity_identifiers.sql
-- =============================================================
-- dim_entity_identifiers
-- Maps internal entity_id to all vendor-specific identifiers.
-- Universal translator between internal surrogate keys and
-- vendor-native identifiers used by pipeline extractors.
-- Populated from seeds/identifiers.csv, the SBS discovery module
-- (src/pipelines/prices/sbs/discovery.py) and enrichment pipelines.
--
-- MULTI-VALUED: one row per (entity_id, id_type, source, id_value).
-- Real-world codes get re-issued - SBS re-codes instruments, issuers
-- change ISINs - so every value ever observed persists as an ALIAS
-- and exactly one per (entity_id, id_type, source) is flagged
-- is_primary (the current code; enforced by the partial unique index).
-- first/last_seen_date bound each value's observation window, and
-- promotion to primary happens only on the newest observation (see
-- upsert_entity_identifier in src/db/queries.py).
--
-- Who queries what:
--   vw_entity_identifier_current (below) - display/series joins that
--     want ONE value per key (queries.py getters, web services).
--   base table - resolution paths that must match ANY historical
--     value: holdings' codigo_sbs->entity map, the SBS backfill fact
--     joins, resolve_entity_id_from_identifier, discovery diffs.
--
-- id_type values: parsekyable / isin / cusip / sedol / codigo_sbs
-- (dashless canonical form) / isin_x / isin_prefix / parent_entity_id
-- / moneda_nocional / moneda_contraparte / fuente.
-- =============================================================

CREATE TABLE IF NOT EXISTS dim_entity_identifiers (
    entity_id INTEGER NOT NULL REFERENCES dim_entity (entity_id),
    id_type TEXT NOT NULL,
    id_value TEXT NOT NULL,
    source TEXT NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_date DATE,                       -- earliest observation (NULL = unknown)
    last_seen_date DATE,                        -- latest observation (drives primacy)
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (entity_id, id_type, source, id_value)
);

-- Exactly one CURRENT value per (entity, id_type, source)
CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_identifiers_primary
    ON dim_entity_identifiers (entity_id, id_type, source)
    WHERE is_primary;

-- Fast lookup by value: resolves entity_id from a vendor identifier
CREATE INDEX IF NOT EXISTS idx_entity_identifiers_value
    ON dim_entity_identifiers (id_type, id_value);

-- Fast lookup by entity; retrieves all identifiers for a given entity
CREATE INDEX IF NOT EXISTS idx_entity_identifiers_entity
    ON dim_entity_identifiers (entity_id);

-- The one-row-per-key face of the table: current identifiers only.
-- Join THIS (not the base table) wherever a fan-out would duplicate
-- rows - the partial unique index above guarantees single rows here.
CREATE OR REPLACE VIEW vw_entity_identifier_current AS
SELECT entity_id, id_type, id_value, source, first_seen_date, last_seen_date
FROM dim_entity_identifiers
WHERE is_primary;
