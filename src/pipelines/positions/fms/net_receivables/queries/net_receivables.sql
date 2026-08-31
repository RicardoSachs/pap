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
-- over the business days in the requested range and runs this once per day, so
-- the parameter is a single as-of date (NOT a BETWEEN range). The date is
-- echoed back into the result (IdSecuencialFechaReporte) so the transform can
-- derive `date` exactly like cash.
--
-- Parameter (positional, pyodbc ? style):
--   1) as_of_date  INT yyyymmdd — the day whose open balance to reconstruct.
--
-- Target staging:    stg_positions_fms_net_receivables
-- Grain:             (CodigoFondo, CodigoIsoMoneda, as_of_date)
--
-- OUTPUT CONTRACT — transform.py depends on these output column names:
--   Tier 1 (typed staging columns):
--     IdSecuencialFechaReporte (= the as-of date, echoed for the `date` column),
--     CodigoFondo, CodigoIsoMoneda, MontoCobrar, MontoPagar
--     [optional soles: MontoCobrarSoles, MontoPagarSoles]
--   Tier 2 -> raw_payload: none (the source is already aggregated per currency).
--
-- TODO(dev) — confirm/finalize before running:
--   (a) IndEstado: the sketch was missing the operator. This assumes
--       4168 = OPEN/pending and 4169 = SETTLED (kept only if it settled AFTER
--       the as-of date). Verify those two state codes.
--   (b) Currency: the procs emit M.Simbolo; this uses M.CodigoISO so codes match
--       fact_positions_cash. Switch back to Simbolo if that's what you index on.
--   (c) Soles: the procs give NO soles figure. To carry soles, uncomment the
--       FMS.MonedaCambio LEFT JOIN, the two *Soles select columns, and add
--       mc.TipoCambio to GROUP BY (same FX pattern as forwards.sql). Otherwise
--       store original-currency amounts only.
-- ---------------------------------------------------------------

SET NOCOUNT ON;
DECLARE @asof INT = ?;

SELECT
    -- ===================== Tier 1 =====================
    @asof                                                              AS IdSecuencialFechaReporte,
    FP.CodigoFondo                                                     AS CodigoFondo,
    M.CodigoISO                                                        AS CodigoIsoMoneda,   -- TODO(b): Simbolo vs CodigoISO
    SUM(CASE WHEN T.IdIndicador = 1 THEN ABS(CCP.Importe) ELSE 0 END)  AS MontoCobrar,       -- receivables (CxC)
    SUM(CASE WHEN T.IdIndicador = 2 THEN ABS(CCP.Importe) ELSE 0 END)  AS MontoPagar         -- payables    (CxP)

    -- ---- optional soles (TODO(c): uncomment these + the join + GROUP BY below) ----
    -- , SUM(CASE WHEN T.IdIndicador = 1 THEN ABS(CCP.Importe) ELSE 0 END) * COALESCE(mc.TipoCambio, 1) AS MontoCobrarSoles
    -- , SUM(CASE WHEN T.IdIndicador = 2 THEN ABS(CCP.Importe) ELSE 0 END) * COALESCE(mc.TipoCambio, 1) AS MontoPagarSoles

FROM FMS.CuentaCobrarPagar CCP
JOIN FMS.FondoPension FP ON FP.IdFondo  = CCP.IdFondo
JOIN FMS.Moneda       M  ON M.IdMoneda  = CCP.IdMoneda
JOIN FMS.Indicador    T  ON T.Id        = CCP.IndCobrarPagar
-- LEFT JOIN FMS.MonedaCambio mc                                        -- TODO(c): enable for soles
--        ON mc.IdFechaMonedaCambio = @asof AND mc.IdMoneda = CCP.IdMoneda
WHERE CCP.FlgActivo = 1
  AND T.IdIndicador IN (1, 2)
  AND CCP.IdSecuencialFechaOperacion <= @asof
  AND (CCP.IndEstado = 4168                                                        -- TODO(a): OPEN/pending
       OR (CCP.IndEstado = 4169 AND CCP.IdSecuencialFechaLiquidacionReal > @asof)) -- settled after as-of
GROUP BY
    FP.CodigoFondo,
    M.CodigoISO;                                                        -- + mc.TipoCambio if soles enabled
