-- src/pipelines/prices/sbs/queries/split_dual_listing.sql
-- =============================================================
-- Repair: a codigo_sbs that discovery glued onto another listing's
-- entity (same ISIN, both codes trading daily - e.g. CNQ USD 345387251017
-- and CNQ CAD 345387751017 on entity 1368) gets its own entity, series
-- and price history. One-off; the coexistence test in discovery.py
-- stops new cases.
--
-- Usage (DBeaver, office DB):
--   1. set v_code to the code to split OUT (the one that must leave).
--   2. run the DO block (it is one transaction; it raises and rolls
--      back if the code is unknown or the entity has a single code).
--   3. re-run the backfill so both series are rebuilt from staging:
--        python scripts/backfill_sbs.py --file-type vector_completo
--      Facts are only purged on dates where v_code was staged, so the
--      other listing's history on its own dates is untouched.
--
-- Find candidates first:
--   SELECT entity_id, array_agg(id_value) FROM dim_entity_identifiers
--   WHERE id_type='codigo_sbs' AND source='sbs'
--   GROUP BY entity_id HAVING COUNT(*) > 1;
-- =============================================================

DO $$
DECLARE
    v_code        TEXT := '345387751017';   -- <<< the code to split out
    v_old_entity  INT;
    v_new_entity  INT;
    v_old_series  INT[];
    v_synth_isin  TEXT;
BEGIN
    SELECT entity_id INTO v_old_entity
    FROM dim_entity_identifiers
    WHERE id_type = 'codigo_sbs' AND source = 'sbs' AND id_value = v_code;
    IF v_old_entity IS NULL THEN
        RAISE EXCEPTION 'codigo_sbs % is not registered', v_code;
    END IF;
    IF (SELECT COUNT(*) FROM dim_entity_identifiers
        WHERE entity_id = v_old_entity AND id_type = 'codigo_sbs' AND source = 'sbs') < 2 THEN
        RAISE EXCEPTION 'entity % has a single codigo_sbs - nothing to split', v_old_entity;
    END IF;

    -- 1. New entity + dim_security skeleton (same shape discovery creates).
    INSERT INTO dim_entity (procode, entity_type, name)
    SELECT 'SBS_' || v_code, 'security', name
    FROM dim_entity WHERE entity_id = v_old_entity
    RETURNING entity_id INTO v_new_entity;

    INSERT INTO dim_security (entity_id, security_type)
    SELECT v_new_entity, security_type FROM dim_security WHERE entity_id = v_old_entity;

    -- 2. Move the code. It is the new entity's only code, so it is primary.
    UPDATE dim_entity_identifiers
    SET entity_id = v_new_entity, is_primary = TRUE
    WHERE entity_id = v_old_entity AND id_type = 'codigo_sbs'
      AND source = 'sbs' AND id_value = v_code;

    -- Old entity: if the moved code was its primary, promote the latest-seen survivor.
    UPDATE dim_entity_identifiers
    SET is_primary = TRUE
    WHERE (entity_id, id_type, source, id_value) = (
            SELECT entity_id, id_type, source, id_value
            FROM dim_entity_identifiers
            WHERE entity_id = v_old_entity AND id_type = 'codigo_sbs' AND source = 'sbs'
            ORDER BY last_seen_date DESC NULLS LAST LIMIT 1)
      AND NOT EXISTS (
            SELECT 1 FROM dim_entity_identifiers
            WHERE entity_id = v_old_entity AND id_type = 'codigo_sbs'
              AND source = 'sbs' AND is_primary);

    -- 3. The synthetic ISIN this code trades under (last char is a letter)
    --    leaves the old entity (with its unresolvable '/isin/' Bloomberg alias)
    --    and is recorded on the new one the way _register_x_isin_instrument does.
    SELECT isin INTO v_synth_isin
    FROM stg_prices_sbs_vector_completo
    WHERE codigo_sbs = v_code AND isin ~ '[A-Za-z]$'
    ORDER BY date DESC LIMIT 1;

    IF v_synth_isin IS NOT NULL THEN
        DELETE FROM dim_entity_identifiers
        WHERE entity_id = v_old_entity
          AND id_value IN (v_synth_isin, '/isin/' || v_synth_isin);

        INSERT INTO dim_entity_identifiers (entity_id, id_type, id_value, source, is_primary)
        VALUES (v_new_entity, 'isin_x',           v_synth_isin,            'sbs', TRUE),
               (v_new_entity, 'isin_prefix',      LEFT(v_synth_isin, 11),  'sbs', TRUE),
               (v_new_entity, 'parent_entity_id', v_old_entity::TEXT,      'sbs', TRUE);
    END IF;

    -- 4. Series for the new entity, mirroring the old entity's SBS series.
    INSERT INTO series_registry
        (entity_id, field, domain, source, frequency, default_start_date, status)
    SELECT v_new_entity, field, domain, source, frequency, default_start_date, 'backfill-pending'
    FROM series_registry
    WHERE entity_id = v_old_entity AND source = 'sbs';

    -- 5. Purge the old series on every date the split-out code was staged:
    --    those are the only dates where its price may have overwritten the
    --    other listing's. The backfill re-run restores both from staging.
    SELECT array_agg(series_id) INTO v_old_series
    FROM series_registry WHERE entity_id = v_old_entity AND source = 'sbs';

    DELETE FROM fact_prices fp
    USING (SELECT DISTINCT date FROM stg_prices_sbs_vector_completo WHERE codigo_sbs = v_code) s
    WHERE fp.series_id = ANY(v_old_series) AND fp.date = s.date;

    RAISE NOTICE 'split %: entity % -> new entity % (synthetic isin %). Now re-run the vector_completo backfill.',
        v_code, v_old_entity, v_new_entity, v_synth_isin;
END $$;
