-- 44_vw_benchmark_changelog.sql
-- ---------------------------------------------------------------
-- vw_benchmark_changelog: every benchmark version against the one it
-- replaced, constituent by constituent.
--
-- One row per (version, series) that appears in the version OR in its
-- predecessor:
--   change   added       in the version, not in the predecessor
--            dropped     in the predecessor, not in the version
--            reweighted  in both, different weight
--            unchanged   in both, same weight
-- with weight_before / weight_after / weight_delta, and the version's
-- effective_from, change_type, reason and created_at alongside - the
-- traceability business asked for, and it falls out of the append-only
-- history for free: this is a view, not a process.
--
-- The predecessor is supersedes_version_id when the version names one,
-- otherwise the previous version of the same benchmark by version_id.
-- The first version has no predecessor: every constituent is 'added'.
-- ---------------------------------------------------------------

CREATE OR REPLACE VIEW vw_benchmark_changelog AS
WITH versions AS (
    SELECT v.version_id, v.portfolio_id, v.effective_from, v.method,
           v.change_type, v.reason, v.created_at,
           COALESCE(v.supersedes_version_id,
                    LAG(v.version_id) OVER (PARTITION BY v.portfolio_id
                                            ORDER BY v.version_id)) AS previous_version_id
    FROM dim_benchmark_version v
),
after AS (
    SELECT v.version_id, c.series_id, c.label, c.weight
    FROM versions v
    JOIN benchmark_constituent c ON c.version_id = v.version_id
),
before AS (
    SELECT v.version_id, c.series_id, c.label, c.weight
    FROM versions v
    JOIN benchmark_constituent c ON c.version_id = v.previous_version_id
),
keys AS (
    SELECT version_id, series_id FROM after
    UNION
    SELECT version_id, series_id FROM before
)
SELECT
    v.portfolio_id,
    p.procode,
    v.version_id,
    v.previous_version_id,
    v.effective_from,
    v.method,
    v.change_type,
    v.reason,
    v.created_at,
    k.series_id,
    COALESCE(n.label, o.label)                          AS label,
    o.weight                                            AS weight_before,
    n.weight                                            AS weight_after,
    COALESCE(n.weight, 0) - COALESCE(o.weight, 0)       AS weight_delta,
    CASE
        WHEN o.series_id IS NULL                        THEN 'added'
        WHEN n.series_id IS NULL                        THEN 'dropped'
        WHEN n.weight IS DISTINCT FROM o.weight         THEN 'reweighted'
        ELSE 'unchanged'
    END                                                 AS change
FROM keys k
JOIN versions v ON v.version_id = k.version_id
JOIN dim_portfolio p ON p.portfolio_id = v.portfolio_id
LEFT JOIN after  n ON n.version_id = k.version_id AND n.series_id = k.series_id
LEFT JOIN before o ON o.version_id = k.version_id AND o.series_id = k.series_id;
