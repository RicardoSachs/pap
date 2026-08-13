-- 28_stg_positions_fms_cash.sql
-- ---------------------------------------------------------------
-- stg_positions_fms_cash: raw landing for the FMS cash (current-
-- account) feed. One of the FMS positions feeds alongside forwards,
-- investment_portfolio (securities), deposits and net_receivables.
--
-- Grain: (codigo_fondo, codigo_institucion, codigo_iso_moneda, date)
-- — one row per fund per institution (bank) per currency per business
-- date. FMS identifies a cash account by institution, so institution is
-- part of the grain (a fund holds cash across several banks per currency).
-- FMS exposes both a code (IdEntidad -> codigo_institucion, the stable
-- grain key) and a readable name (Institucion -> nombre_institucion, for
-- display). Cash is a balance, not a security: there is no codigo_sbs and
-- no dim_entity resolution (Model A — cash gets its own fact table, not
-- synthetic per-currency entities).
--
-- date is a proper DATE, NOT the int yyyymmdd FMS uses; conversion
-- happens in extract/transform. id_secuencial_fecha_reporte is kept
-- as INTEGER for traceability back to the source row.
--
-- Tier 1 attributes are typed columns; anything else the query emits
-- lands in raw_payload JSONB (MontoTotalOriginal, CodigoInstrumento).
--
-- soles: monto_total_soles (MontoTotalSoles) comes directly from the FMS
-- source (IDI.AnexoIVStock) — cash provides the soles amount itself, so
-- there is NO FX-spot join here (unlike forwards). saldo_contable is the
-- balance in the account's own currency.
--
-- NUMERIC (not DOUBLE PRECISION) for monetary fields — cent-exact
-- reconciliation against custody/accounting, matching the positions
-- domain convention.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stg_positions_fms_cash (
    -- Audit / batch
    batch_id                      TEXT NOT NULL,                -- e.g. 'fms_cash_20260622_081532'
    loaded_at                     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Tier 1: typed business attributes
    id_secuencial_fecha_reporte   INTEGER NOT NULL,             -- FMS yyyymmdd int (traceability)
    date                          DATE NOT NULL,                -- DATE-converted from above
    codigo_fondo                  TEXT NOT NULL,                -- fund code; -> dim_portfolio.procode
    codigo_institucion            TEXT NOT NULL,                -- institution code (IdEntidad), grain key
    codigo_iso_moneda             TEXT NOT NULL,                -- currency of the balance (grain)
    nombre_institucion            TEXT,                         -- institution display name (Institucion)
    saldo_contable                NUMERIC(18, 4),               -- accounting balance in codigo_iso_moneda (SaldoContable)
    monto_total_soles             NUMERIC(18, 4),               -- total amount in soles (MontoTotalSoles), from source
    tasa_interes                  NUMERIC(12, 8),               -- account interest rate (null if non-remunerated)
    interes_acumulado             NUMERIC(18, 4),               -- cumulative interest to date

    -- Tier 2: full vendor payload for forensic / future analysis
    raw_payload                   JSONB,

    PRIMARY KEY (codigo_fondo, codigo_institucion, codigo_iso_moneda, date)
);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_cash_batch
    ON stg_positions_fms_cash (batch_id);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_cash_date
    ON stg_positions_fms_cash (date);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_cash_fondo
    ON stg_positions_fms_cash (codigo_fondo);

-- ---------------------------------------------------------------
-- Identifier resolution expectations (used by transform.py):
--   codigo_fondo -> dim_portfolio.procode (source='fms')
-- ---------------------------------------------------------------
