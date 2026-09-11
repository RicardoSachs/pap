-- 53_benchmark_composicion.sql
-- ---------------------------------------------------------------
-- Composition of the SPP benchmark per fund type: a basket of
-- priced series with weights, VERSIONED by effective date.
--
-- A rebalance never edits rows - it inserts the full new basket
-- under a new vigente_desde. The composition that governed any past
-- date is therefore always reproducible, and the benchmark level
-- series (SPP_BENCH_F{n} in fact_prices) can be regenerated from
-- scratch at any time by the calculation in
-- src/pipelines/prices/sbs/valor_cuota/benchmark_composicion.py.
--
-- Components price from any of THREE stores (fuente):
--   'bloomberg' -> bloomberg_serie/bloomberg_dato (BBG registry)
--   'fact'      -> series_registry/fact_prices (pipeline spine)
--   'manual'    -> serie_manual/serie_manual_dato (keyed-in data
--                  for components no vendor provides)
-- fx_* optionally names a second priced series whose level multiplies
-- the component's (currency conversion); NULL means no conversion.
--
-- Weights are stored normalized to sum 1 per (fondo, vigente_desde);
-- the writer validates and normalizes (accepts 100-based input).
-- Between rebalances weights DRIFT with prices (buy-and-hold): the
-- stored peso is the weight AT the rebalance date only.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS benchmark_composicion (
    fondo            INTEGER NOT NULL,
    vigente_desde    DATE NOT NULL,

    -- What the component is (display) and where it prices from.
    -- The CHECKs are NAMED and re-stated in 56_spp_migraciones.sql so
    -- that a database created by an earlier version converges: a
    -- CREATE TABLE IF NOT EXISTS never alters what already exists.
    etiqueta         TEXT NOT NULL,
    fuente           TEXT NOT NULL
        CONSTRAINT ck_benchmark_composicion_fuente
        CHECK (fuente IN ('bloomberg', 'fact', 'manual')),
    ref_id           INTEGER NOT NULL,

    -- Weight at the rebalance date, normalized to sum 1 per basket
    peso             NUMERIC(9, 6) NOT NULL CHECK (peso > 0),

    -- Optional FX leg: component price is multiplied by this series
    fx_fuente        TEXT
        CONSTRAINT ck_benchmark_composicion_fx_fuente
        CHECK (fx_fuente IN ('bloomberg', 'fact', 'manual')),
    fx_ref_id        INTEGER,

    creado_en        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (fondo, vigente_desde, fuente, ref_id),
    CHECK ((fx_fuente IS NULL) = (fx_ref_id IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_benchmark_composicion_fondo
    ON benchmark_composicion (fondo, vigente_desde);
