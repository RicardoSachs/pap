-- 57_benchmark.sql
-- ---------------------------------------------------------------
-- The benchmark of each fund type, as a named thing.
--
-- There is ONE benchmark per fund - that is the decision - but it now
-- has a name of its own ("Renta mixta global 60/40") instead of being
-- known only as SPP_BENCH_F2. The name is what the tablero shows: in
-- the chart legend, in the book and in the composition editor.
--
-- Declaring a benchmark here is also what ENABLES a fund to have one.
-- Before, the set of funds with benchmark was frozen in
-- config/afps.yaml; now adding a row is enough, and the series gets
-- registered on the spot. The yaml list stays as the default for a
-- fresh database.
--
-- The level series itself does not move: it is still
-- SPP_BENCH_F{fondo} / PX_LAST / source 'benchmark' in fact_prices,
-- produced by the chained calculation over benchmark_composicion.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS benchmark (
    fondo        INTEGER PRIMARY KEY,
    nombre       TEXT NOT NULL,
    descripcion  TEXT,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT ck_benchmark_nombre CHECK (length(trim(nombre)) > 0)
);
