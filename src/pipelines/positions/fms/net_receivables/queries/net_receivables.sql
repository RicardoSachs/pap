-- net_receivables.sql
-- ---------------------------------------------------------------
-- FMS extraction query: net receivables (cuentas por cobrar netas) feed.
--
-- Consolidates the two FMS point-in-time procedures (receivables R_CONEX3_CxC
-- with IdIndicador=1, payables with IdIndicador=2, both over
-- FMS.CuentaCobrarPagar) into ONE query that returns BOTH legs per
-- (fund, currency) for a single as-of date. Net = MontoCobrar - MontoPagar,
-- derived downstream.
--
-- POINT-IN-TIME / ONE DATE (unlike cash/forwards): this reconstructs the OPEN
-- balance AS OF a single day — it does not scan a date range. extract.py loops
-- over the business days in the requested range, runs this once per day, and
-- stamps the `date` column itself (the as-of day is the loop variable, so it is
-- NOT selected here — the query returns only the business data).
--
-- Parameters (positional, pyodbc ? style) — the SAME as-of date, bound THREE
-- times, in statement order:
--   1) as_of_date  INT yyyymmdd  (MonedaCambio join: FX rate as of that day)
--   2) as_of_date  INT yyyymmdd  (IdSecuencialFechaOperacion <= as_of)
--   3) as_of_date  INT yyyymmdd  (IdSecuencialFechaLiquidacionReal > as_of)
--
-- Soles: MonedaCambio (NOT the stale TipoCambioSpot pattern — same lesson as
-- forwards.sql) provides the FMS valuation rate. PEN needs no rate (factor 1).
-- Deliberately NO COALESCE(rate, 1): a missing FX row for a non-PEN currency
-- must surface as NULL soles (caught by log_null_counts downstream), never be
-- silently valued at 1.0. TipoCambio is carried as PROVENANCE for the soles
-- figures only — fact_prices (SBS tipo_cambio) is the system's FX historian.
--
-- Target staging:    stg_positions_fms_net_receivables
-- Grain:             (CodigoFondo, CodigoIsoMoneda, <date stamped by extract>)
--
-- OUTPUT CONTRACT — transform.py depends on these output column names:
--   Tier 1 (typed staging columns):
--     CodigoFondo, CodigoIsoMoneda, MontoCobrar, MontoPagar,
--     MontoCobrarSoles, MontoPagarSoles, TipoCambio
--   `date` is added by extract.py (not selected here).
--   Tier 2 -> raw_payload: none (the source is already aggregated per currency).
--
-- TODO(dev) — confirm/finalize before running:
--   (a) IndEstado: the sketch was missing the operator. This assumes
--       4168 = OPEN/pending and 4169 = SETTLED (kept only if it settled AFTER
--       the as-of date). Verify those two state codes.
--   (b) Currency: the procs emit M.Simbolo; this uses M.CodigoISO so codes match
--       fact_positions_cash. Switch back to Simbolo if that's what you index on.
-- ---------------------------------------------------------------

SELECT
    -- ===================== Tier 1 =====================
    FP.CodigoFondo                                                     AS CodigoFondo,
    M.CodigoISO                                                        AS CodigoIsoMoneda,   -- TODO(b): Simbolo vs CodigoISO
    SUM(CASE WHEN T.IdIndicador = 1 THEN ABS(CCP.Importe) ELSE 0 END)  AS MontoCobrar,       -- receivables (CxC)
    SUM(CASE WHEN T.IdIndicador = 2 THEN ABS(CCP.Importe) ELSE 0 END)  AS MontoPagar,        -- payables    (CxP)

    -- Soles legs: NULL when the FX rate is missing for a non-PEN currency
    -- (fail-visible; never silently valued at 1.0)
    SUM(CASE WHEN T.IdIndicador = 1 THEN ABS(CCP.Importe) ELSE 0 END)
        * CASE WHEN M.CodigoISO = 'PEN' THEN 1 ELSE mc.TipoCambio END  AS MontoCobrarSoles,
    SUM(CASE WHEN T.IdIndicador = 2 THEN ABS(CCP.Importe) ELSE 0 END)
        * CASE WHEN M.CodigoISO = 'PEN' THEN 1 ELSE mc.TipoCambio END  AS MontoPagarSoles,

    -- Provenance: the FMS rate used for this row's soles figures
    CASE WHEN M.CodigoISO = 'PEN' THEN 1 ELSE mc.TipoCambio END        AS TipoCambio

FROM FMS.CuentaCobrarPagar CCP
JOIN FMS.FondoPension FP ON FP.IdFondo  = CCP.IdFondo
JOIN FMS.Moneda       M  ON M.IdMoneda  = CCP.IdMoneda
JOIN FMS.Indicador    T  ON T.Id        = CCP.IndCobrarPagar
LEFT JOIN FMS.MonedaCambio mc
       ON mc.IdFechaMonedaCambio = ?                                                -- as-of (bind #1)
      AND mc.IdMoneda            = CCP.IdMoneda
WHERE CCP.FlgActivo = 1
  AND T.IdIndicador IN (1, 2)
  AND CCP.IdSecuencialFechaOperacion <= ?                                           -- as-of (bind #2)
  AND (CCP.IndEstado = 4168                                                         -- TODO(a): OPEN/pending
       OR (CCP.IndEstado = 4169 AND CCP.IdSecuencialFechaLiquidacionReal > ?))      -- as-of (bind #3); settled after
GROUP BY
    FP.CodigoFondo,
    M.CodigoISO,
    mc.TipoCambio;
