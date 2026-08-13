-- diagnose_grain_cash.sql
-- ---------------------------------------------------------------
-- Office-run diagnostic (FMS / SQL Server). NOT part of the pipeline.
--
-- Question: is (fund, institution, currency, report date) — the intended
-- staging/fact grain — actually unique in the FMS cash source
-- (IDI.AnexoIVStock)? If a fund can hold more than one account at the same
-- bank + currency on the same date, this grain collapses them under
-- ON CONFLICT DO UPDATE (silent loss).
--
-- Grouped by the base-table columns (no joins needed): IdFondoPension,
-- IdEntidad, Moneda, IdSecuencialFechaReporte — each maps 1:1 to the
-- staging grain (codigo_fondo, codigo_institucion, codigo_iso_moneda, date).
--
-- Interpreting the result:
--   * ZERO rows returned  -> grain is unique; the four-part key is safe.
--   * rows returned       -> add an account identifier (codigo_cuenta) to
--                            Tier 1 and to both PKs (staging 28 + fact 29)
--                            before loading. Inspect the extra distinguishing
--                            column and add it.
--
-- Parameters: two positional ? (start / end IdSecuencialFechaReporte,
-- INT yyyymmdd). In DBeaver, substitute literal ints for `? AND ?`.
-- ---------------------------------------------------------------

SELECT
    cash.IdFondoPension,
    cash.IdEntidad,
    cash.Moneda,
    cash.IdSecuencialFechaReporte,
    COUNT(*) AS row_count
FROM IDI.AnexoIVStock cash
WHERE cash.IdSecuencialFechaReporte BETWEEN ? AND ?
GROUP BY
    cash.IdFondoPension,
    cash.IdEntidad,
    cash.Moneda,
    cash.IdSecuencialFechaReporte
HAVING COUNT(*) > 1
ORDER BY row_count DESC, cash.IdFondoPension, cash.IdEntidad;
