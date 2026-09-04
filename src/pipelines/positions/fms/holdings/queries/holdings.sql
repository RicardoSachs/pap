-- holdings.sql
-- ---------------------------------------------------------------
-- FMS extraction query: holdings feed (securities + deposits) from the
-- IDI daily valorization.
--
-- One row per fund per holding per report date. BOTH securities and deposits
-- come from IDI.ValorizacionIDI in this single query; they are split DOWNSTREAM
-- (in the fact transforms) by codigo_sbs — deposits start with '60', everything
-- else is a security. The query itself is type-agnostic.
--
-- Securities vs deposits — a clean mutual exclusion in the source:
--   securities: IdInstrumento <> 0, IdOrdenInversion = 0, CodigoSBS not '60…'
--   deposits:   IdInstrumento = 0,  IdOrdenInversion <> 0, CodigoSBS = '60…'
-- So each line resolves down its own path (all LEFT joins, guarded by <> 0):
--   currency:  securities inst.IdMoneda / deposits oi.IdMoneda  (COALESCEd -> Moneda)
--   class:     securities inst.IdTipoInstrumento -> TipoInstrumento.IndClase
--              (145 = FI, 146 = equity); null for deposits
--   terms:     deposits odp.Tasa / DiasVigencia / IdSecuencialFechaVencimiento;
--              null for securities
--
-- Fund NAV (ValorCuota) and AUM (ValorCartera) from CierreIDI are denormalized
-- onto every line; downstream they are de-duped to one row per (fund, date) into
-- fact_portfolio_valuation.
--
-- STORED DAILY SNAPSHOT (like cash, NOT point-in-time like net_receivables): each
-- row carries its own report date (IdSecuencialFechaIDI), so this is a single
-- set-based RANGE query — no per-day loop. FlgHistorico = 0 selects the current
-- disclosure for each (fund, date).
--
-- Parameters (positional, pyodbc ? style):
--   1) start_date  INT yyyymmdd, inclusive lower bound
--   2) end_date    INT yyyymmdd, inclusive upper bound
--
-- Target staging:    stg_positions_fms_holdings
-- Grain (staging):   (CodigoFondo, CodigoSBS, IdOrdenInversion, IdSecuencialFechaIDI)
--   -> fact_positions_securities: (portfolio_id, security_entity_id, date, source)  [id_orden_inversion = 0]
--   -> fact_positions_deposits:   (portfolio_id, id_orden_inversion, date, source)  [codigo_sbs generic '60…']
--
-- Measures: Cantidad / PrecioPEN / ImportePEN (stocks) + their *Anterior
-- counterparts; MontoInteresVencimientoCupon / OrdenesRenta / AccionesLiberadas
-- / Dividendos / Rescates are per-day cash FLOWS (sum over a range; do NOT sum
-- the stock measures across dates).
--
-- TODO(dev): confirm (CodigoFondo, CodigoSBS, IdOrdenInversion, date) is unique
-- via a diagnose-grain check, and that ImportePEN is populated on deposit rows.
-- ---------------------------------------------------------------

WITH filtered_idi AS (
    SELECT
        i.IdIDI,
        i.IdFondoPension,
        i.IdSecuencialFechaIDI
    FROM FMS.IDI i
    WHERE i.IdSecuencialFechaIDI BETWEEN ? AND ?
)
SELECT
    -- ===================== Tier 1 (common) =====================
    fi.IdSecuencialFechaIDI                       AS IdSecuencialFechaIDI,   -- report date -> `date`
    fond.CodigoFondo                              AS CodigoFondo,
    vi.IdOrdenInversion                           AS IdOrdenInversion,       -- 0 for securities; real order for deposits (grain)
    vi.CodigoSBS                                  AS CodigoSBS,              -- '60%' = deposit, else security
    m.CodigoISO                                   AS CodigoIsoMoneda,        -- securities via Instrumento, deposits via OrdenInversion
    ti.IndClase                                   AS IndClase,               -- 145 FI / 146 equity (securities); null for deposits
    vi.ImportePEN                                 AS ImportePEN,             -- valued amount in soles (Cantidad x PrecioPEN)
    ci.ValorCuota                                 AS ValorCuota,             -- fund NAV (denormalized)
    ci.ValorCartera                               AS ValorCartera,           -- fund AUM (denormalized)

    -- ===================== Tier 1 (security-specific; null on deposit rows) =====================
    vi.Cantidad                                   AS Cantidad,
    vi.PrecioPEN                                  AS PrecioPEN,
    vi.CantidadAnterior                           AS CantidadAnterior,
    vi.PrecioAnteriorPEN                          AS PrecioAnteriorPEN,
    vi.ImporteAnteriorPEN                         AS ImporteAnteriorPEN,
    vi.MontoInteresVencimientoCupon               AS MontoInteresVencimientoCupon,   -- coupon at maturity (flow)
    vi.MontoOrdenesRenta                          AS MontoOrdenesRenta,              -- income orders (flow)
    vi.MontoAccionesLiberadas                     AS MontoAccionesLiberadas,         -- bonus shares / splits (flow)
    vi.MontoDividendos                            AS MontoDividendos,                -- dividends (flow)
    vi.MontoRescates                              AS MontoRescates,                  -- redemptions (flow)

    -- ===================== Tier 1 (deposit-specific; null on security rows) =====================
    odp.Tasa                                      AS Tasa,                   -- deposit rate
    odp.DiasVigencia                              AS DiasVigencia,           -- deposit term (days)
    odp.IdSecuencialFechaVencimiento              AS IdSecuencialFechaVencimiento,   -- deposit maturity (yyyymmdd)

    -- ===================== Tier 2 -> raw_payload =====================
    vi.Factor                                     AS Factor

FROM IDI.ValorizacionIDI vi
JOIN FMS.CierreIDI ci
    ON vi.IdCierreIDI = ci.IdCierreIDI
   AND ci.FlgHistorico = 0
JOIN filtered_idi fi
    ON ci.IdIDI = fi.IdIDI
JOIN FMS.FondoPension fond
    ON fond.IdFondo = fi.IdFondoPension
-- securities path (IdInstrumento <> 0; IdOrdenInversion = 0)
LEFT JOIN FMS.Instrumento inst
    ON inst.IdInstrumento = vi.IdInstrumento
   AND vi.IdInstrumento <> 0
LEFT JOIN FMS.TipoInstrumento ti
    ON ti.IdTipoInstrumento = inst.IdTipoInstrumento
-- deposits path (IdOrdenInversion <> 0; IdInstrumento = 0)
LEFT JOIN FMS.OrdenInversion oi
    ON oi.IdOrdenInversion = vi.IdOrdenInversion
   AND vi.IdOrdenInversion <> 0
LEFT JOIN FMS.OrdenInversionDepositoPlazo odp
    ON odp.IdOrdenInversion = vi.IdOrdenInversion
   AND vi.IdOrdenInversion <> 0
-- currency: whichever path resolved
LEFT JOIN FMS.Moneda m
    ON m.IdMoneda = COALESCE(inst.IdMoneda, oi.IdMoneda);
