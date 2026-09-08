-- cash.sql
-- ---------------------------------------------------------------
-- FMS extraction query: cash (current-account) feed.
--
-- Returns: one row per ACCOUNT — fund per institution (bank) per currency
-- per account (CodigoInstrumento) per business date, with the accounting
-- balance and its soles amount. A fund can hold SEVERAL accounts at the
-- same bank in the same currency on the same day (found reconciling against
-- the accountant reports), so CodigoInstrumento is part of the grain —
-- the tables report accounts, they do NOT aggregate.
--
-- Parameters (positional, pyodbc ? style):
--   1) start_date  INT yyyymmdd, inclusive lower bound
--   2) end_date    INT yyyymmdd, inclusive upper bound
-- For single-day runs, pass the same date twice.
--
-- Target staging:    stg_positions_fms_cash
-- Grain:             (CodigoFondo, IdEntidad, CodigoIsoMoneda,
--                     CodigoInstrumento, IdSecuencialFechaReporte)
--
-- OUTPUT CONTRACT — transform.py depends on these output column names:
--   Tier 1 (typed staging columns):
--     IdSecuencialFechaReporte, CodigoFondo, IdEntidad, CodigoIsoMoneda,
--     CodigoInstrumento, Institucion, SaldoContable, MontoTotalSoles,
--     TasaInteres, InteresAcumulado
--   Tier 2 (preserved verbatim in raw_payload JSONB):
--     MontoTotalOriginal
--
-- IdEntidad is the institution CODE (grain key -> codigo_institucion);
-- Institucion is the readable NAME (display -> nombre_institucion, TRIM'd);
-- CodigoInstrumento is the account identifier (grain key -> codigo_instrumento).
--
-- soles: MontoTotalSoles comes directly from the source (NO FX-spot join —
-- cash provides the soles amount itself, unlike forwards). SaldoContable is
-- the balance in the account's own currency.
--
-- Source: IDI.AnexoIVStock, joined to FMS.FondoPension (IdFondoPension =
-- IdFondo) and FMS.Moneda (Moneda = Simbolo).
-- ---------------------------------------------------------------

SELECT
    -- ===================== Tier 1 =====================
    cash.IdSecuencialFechaReporte                              AS IdSecuencialFechaReporte,
    fond.CodigoFondo                                           AS CodigoFondo,
    cash.IdEntidad                                             AS IdEntidad,           -- institution code -> codigo_institucion (grain)
    LTRIM(RTRIM(cash.Institucion))                             AS Institucion,         -- institution name -> nombre_institucion
    m.CodigoISO                                                AS CodigoIsoMoneda,
    cash.CodigoInstrumento                                     AS CodigoInstrumento,   -- account id -> codigo_instrumento (grain)
    cash.SaldoContable                                         AS SaldoContable,
    cash.MontoTotalSoles                                       AS MontoTotalSoles,
    cash.TasaInteres                                           AS TasaInteres,
    cash.InteresAcumulado                                      AS InteresAcumulado,

    -- ===================== Tier 2 =====================
    cash.MontoTotalOriginal
FROM IDI.AnexoIVStock cash
JOIN FMS.FondoPension fond
    ON cash.IdFondoPension = fond.IdFondo
JOIN FMS.Moneda m
    ON cash.Moneda = m.Simbolo
WHERE cash.IdSecuencialFechaReporte BETWEEN ? AND ?;
