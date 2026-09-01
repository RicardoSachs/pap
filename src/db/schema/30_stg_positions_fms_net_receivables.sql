-- 30_stg_positions_fms_net_receivables.sql
-- ---------------------------------------------------------------
-- stg_positions_fms_net_receivables: raw landing for the FMS net
-- receivables (cuentas por cobrar netas) feed. One of the FMS positions
-- feeds alongside forwards, cash, investment_portfolio (securities) and
-- deposits.
--
-- Grain: (codigo_fondo, codigo_iso_moneda, date) — one row per fund per
-- currency per as-of date. Both legs are carried: monto_cobrar
-- (receivables, CxC) and monto_pagar (payables, CxP); the net is
-- monto_cobrar - monto_pagar, derived downstream. Ephemeral, like cash:
-- no codigo_sbs and no dim_entity resolution (Model A — own fact table).
--
-- POINT-IN-TIME date: the source (FMS.CuentaCobrarPagar via the two
-- R_CONEX3_CxC/CxP procedures) reconstructs the OPEN balance AS OF a single
-- day. `date` is the as-of day the extract computed the row for — it is
-- stamped by extract.py (the per-day loop variable), NOT read from a source
-- column, so there is no id_secuencial_fecha_* column here. `date` in
-- yyyymmdd form is the exact reproduction key for the FMS procedures.
--
-- NUMERIC (not DOUBLE PRECISION) for monetary fields — cent-exact
-- reconciliation, matching the positions domain convention.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stg_positions_fms_net_receivables (
    -- Audit / batch
    batch_id                      TEXT NOT NULL,                -- e.g. 'fms_net_receivables_20260828_081532'
    loaded_at                     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Tier 1: typed business attributes
    date                          DATE NOT NULL,                -- as-of day (stamped by extract)
    codigo_fondo                  TEXT NOT NULL,                -- fund code; -> dim_portfolio.procode
    codigo_iso_moneda             TEXT NOT NULL,                -- currency of the balance (grain)
    monto_cobrar                  NUMERIC(18, 4),               -- receivables (CxC), sum of ABS(Importe)
    monto_pagar                   NUMERIC(18, 4),               -- payables (CxP), sum of ABS(Importe)

    -- Tier 2: full vendor payload (empty here — source is aggregated)
    raw_payload                   JSONB,

    PRIMARY KEY (codigo_fondo, codigo_iso_moneda, date)
);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_net_receivables_batch
    ON stg_positions_fms_net_receivables (batch_id);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_net_receivables_date
    ON stg_positions_fms_net_receivables (date);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_net_receivables_fondo
    ON stg_positions_fms_net_receivables (codigo_fondo);

-- ---------------------------------------------------------------
-- Identifier resolution expectations (used by transform.py):
--   codigo_fondo -> dim_portfolio.procode (source='fms')
-- ---------------------------------------------------------------
