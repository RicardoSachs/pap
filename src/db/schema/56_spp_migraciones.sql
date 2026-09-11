-- 56_spp_migraciones.sql
-- ---------------------------------------------------------------
-- Convergence file for the SPP block (50-55).
--
-- Every other schema file is CREATE TABLE IF NOT EXISTS, which is a
-- no-op on a database whose tables already exist: a constraint that
-- changes shape after the first deployment NEVER reaches an older
-- database, and the mismatch only surfaces as a runtime error.
-- (It already happened once: benchmark_composicion's fuente CHECK
-- gained 'manual' in the 2026-09 redesign and had to be ALTERed by
-- hand here.)
--
-- This file runs last (alphabetically after 55_) and re-states the
-- constraints the CODE depends on, idempotently: every block is safe
-- to run on a fresh database and on one created by any earlier
-- version of this branch. Add to it whenever a 50-55 constraint
-- changes - never edit the constraint in place and hope.
-- ---------------------------------------------------------------

-- ---- dim_entity: ON CONFLICT target used by get_or_create_entity_id
-- src/db/queries.py upserts on (procode, entity_type). Databases
-- created before that constraint existed raise InvalidColumnReference
-- on the FIRST registration of the SPP series.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_dim_entity_procode_type'
          AND conrelid = 'dim_entity'::regclass
    ) THEN
        ALTER TABLE dim_entity
            ADD CONSTRAINT uq_dim_entity_procode_type
            UNIQUE (procode, entity_type);
    END IF;
END $$;


-- ---- benchmark_composicion: the 'manual' source
-- Components price from three stores since the 2026-09 redesign
-- (bloomberg / fact / manual). A database created before it keeps the
-- two-value CHECK and rejects every manual component with a
-- check_violation the UI can only show as a 500.
ALTER TABLE benchmark_composicion
    DROP CONSTRAINT IF EXISTS benchmark_composicion_fuente_check;
ALTER TABLE benchmark_composicion
    DROP CONSTRAINT IF EXISTS ck_benchmark_composicion_fuente;
ALTER TABLE benchmark_composicion
    ADD CONSTRAINT ck_benchmark_composicion_fuente
    CHECK (fuente IN ('bloomberg', 'fact', 'manual'));

ALTER TABLE benchmark_composicion
    DROP CONSTRAINT IF EXISTS benchmark_composicion_fx_fuente_check;
ALTER TABLE benchmark_composicion
    DROP CONSTRAINT IF EXISTS ck_benchmark_composicion_fx_fuente;
ALTER TABLE benchmark_composicion
    ADD CONSTRAINT ck_benchmark_composicion_fx_fuente
    CHECK (fx_fuente IN ('bloomberg', 'fact', 'manual'));
