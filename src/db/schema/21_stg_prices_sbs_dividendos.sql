-- 21_stg_prices_sbs_dividendos.sql
-- ---------------------------------------------------------------
-- Staging table for SBS daily dividends file (dividendos).
-- Contains dividend adjustment factors and delivery types.
-- One row per instrument per reference_date per load.
-- Loaded by pipeline/prices/sbs/dividendos/extract.py.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stg_prices_sbs_dividendos (
    -- Reference date from file (FECHA VECTOR)
    fecha_vector         DATE,

    -- SBS identifiers
    codigo_sbs           TEXT NOT NULL,
    isin                 TEXT,
    nemonico             TEXT,

    -- Instrument metadata
    emisor               TEXT,
    moneda               TEXT,

    -- Dividend facts
    factor_ajuste     DOUBLE PRECISION,
    tipo_entrega         TEXT,

    -- Pipeline metadata
    date                 DATE NOT NULL,
    loaded_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (codigo_sbs, date, loaded_at)
);

CREATE INDEX IF NOT EXISTS idx_stg_sbs_dividendos_date
    ON stg_prices_sbs_dividendos (date);

CREATE INDEX IF NOT EXISTS idx_stg_sbs_dividendos_isin
    ON stg_prices_sbs_dividendos (isin);
