-- 40_stg_prices_sbs_valor_cuota.sql
-- ---------------------------------------------------------------
-- Staging table for the SPP "valor cuota" feed: the SBS variables
-- page scraped daily (last 7 business days, three metrics per AFP x
-- fund) and the monthly historical XLS (valor cuota since 1993).
--
-- LONG format, one row per (afp, fondo, date, load): the standalone
-- monitor stored this as a 48-column wide table, but here the fact
-- destination is fact_prices (long), so staging mirrors that grain.
-- The three SBS metrics travel together because the daily page
-- publishes them side by side; the historical XLS only carries
-- valor_cuota and leaves the other two NULL.
--
-- Column names valor_cuota / cuotas / fondo_soles / fondo are the
-- SBS's own names for the published figures and stay as they come.
--
-- `source` is the feed's source value, 'sbs_spp' (the SPP segment of
-- the public SBS portal; 'sbs' is the extranet vector files the feeds
-- on main own), the same value the fact rows and series_registry carry.
-- `channel` says which SBS publication the row came from:
-- 'daily_page' | 'history_xls'.
--
-- Rows are never updated: every load appends its own copy, keyed by
-- loaded_at, so a restatement is visible as two rows. The facts are
-- derived by src/pipelines/prices/sbs/valor_cuota/transform.py.
-- Loaded by src/pipelines/prices/sbs/valor_cuota/extract.py.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stg_prices_sbs_valor_cuota (
    -- Stable AFP identity (registry key, e.g. 'habitat') + fund type
    afp              TEXT NOT NULL,
    fondo            INTEGER NOT NULL,

    -- The three metrics the SBS publishes per AFP x fund
    valor_cuota      DOUBLE PRECISION,
    cuotas           DOUBLE PRECISION,
    fondo_soles      DOUBLE PRECISION,

    -- Feed source value, 'sbs_spp' (see the banner)
    source           TEXT,
    -- Which SBS publication the row came from: 'daily_page' | 'history_xls'
    channel          TEXT,

    -- Pipeline metadata
    date             DATE NOT NULL,
    loaded_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (afp, fondo, date, loaded_at)
);

-- ---- Convergence for databases created from the fork ---------------
-- The fork's version of this table named the provenance column
-- `fuente`. CREATE TABLE IF NOT EXISTS leaves an existing table as it
-- is, and the loader inserts into `source`: on such a database every
-- staging insert would fail. Rename in place when the old column is
-- there; a no-op everywhere else.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'stg_prices_sbs_valor_cuota' AND column_name = 'fuente'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'stg_prices_sbs_valor_cuota' AND column_name = 'source'
    ) THEN
        ALTER TABLE stg_prices_sbs_valor_cuota RENAME COLUMN fuente TO source;
    END IF;
END $$;

-- `channel` arrived after the first databases were created from this
-- file; CREATE TABLE IF NOT EXISTS leaves them without it.
ALTER TABLE stg_prices_sbs_valor_cuota ADD COLUMN IF NOT EXISTS channel TEXT;

CREATE INDEX IF NOT EXISTS idx_stg_prices_sbs_valor_cuota_date
    ON stg_prices_sbs_valor_cuota (date);
