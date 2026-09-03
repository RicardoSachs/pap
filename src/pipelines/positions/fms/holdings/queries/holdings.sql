-- holdings.sql
-- ---------------------------------------------------------------
-- FMS extraction query: holdings feed (securities + deposits) from the
-- IDI daily valorization.
--
-- One row per fund per investment-order line per report date. BOTH securities
-- and deposits come from IDI.ValorizacionIDI in this single query; they are
-- split DOWNSTREAM (in the fact transforms) by codigo_sbs — deposits start
-- with '60', everything else is a security. The query itself is type-agnostic.
--
-- Fund NAV (ValorCuota) and AUM (ValorCartera) from CierreIDI are denormalized
-- onto every line; downstream they are de-duped to one row per (fund, date)
-- into fact_portfolio_valuation.
--
-- Currency: resolved for BOTH types via FMS.OrdenInversion.IdMoneda -> Moneda
-- (every position came from an order, and the order carries the currency).
-- Deposit terms (Tasa, DiasVigencia) come from FMS.OrdenInversionDepositoPlazo
-- as a LEFT JOIN — null on security rows.
--
-- STORED DAILY SNAPSHOT (like cash, NOT point-in-time like net_receivables):
-- each row carries its own report date (IdSecuencialFechaIDI), so this is a
-- single set-based RANGE query — no per-day loop. FlgHistorico = 0 selects the
-- current disclosure for each (fund, date); older restatements are excluded.
--
-- Parameters (positional, pyodbc ? style):
--   1) start_date  INT yyyymmdd, inclusive lower bound
--   2) end_date    INT yyyymmdd, inclusive upper bound
--
-- Target staging:    stg_positions_fms_holdings
-- Grain:             (CodigoFondo, IdOrdenInversion, IdSecuencialFechaIDI)
--                    — IdOrdenInversion keys the line (one order = one holding);
--                      essential for deposits, whose '60…' CodigoSBS is NOT
--                      unique per deposit. Confirm with a diagnose-grain check.
--
-- OUTPUT CONTRACT — transform.py depends on these output column names:
--   Tier 1 (typed staging columns):
--     IdSecuencialFechaIDI (report date -> `date`), CodigoFondo,
--     IdOrdenInversion, CodigoSBS, CodigoIsoMoneda, ImportePEN,
--     ValorCuota, ValorCartera,
--     + <security measures: quantity, price, ...>   (null on deposit rows)
--     + Tasa, DiasVigencia                          (deposit terms; null on security rows)
--   Tier 2 -> raw_payload: any other ValorizacionIDI columns worth keeping.
--
-- TODO(dev) — still to define:
--   (a) Confirm (fund, IdOrdenInversion, date) is unique (diagnose-grain).
--   (c) Add the security measures (Cantidad, PrecioUnitario, ...) from vi.*.
--   Maturity: DiasVigencia is the term in days. Decide whether to store it as
--   dias_vigencia (+ derive maturity = order date + DiasVigencia downstream),
--   or add odp.<FechaVencimiento> if the table exposes an explicit maturity.
-- ---------------------------------------------------------------

WITH filtered_idi AS (
    SELECT
        i.IdiIDI,
        i.IdFondoPension,
        i.IdSecuencialFechaIDI
    FROM FMS.IDI i
    WHERE i.IdSecuencialFechaIDI BETWEEN ? AND ?
)
SELECT
    -- ===================== Tier 1 (common to both types) =====================
    fi.IdSecuencialFechaIDI                                     AS IdSecuencialFechaIDI,   -- report date -> `date`
    fond.CodigoFondo                                           AS CodigoFondo,
    vi.IdOrdenInversion                                        AS IdOrdenInversion,       -- line grain key (one order = one holding)
    vi.CodigoSBS                                               AS CodigoSBS,              -- '60%' = deposit, else security
    m.CodigoISO                                                AS CodigoIsoMoneda,        -- currency (via OrdenInversion, both types)
    vi.ImportePEN                                              AS ImportePEN,             -- valued amount in soles
    ci.ValorCuota                                              AS ValorCuota,             -- fund NAV (denormalized)
    ci.ValorCartera                                            AS ValorCartera,           -- fund AUM (denormalized)

    -- ===================== Tier 1 (security-specific; null on deposit rows) =====================
    -- , vi.<Cantidad>          AS Cantidad          -- TODO(dev): quantity
    -- , vi.<PrecioUnitario>    AS PrecioUnitario    -- TODO(dev): unit price

    -- ===================== Tier 1 (deposit-specific; null on security rows) =====================
    odp.Tasa                                                   AS Tasa,                   -- deposit rate
    odp.DiasVigencia                                           AS DiasVigencia            -- deposit term (days)
    -- , odp.<FechaVencimiento>  AS FechaVencimiento  -- TODO(dev): explicit maturity, if present

    -- ===================== Tier 2 -> raw_payload =====================
    -- , vi.<other columns>  -- anything else worth keeping verbatim

FROM IDI.ValorizacionIDI vi
JOIN FMS.CierreIDI ci
    ON vi.IdCierreIDI = ci.IdCierreIDI
   AND ci.FlgHistorico = 0
JOIN filtered_idi fi
    ON ci.IdiIDI = fi.IdiIDI
JOIN FMS.FondoPension fond
    ON fond.IdFondo = fi.IdFondoPension
JOIN FMS.OrdenInversion oi
    ON oi.IdOrdenInversion = vi.IdOrdenInversion
JOIN FMS.Moneda m
    ON m.IdMoneda = oi.IdMoneda
LEFT JOIN FMS.OrdenInversionDepositoPlazo odp                  -- deposit-only detail (null for securities)
    ON odp.IdOrdenInversion = vi.IdOrdenInversion;
