-- diagnose_grain.sql
-- ---------------------------------------------------------------
-- Office-run diagnostic (FMS / SQL Server). NOT part of the pipeline.
--
-- Question: is (CodigoFondo, CodigoSbs, IdSecuencialFechaProceso) —
-- the staging/fact grain — actually unique in FMS.ForwardPrecio, or
-- does FMS emit more than one row per contract per fund per date?
--
-- The payload carries IndCxcCxp (cuenta por cobrar / por pagar) and
-- IdCuentaCobrarPagar, which suggest FMS may split one contract into a
-- receivable row and a payable row on the SAME grain. If so, the
-- current PK (codigo_fondo, codigo_sbs, date) + ON CONFLICT DO UPDATE
-- silently keeps one and drops the other.
--
-- Interpreting the result:
--   * ZERO rows returned  -> grain is unique, no leg collision. Record
--                            that in the 26/27 schema banners and stop.
--   * rows returned       -> grain is NOT unique. Read distinct_cxc_cxp:
--       - = row_count      -> the duplication axis IS CxC/CxP; add
--                             ind_cxc_cxp to Tier 1 + widen both PKs
--                             (staging 26, fact 27) to include it, then
--                             ALTER the live tables (no migration tool).
--       - < row_count      -> some other axis also duplicates; inspect
--                             IdCuentaCobrarPagar / CodigoReferencia
--                             before choosing the discriminator.
--
-- Parameters: two positional ? (start / end IdSecuencialFechaProceso,
-- INT yyyymmdd). In DBeaver, substitute literal ints for `? AND ?`.
-- ---------------------------------------------------------------

SELECT
    fond.CodigoFondo,
    fp.CodigoSbs,
    fp.IdSecuencialFechaProceso,
    COUNT(*)                                AS row_count,
    COUNT(DISTINCT fp.IndCxcCxp)            AS distinct_cxc_cxp,
    COUNT(DISTINCT fp.IdCuentaCobrarPagar)  AS distinct_cuentas,
    COUNT(DISTINCT fp.CodigoReferencia)     AS distinct_referencia
FROM FMS.ForwardPrecio fp
JOIN FMS.FondoPension fond
    ON fp.IdFondo = fond.IdFondo
WHERE fp.IdSecuencialFechaProceso BETWEEN ? AND ?
GROUP BY
    fond.CodigoFondo,
    fp.CodigoSbs,
    fp.IdSecuencialFechaProceso
HAVING COUNT(*) > 1
ORDER BY row_count DESC, fond.CodigoFondo, fp.CodigoSbs;
