
-- 17_stg_prices_sbs_vector_completo.sql
-- ---------------------------------------------------------------
-- Staging table for SBS daily general prices file (vector_completo).
-- Contains shared columns across all instrument types.
-- One row per instrument per reference_date per load.
-- Loaded by pipeline/prices/sbs/vector_completo/extract.py.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stg_prices_sbs_vector_completo (
    -- SBS identifiers
    codigo_sbs       TEXT NOT NULL,
    isin             TEXT,
    nemonico         TEXT,

    -- Instrument metadata (slowly changing - also fed to dim tables)
    tipo_instrumento TEXT,
    emisor           TEXT,
    moneda           TEXT,

    -- Daily price facts
    precio           DOUBLE PRECISION,
    variacion        DOUBLE PRECISION,

    -- Pipeline metadata
    date             DATE NOT NULL,
    loaded_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (codigo_sbs, date, loaded_at)
);

CREATE INDEX IF NOT EXISTS idx_stg_sbs_vector_completo_date
    ON stg_prices_sbs_vector_completo (date);

CREATE INDEX IF NOT EXISTS idx_stg_sbs_vector_completo_isin
    ON stg_prices_sbs_vector_completo (isin);
