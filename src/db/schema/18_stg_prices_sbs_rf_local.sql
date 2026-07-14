
-- 18_stg_prices_sbs_rf_local.sql
-- ---------------------------------------------------------------
-- Staging table for SBS local fixed income file (rf_local).
-- Contains full bond analytics: YTM, spreads, duration, ratings,
-- coupon dates, clean/dirty prices.
-- One row per instrument per reference_date per load.
-- Loaded by pipeline/prices/sbs/rf_local/extract.py.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stg_prices_sbs_rf_local (
    -- SBS identifiers
    codigo_sbs                  TEXT NOT NULL,
    isin                        TEXT,
    nemonico                    TEXT,

    -- Instrument metadata (slowly changing - also fed to dim_security_bond)
    tipo_instrumento            TEXT,
    emisor                      TEXT,
    moneda                      TEXT,
    valor_facial                DOUBLE PRECISION,
    origen_precio               TEXT,   -- source of price (e.g. BVL, Bloomberg, SBS)
    fecha_emision               DATE,
    fecha_vencimiento           DATE,
    tasa_cupon                  DOUBLE PRECISION,
    margen_libor                DOUBLE PRECISION,
    rating                      TEXT,
    ultimo_cupon                DATE,
    proximo_cupon               DATE,

    -- Daily price facts (change every day)
    precio_limpio_monto         DOUBLE PRECISION,
    precio_limpio_pct           DOUBLE PRECISION,
    precio_sucio_monto          DOUBLE PRECISION,
    precio_sucio_pct            DOUBLE PRECISION,
    interes_corrido_monto       DOUBLE PRECISION,
    tir                         DOUBLE PRECISION,
    spreads                     DOUBLE PRECISION,
    tir_sin_opciones            DOUBLE PRECISION,
    duracion                    DOUBLE PRECISION,
    variacion_precio_limpio     DOUBLE PRECISION,
    variacion_precio_sucio      DOUBLE PRECISION,
    variacion_tir               DOUBLE PRECISION,

    -- Pipeline metadata
    date                        DATE NOT NULL,
    loaded_at                   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (codigo_sbs, date, loaded_at)
);

CREATE INDEX IF NOT EXISTS idx_stg_sbs_rf_local_date
    ON stg_prices_sbs_rf_local (date);

CREATE INDEX IF NOT EXISTS idx_stg_sbs_rf_local_isin
    ON stg_prices_sbs_rf_local (isin);
