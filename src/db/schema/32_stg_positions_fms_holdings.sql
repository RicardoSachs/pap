-- 32_stg_positions_fms_holdings.sql
-- ---------------------------------------------------------------
-- stg_positions_fms_holdings: raw landing for the FMS holdings feed
-- (securities + deposits) from the IDI daily valorization. One shared
-- staging table; downstream it fans out to three facts:
--   fact_positions_securities  (codigo_sbs NOT '60…', entity-resolved)
--   fact_positions_deposits    (codigo_sbs '60…', keyed on id_orden_inversion)
--   fact_portfolio_valuation   (deduped per fund/date: valor_cuota + valor_cartera)
--
-- Grain: (codigo_fondo, codigo_sbs, id_orden_inversion, date). For securities
-- id_orden_inversion is 0 (one row per fund/security/date); for deposits it is
-- the distinct order (their '60…' codigo_sbs is not unique).
--
-- date derives from id_secuencial_fecha_idi (the report date, a real source
-- column — cash pattern). NAV/AUM are denormalized onto every line.
--
-- Type-specific columns are nullable on the other type's rows (security
-- measures null on deposits; tasa/dias/vencimiento null on securities).
--
-- NUMERIC (not DOUBLE PRECISION) for monetary fields — positions convention.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stg_positions_fms_holdings (
    -- Audit / batch
    batch_id                          TEXT NOT NULL,
    loaded_at                         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Grain + common
    id_secuencial_fecha_idi           INTEGER NOT NULL,          -- FMS yyyymmdd report date (traceability)
    date                              DATE NOT NULL,             -- DATE-converted from above
    codigo_fondo                      TEXT NOT NULL,             -- fund; -> dim_portfolio.procode
    codigo_sbs                        TEXT NOT NULL,             -- '60%' = deposit, else security
    id_orden_inversion                INTEGER NOT NULL,          -- 0 for securities; order id for deposits
    codigo_iso_moneda                 TEXT,                      -- currency
    ind_clase                         INTEGER,                   -- 145 FI / 146 equity (securities); null deposits
    importe_pen                       NUMERIC(18, 4),            -- valued amount in soles
    valor_cuota                       NUMERIC(18, 8),            -- fund NAV (denormalized)
    valor_cartera                     NUMERIC(18, 4),            -- fund AUM (denormalized)

    -- Security-specific (null on deposit rows)
    cantidad                          NUMERIC(24, 8),
    precio_pen                        NUMERIC(18, 8),
    cantidad_anterior                 NUMERIC(24, 8),
    precio_anterior_pen               NUMERIC(18, 8),
    importe_anterior_pen              NUMERIC(18, 4),
    monto_intereses_vencimiento_cupon NUMERIC(18, 4),           -- coupon at maturity (flow)
    monto_ordenes_renta               NUMERIC(18, 4),           -- income orders (flow)
    monto_acciones_liberadas          NUMERIC(18, 4),           -- bonus shares / splits (flow)
    monto_dividendos                  NUMERIC(18, 4),           -- dividends (flow)
    monto_rescates                    NUMERIC(18, 4),           -- redemptions (flow)

    -- Deposit-specific (null on security rows)
    tasa                              NUMERIC(12, 8),           -- deposit rate
    dias_vigencia                     INTEGER,                  -- deposit term (days)
    id_secuencial_fecha_vencimiento   INTEGER,                  -- deposit maturity (yyyymmdd)

    -- Tier 2
    raw_payload                       JSONB,

    PRIMARY KEY (codigo_fondo, codigo_sbs, id_orden_inversion, date)
);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_holdings_batch
    ON stg_positions_fms_holdings (batch_id);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_holdings_date
    ON stg_positions_fms_holdings (date);

CREATE INDEX IF NOT EXISTS idx_stg_positions_fms_holdings_fondo
    ON stg_positions_fms_holdings (codigo_fondo);
