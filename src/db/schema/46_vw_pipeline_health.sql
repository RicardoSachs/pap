-- 46_vw_pipeline_health.sql
-- ---------------------------------------------------------------
-- vw_pipeline_health: how fresh every daily feed is, one row per feed.
--
-- Grain: feed.
--   positions_securities / _deposits / _cash / _forwards /
--   _net_receivables / _valuation     the six positions facts
--   contribution                      fact_contribution
--   prices_<source>                   fact_prices, one feed per source
--                                     (prices_bloomberg, prices_sbs,
--                                     prices_sbs_spp, prices_model, ...)
--
-- Columns:
--   last_date / rows_last_date   newest business date held, and its rows
--   prev_date / rows_prev_date   the date before it - a last day with far
--                                fewer rows than the previous one is a
--                                partial load
--   last_loaded_at               when the newest date was written. NULL
--                                for prices: fact_prices has no loaded_at
--
-- The view states FACTS only. Whether last_date is late depends on the
-- SBS reporting calendar (NYSE or XLIM open), which lives in Python
-- (src/calendars), so the verdict is computed by web/api/services/
-- status.py and shown on the dashboards' Status page. From DBeaver,
-- read last_date against the last business day.
--
-- Only the last 45 days are scanned, through each table's date index
-- (fact_contribution has none and is scanned whole). A feed with no row
-- in that window still appears, with NULL dates: the positions feeds
-- are listed by hand and the price feeds come from series_registry.
-- Rows dated after today (e.g. announced dividends) are ignored so they
-- cannot make a stalled feed look current.
-- ---------------------------------------------------------------

CREATE OR REPLACE VIEW vw_pipeline_health AS
WITH daily AS (
    SELECT 'positions_securities'::text AS feed, date, COUNT(*) AS n, MAX(loaded_at) AS loaded_at
    FROM fact_positions_securities
    WHERE date BETWEEN CURRENT_DATE - 45 AND CURRENT_DATE GROUP BY date
    UNION ALL
    SELECT 'positions_deposits', date, COUNT(*), MAX(loaded_at)
    FROM fact_positions_deposits
    WHERE date BETWEEN CURRENT_DATE - 45 AND CURRENT_DATE GROUP BY date
    UNION ALL
    SELECT 'positions_cash', date, COUNT(*), MAX(loaded_at)
    FROM fact_positions_cash
    WHERE date BETWEEN CURRENT_DATE - 45 AND CURRENT_DATE GROUP BY date
    UNION ALL
    SELECT 'positions_forwards', date, COUNT(*), MAX(loaded_at)
    FROM fact_positions_forwards
    WHERE date BETWEEN CURRENT_DATE - 45 AND CURRENT_DATE GROUP BY date
    UNION ALL
    SELECT 'positions_net_receivables', date, COUNT(*), MAX(loaded_at)
    FROM fact_positions_net_receivables
    WHERE date BETWEEN CURRENT_DATE - 45 AND CURRENT_DATE GROUP BY date
    UNION ALL
    SELECT 'positions_valuation', date, COUNT(*), MAX(loaded_at)
    FROM fact_portfolio_valuation
    WHERE date BETWEEN CURRENT_DATE - 45 AND CURRENT_DATE GROUP BY date
    UNION ALL
    SELECT 'contribution', date, COUNT(*), MAX(loaded_at)
    FROM fact_contribution
    WHERE date BETWEEN CURRENT_DATE - 45 AND CURRENT_DATE GROUP BY date
    UNION ALL
    SELECT 'prices_' || source, date, COUNT(*), NULL::timestamptz
    FROM fact_prices
    WHERE date BETWEEN CURRENT_DATE - 45 AND CURRENT_DATE GROUP BY source, date
),
ranked AS (
    SELECT feed, date, n, loaded_at,
           ROW_NUMBER() OVER (PARTITION BY feed ORDER BY date DESC) AS rn
    FROM daily
),
feeds AS (
    SELECT feed FROM (VALUES
        ('positions_securities'), ('positions_deposits'), ('positions_cash'),
        ('positions_forwards'), ('positions_net_receivables'),
        ('positions_valuation'), ('contribution')
    ) AS f (feed)
    UNION
    SELECT 'prices_' || source FROM series_registry
    WHERE domain = 'prices' AND frequency = 'daily' AND status = 'active'
    UNION
    SELECT feed FROM daily
)
SELECT
    f.feed,
    CASE WHEN f.feed LIKE 'prices\_%' THEN 'prices' ELSE 'positions' END AS domain,
    l.date       AS last_date,
    l.n          AS rows_last_date,
    l.loaded_at  AS last_loaded_at,
    p.date       AS prev_date,
    p.n          AS rows_prev_date
FROM feeds f
LEFT JOIN ranked l ON l.feed = f.feed AND l.rn = 1
LEFT JOIN ranked p ON p.feed = f.feed AND p.rn = 2;
