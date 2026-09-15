-- 36_vw_positions_unified.sql
-- ---------------------------------------------------------------
-- vw_positions_unified + vw_positions_recon: the consolidation point
-- of the positions domain (Architecture B - per-type fact tables, no
-- materialized fact_positions rollup; that name stays reserved).
--
-- vw_positions_unified
--   One row per position across the five per-type facts, at grain
--   (portfolio_id, date, source, position_type, position_key):
--     security       fact_positions_securities   importe_pen
--     deposit        fact_positions_deposits     importe_pen
--     cash           fact_positions_cash         monto_total_soles
--     forward        fact_positions_forwards     mtm_soles
--     net_receivable fact_positions_net_recv.    cobrar_soles - pagar_soles
--
--   in_nav: TRUE for the types whose PEN values sum to the fund NAV
--   (security, deposit, cash, net_receivable). FALSE for forwards:
--   FMS embeds the forward valuation in CuentaCobrarPagar, so the
--   net_receivable rows ALREADY carry the forwards' MTM - summing the
--   forward rows too would double-count. Forward rows stay in the view
--   because the FX underlying positioning (fact_portfolio_fx_exposure)
--   needs the contracts and their legs; they just do not contribute to
--   the NAV tie-out.
--
--   market_value_pen is NULLABLE by design: a forward without MTM or a
--   receivable without FMS FX soles surfaces as NULL (visible), never as
--   a silent 0 or notional substitute. security_entity_id is populated
--   only for position_type='security' (the one entity-resolved type).
--   weight = market_value_pen / valor_cartera comes from the LEFT JOIN
--   to fact_portfolio_valuation on (portfolio_id, date, source) - this
--   is why weight is not materialized on the per-type facts (see 35).
--   (Forward rows get a weight too - informational, e.g. MTM as a share
--   of AUM - but remember it is not a NAV component.)
--
-- vw_positions_recon
--   The NAV tie-out, frozen into the schema: per (portfolio, date,
--   source), per-type PEN sums vs valor_cartera. positions_pen and
--   gap_pen include ONLY in_nav rows (securities + deposits + cash +
--   net receivables); forwards_mtm_pen is reported as a MEMO column
--   outside the sum. gap_pen ~ 0 proves the consolidation is complete
--   and correct; the unvalued-row counters say where to look when it
--   is not. This is the daily monitorable version of the manual
--   accountant-report double-check.
--
-- CREATE OR REPLACE keeps re-runs idempotent; note PG refuses REPLACE
-- on an incompatible column-set change - drop the views first in that
-- case (they hold no data).
-- ---------------------------------------------------------------

CREATE OR REPLACE VIEW vw_positions_unified AS
WITH positions AS (
    SELECT
        portfolio_id,
        date,
        source,
        'security'::text            AS position_type,
        security_entity_id::text    AS position_key,
        security_entity_id          AS security_entity_id,
        codigo_iso_moneda,
        importe_pen                 AS market_value_pen,
        TRUE                        AS in_nav
    FROM fact_positions_securities

    UNION ALL

    SELECT
        portfolio_id, date, source,
        'deposit',
        id_orden_inversion::text,
        NULL::integer,
        codigo_iso_moneda,
        importe_pen,
        TRUE
    FROM fact_positions_deposits

    UNION ALL

    SELECT
        portfolio_id, date, source,
        'cash',
        codigo_institucion || ':' || codigo_instrumento,   -- account-grain key
        NULL::integer,
        codigo_iso_moneda,
        monto_total_soles,
        TRUE
    FROM fact_positions_cash

    UNION ALL

    SELECT
        portfolio_id, date, source,
        'forward',
        codigo_sbs,
        NULL::integer,
        codigo_iso_moneda_nocional,
        mtm_soles,                                         -- NULL = unvalued; NEVER nocional_soles here
        FALSE                                              -- MTM already inside net_receivables (CxC/CxP)
    FROM fact_positions_forwards

    UNION ALL

    SELECT
        portfolio_id, date, source,
        'net_receivable',
        codigo_iso_moneda,                                 -- one row per currency = its own key
        NULL::integer,
        codigo_iso_moneda,
        monto_cobrar_soles - monto_pagar_soles,            -- NULL = missing FMS FX soles
        TRUE                                               -- carries the forwards' MTM among CxC/CxP
    FROM fact_positions_net_receivables
)
SELECT
    pos.portfolio_id,
    pos.date,
    pos.source,
    pos.position_type,
    pos.position_key,
    pos.security_entity_id,
    pos.codigo_iso_moneda,
    pos.market_value_pen,
    pos.in_nav,
    v.valor_cartera,
    pos.market_value_pen / NULLIF(v.valor_cartera, 0)      AS weight
FROM positions pos
LEFT JOIN fact_portfolio_valuation v
       ON v.portfolio_id = pos.portfolio_id
      AND v.date         = pos.date
      AND v.source       = pos.source;


CREATE OR REPLACE VIEW vw_positions_recon AS
SELECT
    u.portfolio_id,
    p.procode,
    u.date,
    u.source,

    -- NAV components (in_nav rows; NULL market values excluded from their
    -- sums but counted below, so the gap explains itself)
    SUM(u.market_value_pen) FILTER (WHERE u.position_type = 'security')        AS securities_pen,
    SUM(u.market_value_pen) FILTER (WHERE u.position_type = 'deposit')         AS deposits_pen,
    SUM(u.market_value_pen) FILTER (WHERE u.position_type = 'cash')            AS cash_pen,
    SUM(u.market_value_pen) FILTER (WHERE u.position_type = 'net_receivable')  AS net_receivables_pen,

    -- MEMO only: forward MTM is already inside net_receivables (CxC/CxP),
    -- so it is NOT part of positions_pen / gap_pen (double counting).
    SUM(u.market_value_pen) FILTER (WHERE u.position_type = 'forward')         AS forwards_mtm_pen_memo,

    SUM(COALESCE(u.market_value_pen, 0)) FILTER (WHERE u.in_nav)               AS positions_pen,
    u.valor_cartera,
    u.valor_cartera
        - SUM(COALESCE(u.market_value_pen, 0)) FILTER (WHERE u.in_nav)         AS gap_pen,

    -- Why the gap, when there is one (receivables affect the sum; the
    -- forwards counter is data-quality memo, like forwards_mtm_pen_memo)
    COUNT(*) FILTER (WHERE u.position_type = 'net_receivable'
                       AND u.market_value_pen IS NULL)                         AS receivables_without_soles,
    COUNT(*) FILTER (WHERE u.position_type = 'forward'
                       AND u.market_value_pen IS NULL)                         AS forwards_without_mtm
FROM vw_positions_unified u
JOIN dim_portfolio p ON p.portfolio_id = u.portfolio_id
GROUP BY
    u.portfolio_id, p.procode, u.date, u.source, u.valor_cartera;
