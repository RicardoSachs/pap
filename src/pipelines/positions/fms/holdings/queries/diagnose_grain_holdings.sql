-- diagnose_grain_holdings.sql
-- ---------------------------------------------------------------
-- Office-run diagnostic (FMS / SQL Server). NOT part of the pipeline.
--
-- Question: is (CodigoFondo, CodigoSBS, IdOrdenInversion, IdSecuencialFechaIDI)
-- — the staging grain — unique in the IDI valorization? Securities carry
-- IdOrdenInversion = 0 (should be one row per fund/security/date); deposits
-- carry a distinct order. If any group returns > 1 row, the grain collapses
-- them under ON CONFLICT DO UPDATE (silent loss).
--
-- Interpreting the result:
--   * ZERO rows -> grain is unique; safe.
--   * rows       -> inspect: for securities, something else splits the line
--                   (a second order? lot?); for deposits, IdOrdenInversion
--                   should already separate them. Add the missing key.
--
-- Parameters: two positional ? (start / end IdSecuencialFechaIDI, INT yyyymmdd).
-- In DBeaver, substitute literal ints for `? AND ?`.
-- ---------------------------------------------------------------

WITH filtered_idi AS (
    SELECT i.IdIDI, i.IdFondoPension, i.IdSecuencialFechaIDI
    FROM FMS.IDI i
    WHERE i.IdSecuencialFechaIDI BETWEEN ? AND ?
)
SELECT
    fi.IdFondoPension,
    vi.CodigoSBS,
    vi.IdOrdenInversion,
    fi.IdSecuencialFechaIDI,
    COUNT(*) AS row_count
FROM IDI.ValorizacionIDI vi
JOIN FMS.CierreIDI ci ON vi.IdCierreIDI = ci.IdCierreIDI AND ci.FlgHistorico = 0
JOIN filtered_idi fi  ON ci.IdIDI = fi.IdIDI
GROUP BY
    fi.IdFondoPension,
    vi.CodigoSBS,
    vi.IdOrdenInversion,
    fi.IdSecuencialFechaIDI
HAVING COUNT(*) > 1
ORDER BY row_count DESC, fi.IdFondoPension, vi.CodigoSBS;
