// web/apps/dashboards/app/positioning/page.js
// ---------------------------------------------------------------------------
// Positioning dashboard — Profuturo "posicionamiento" matrix as a collapsible
// pivot tree across three sleeves (PRO1/PRO2/PRO3), in two views: Absolute
// weights and Duration contribution.
//
// Content is in English; technical column identifiers (PRO1, DurPRO1, Category)
// and currency/country codes stay as-is.
//
// DATA NOTE: the wired toy API has 4 generic Mexican portfolios and none of
// this hierarchy. The tree below is hard-coded with DETERMINISTIC SYNTHETIC
// values (leaves carry values; subtotals are summed) so it reproduces the real
// reporting layout. The only live API value is AUM Total (KPI #1).
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { apiGet, pct, num } from '../../lib/api';
import { downloadCsv } from '../../lib/csv';
import { useDashboard } from '../../components/DashboardProvider';
import KpiBar from '../../components/KpiBar';

const PlotlyChart = dynamic(() => import('../../components/PlotlyChart'), { ssr: false });

const SLEEVES = ['PRO1', 'PRO2', 'PRO3'];
const CASH_AMBER_THRESHOLD = 0.10; // Posición en Caja KPI turns amber above this
const INDENT = { 1: 12, 2: 28, 3: 44, 4: 60 };

const BLOCK_META = {
  absolute: { tab: 'Absolute Positioning', accent: '#5B8CFF', guide: 'Each cell = weight of (category) in sleeve PRO(1/2/3)' },
  duration: { tab: 'Duration Matrix', accent: '#C9A84C', guide: 'Each cell = duration contribution by (category, sleeve)' },
};
const SLEEVE_COLOR = ['#5B8CFF', '#5FD7B0', '#D9BE6E'];
const FILTERS = [['all', 'All'], ['asset', 'Asset Class'], ['currency', 'Currency'], ['region', 'Region'], ['strategy', 'Strategy']];

// node builders. leaf carries abs/dur per sleeve; sub aggregates its children.
const leaf = (key, label, level, abs, dur, group) => ({ key, label, level, collapsible: false, children: [], abs, dur, group });
const sub = (key, label, level, children, group) => ({ key, label, level, collapsible: true, children, group });

// ---- the exact hierarchy (hard-coded, no inferred/repeated subtrees) -------
const TREE = [
  sub('RF', 'RF — Fixed Income', 1, [
    sub('RF.USD', 'USD', 2, [
      leaf('RF.USD.Treasury', 'Treasury', 3, [0.16, 0.12, 0.09], [1.10, 0.90, 0.65]),
      leaf('RF.USD.Credito', 'Credit (USD)', 3, [0.08, 0.06, 0.04], [0.40, 0.30, 0.20]),
    ], 'ccy'),
    sub('RF.LocalCurrency', 'Local Currency', 2, [
      sub('RF.LocalCurrency.PEN', 'PEN', 3, [
        leaf('RF.LocalCurrency.PEN.Soberanos', 'Sovereign Bonds', 4, [0.12, 0.09, 0.05], [0.80, 0.60, 0.40]),
        leaf('RF.LocalCurrency.PEN.Credito', 'Credit (PEN)', 4, [0.06, 0.04, 0.03], [0.30, 0.25, 0.15]),
      ], 'ccy'),
      sub('RF.LocalCurrency.Latam', 'Latam', 3, [
        leaf('RF.LocalCurrency.Latam.MXN', 'MXN', 4, [0.04, 0.03, 0.02], [0.20, 0.15, 0.10], 'country'),
        leaf('RF.LocalCurrency.Latam.BRL', 'BRL', 4, [0.03, 0.02, 0.015], [0.12, 0.10, 0.07], 'country'),
        leaf('RF.LocalCurrency.Latam.COP', 'COP', 4, [0.02, 0.02, 0.01], [0.08, 0.06, 0.04], 'country'),
        leaf('RF.LocalCurrency.Latam.CLP', 'CLP', 4, [0.02, 0.01, 0.01], [0.06, 0.05, 0.03], 'country'),
        leaf('RF.LocalCurrency.Latam.Latam', 'Latam', 4, [0.01, 0.01, 0.005], [0.04, 0.04, 0.02], 'country'),
      ], 'region'),
      leaf('RF.LocalCurrency.Global', 'Global', 3, [0.06, 0.05, 0.03], [0.30, 0.25, 0.18], 'region'),
    ], 'ccy'),
  ]),
  sub('RV', 'RV — Equities', 1, [
    sub('RV.RVExterior', 'Foreign Equities', 2, [
      leaf('RV.RVExterior.Global', 'Global', 3, [0.02, 0.04, 0.06], [0, 0, 0]),
      leaf('RV.RVExterior.EEUU', 'USA', 3, [0.04, 0.07, 0.10], [0, 0, 0]),
      leaf('RV.RVExterior.Europa', 'Europe', 3, [0.02, 0.03, 0.05], [0, 0, 0]),
      leaf('RV.RVExterior.Japon', 'Japan', 3, [0.01, 0.02, 0.03], [0, 0, 0]),
      leaf('RV.RVExterior.Commodities', 'Commodities', 3, [0.01, 0.02, 0.03], [0, 0, 0]),
      sub('RV.RVExterior.Emergentes', 'Emerging Markets', 3, [
        leaf('RV.RVExterior.Emergentes.Brasil', 'Brazil', 4, [0.006, 0.012, 0.018], [0, 0, 0]),
        leaf('RV.RVExterior.Emergentes.RestoLatam', 'Rest of LatAm', 4, [0.004, 0.008, 0.012], [0, 0, 0]),
        leaf('RV.RVExterior.Emergentes.China', 'China', 4, [0.005, 0.010, 0.015], [0, 0, 0]),
        leaf('RV.RVExterior.Emergentes.Corea', 'Korea', 4, [0.003, 0.006, 0.009], [0, 0, 0]),
        leaf('RV.RVExterior.Emergentes.RestoAsiaEM', 'Rest of EM Asia', 4, [0.002, 0.004, 0.006], [0, 0, 0]),
      ]),
    ]),
    sub('RV.RVLocal', 'Local Equities', 2, [
      leaf('RV.RVLocal.Financiero', 'Financials', 3, [0.03, 0.05, 0.07], [0, 0, 0]),
      leaf('RV.RVLocal.NoFinanciero', 'Non-Financials', 3, [0.03, 0.05, 0.06], [0, 0, 0]),
      leaf('RV.RVLocal.Fondos', 'Funds', 3, [0.02, 0.03, 0.04], [0, 0, 0]),
    ]),
  ]),
  sub('Alts', 'Alts — Alternatives', 1, [
    leaf('Alts.AltExterior', 'Foreign Alternatives', 2, [0.07, 0.09, 0.10], [0.25, 0.30, 0.28]),
    leaf('Alts.AltLocal', 'Local Alternatives', 2, [0.05, 0.06, 0.06], [0.20, 0.25, 0.22]),
  ]),
  sub('Caja', 'Cash', 1, [
    leaf('Caja.Depositos', 'Deposits', 2, [0.06, 0.04, 0.03], [0, 0, 0]),
    leaf('Caja.EnTransito', 'In Transit', 2, [0.02, 0.01, 0.01], [0, 0, 0]),
  ]),
];

// roll subtotals up from leaves; tag each node with its total descendant-leaf count
function finalize(node) {
  if (!node.collapsible) { node.leafCount = 1; return node; }
  node.children.forEach(finalize);
  node.abs = [0, 1, 2].map((i) => node.children.reduce((s, c) => s + c.abs[i], 0));
  node.dur = [0, 1, 2].map((i) => node.children.reduce((s, c) => s + c.dur[i], 0));
  node.leafCount = node.children.reduce((s, c) => s + c.leafCount, 0);
  return node;
}
TREE.forEach(finalize);

const FLAT = [];
(function walk(nodes) { for (const n of nodes) { FLAT.push(n); if (n.children.length) walk(n.children); } })(TREE);
const TOP = Object.fromEntries(TREE.map((n) => [n.key, n]));
const ALL_COLLAPSIBLE_KEYS = FLAT.filter((n) => n.collapsible).map((n) => n.key);
const GT_ABS = [0, 1, 2].map((i) => TREE.reduce((s, n) => s + n.abs[i], 0));
const GT_DUR = [0, 1, 2].map((i) => TREE.reduce((s, n) => s + n.dur[i], 0));

// Deterministic 30-point trend around a seed value (positioning data is a
// synthetic snapshot with no history — this renders a stable KPI sparkline).
function synthSpark(seed, n = 30) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const trend = 0.9 + 0.1 * (i / (n - 1));           // gentle drift toward the value
    const wiggle = Math.sin((i + 1) * (seed * 6.283 + 1)) * 0.04;
    out.push(seed * (trend + wiggle));
  }
  return out;
}

export default function PositioningPage() {
  const { portfolioId, range } = useDashboard();
  const [aum, setAum] = useState(null);
  const [aumMeta, setAumMeta] = useState('');
  const [block, setBlock] = useState('absolute');
  const [filter, setFilter] = useState('all');
  const [heatMap, setHeatMap] = useState(false);
  const [sort, setSort] = useState({ col: null, dir: null }); // col 0..2, dir 'desc'|'asc'|null
  const [detailRow, setDetailRow] = useState(null);
  const [collapsed, setCollapsed] = useState(new Set(['RF.USD', 'RF.LocalCurrency', 'RV.RVExterior', 'RV.RVLocal']));

  // live AUM Total (only real value sourced from the wired API)
  useEffect(() => {
    if (!portfolioId) { setAum(null); setAumMeta(''); return; }
    apiGet(`/api/portfolios/${portfolioId}/holdings?date=${range.to}`)
      .then((d) => { setAum(d?.total_market_value ?? null); setAumMeta(`as of ${d?.reference_date || range.to}`); })
      .catch(() => { setAum(null); setAumMeta(''); });
  }, [portfolioId, range.to]);

  const toggle = (key) => setCollapsed((prev) => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  // --- value accessors per block -------------------------------------------
  const nodeVal = (n, i) => (block === 'absolute' ? n.abs[i] : n.dur[i]);
  const fmtCell = (v) => (block === 'absolute' ? `${(v * 100).toFixed(2)}%` : `${v.toFixed(2)}yr`);
  const csvVal = (v) => (block === 'duration' ? v.toFixed(2) : (v * 100).toFixed(2));
  const cellBg = (v) => {
    if (!heatMap) return undefined;
    if (block === 'absolute') return `rgba(91,140,255,${Math.min(0.5, v * 0.7)})`;
    return `rgba(245,166,35,${Math.min(0.45, v / 4)})`;
  };
  // intensity text class (absolute only): >40% bright, 20–40% normal, <20% muted, 0 very muted
  const absTone = (v) => {
    if (block !== 'absolute') return '';
    if (v === 0) return 'pos-zero';
    if (v < 0.20) return 'pos-soft';
    if (v <= 0.40) return '';
    return 'pos-strong';
  };
  const colLabel = (i) => (block === 'duration' ? `Dur${SLEEVES[i]}` : SLEEVES[i]);

  // --- KPIs (5, from the tree totals + live AUM) ---------------------------
  const cashPro1 = TOP.Caja.abs[0];
  const kpis = [
    { label: 'AUM Total', value: aum != null ? num(aum, 0) : '—', meta: aumMeta || '—' },
    { label: 'Equity Exposure', value: pct(TOP.RV.abs[0]), meta: 'RV — PRO1', spark: synthSpark(TOP.RV.abs[0]) },
    { label: 'Fixed Income Exposure', value: pct(TOP.RF.abs[0]), meta: 'RF — PRO1' },
    { label: 'Cash Position', value: pct(cashPro1), meta: 'Cash — PRO1', valueStyle: cashPro1 > CASH_AMBER_THRESHOLD ? { color: 'var(--warning)' } : undefined, spark: synthSpark(cashPro1) },
    { label: 'Portfolio Duration', value: `${GT_DUR[0].toFixed(2)}yr`, meta: 'Duration · PRO1', accent: true, spark: synthSpark(GT_DUR[0]) },
  ];

  // --- chart: asset-class exposure by sleeve (grouped bars) ----------------
  const ASSET_KEYS = ['RF', 'RV', 'Alts', 'Caja'];
  const barTraces = SLEEVES.map((sleeve, i) => ({
    type: 'bar', name: sleeve,
    x: ASSET_KEYS,
    y: ASSET_KEYS.map((k) => TOP[k].abs[i] * 100),
    marker: { color: SLEEVE_COLOR[i] },
    hovertemplate: `%{x} · ${sleeve}: %{y:.2f}%<extra></extra>`,
  }));

  // --- filter: which node keys are allowed for the current filter ----------
  const allowedKeys = (() => {
    if (filter === 'all') return null;
    if (filter === 'asset') return new Set(FLAT.filter((n) => n.level <= 2).map((n) => n.key));
    if (filter === 'currency') return new Set(FLAT.filter((n) => n.key.startsWith('RF') && n.group !== 'region' && n.group !== 'country').map((n) => n.key));
    if (filter === 'strategy') return new Set(FLAT.filter((n) => (n.key.startsWith('RV') || n.key.startsWith('Alts')) && n.level <= 2).map((n) => n.key));
    if (filter === 'region') {
      const allow = new Set();
      FLAT.filter((n) => n.label === 'Latam' || n.label === 'Global').forEach((m) => {
        const parts = m.key.split('.');
        for (let j = 1; j <= parts.length; j++) allow.add(parts.slice(0, j).join('.'));
        FLAT.forEach((n) => { if (n.key === m.key || n.key.startsWith(`${m.key}.`)) allow.add(n.key); });
      });
      return allow;
    }
    return null;
  })();

  // --- visible rows: walk the tree honoring filter, collapse, and sort -----
  const sortActive = sort.dir != null && sort.col != null;
  const sortSibs = (nodes) => (sortActive
    ? [...nodes].sort((a, b) => (sort.dir === 'desc' ? nodeVal(b, sort.col) - nodeVal(a, sort.col) : nodeVal(a, sort.col) - nodeVal(b, sort.col)))
    : nodes);
  const visible = [];
  (function collect(nodes) {
    for (const n of sortSibs(nodes)) {
      if (allowedKeys && !allowedKeys.has(n.key)) continue;
      visible.push(n);
      if (n.collapsible && !collapsed.has(n.key)) collect(n.children);
    }
  })(TREE);

  const cycleSort = (i) => setSort((s) => {
    if (s.col !== i) return { col: i, dir: 'desc' };
    const next = s.dir === 'desc' ? 'asc' : s.dir === 'asc' ? null : 'desc';
    return { col: i, dir: next };
  });
  const sortInd = (i) => (sort.col === i ? (sort.dir === 'desc' ? '↓' : sort.dir === 'asc' ? '↑' : '↕') : '↕');

  // CSV: full tree in order (ignores collapse), with a Level column
  const exportCsv = () => {
    const headers = ['Level', 'Label', ...[0, 1, 2].map(colLabel)];
    const rows = FLAT.map((n) => [n.level, n.label, ...[0, 1, 2].map((i) => csvVal(nodeVal(n, i)))]);
    rows.push(['', 'Grand Total', ...[0, 1, 2].map((i) => csvVal(block === 'absolute' ? GT_ABS[i] : GT_DUR[i]))]);
    downloadCsv(`posicionamiento_${block}_${range.to}`, headers, rows);
  };

  const rowOnClick = (n) => { if (n.collapsible) toggle(n.key); else setDetailRow(n); };

  return (
    <div>
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">Positioning</div>
      </div>
      <p className="page-sub">PRO sleeve matrix — absolute weights and duration contribution.</p>

      <KpiBar tiles={kpis} />

      {/* asset class exposure */}
      <div className="panel">
        <div className="panel-title">Asset Class Exposure</div>
        <PlotlyChart
          data={barTraces}
          layout={{ barmode: 'group', showlegend: true, legend: { orientation: 'h', y: -0.18 }, yaxis: { ticksuffix: '%' }, margin: { l: 48, r: 16, t: 10, b: 40 } }}
          style={{ height: '320px' }}
        />
      </div>

      {/* matrix */}
      <div className="panel">
        <div className="pos-tabs">
          {Object.entries(BLOCK_META).map(([k, m]) => (
            <button
              key={k}
              type="button"
              className={`pos-tab ${block === k ? 'active' : ''}`}
              style={block === k ? { background: m.accent, borderColor: m.accent, color: '#fff' } : { borderColor: m.accent, color: m.accent }}
              onClick={() => setBlock(k)}
            >
              {m.tab}
            </button>
          ))}
        </div>

        <div className="pos-bar">
          <div className="pos-filters">
            {FILTERS.map(([k, lab]) => (
              <button key={k} type="button" className={`btn ${filter === k ? 'active' : ''}`} onClick={() => setFilter(k)}>{lab}</button>
            ))}
          </div>
          <div className="pos-bar-right">
            <button type="button" className="btn" onClick={() => setCollapsed(new Set())}>Expand all</button>
            <button type="button" className="btn" onClick={() => setCollapsed(new Set(ALL_COLLAPSIBLE_KEYS))}>Collapse all</button>
            <button type="button" className={`btn ${heatMap ? 'active' : ''}`} onClick={() => setHeatMap((v) => !v)} title="Color cells by magnitude">
              Heat map · {heatMap ? 'On' : 'Off'}
            </button>
            <button type="button" className="btn" onClick={exportCsv} title="Export the active block as CSV">↓ Export CSV</button>
          </div>
        </div>

        <div className="pos-guide">{BLOCK_META[block].guide}</div>

        <div className="pos-wrap">
          <table className="pos-table">
            <thead>
              <tr className="pos-col">
                <th className="pos-cat pos-cat-head">Category</th>
                {[0, 1, 2].map((i) => (
                  <th key={i} className={`pos-sortable ${i > 0 ? 'pos-div' : ''}`} onClick={() => cycleSort(i)}>
                    {colLabel(i)} <span className={`pos-sort-ind ${sort.col === i && sort.dir ? 'on' : ''}`}>{sortInd(i)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((n) => {
                const kind = n.collapsible ? 'pt-sub' : 'pt-leaf';
                const isCollapsed = collapsed.has(n.key);
                return (
                  <tr key={n.key} className={`pt-row pt-l${n.level} ${kind}`} onClick={() => rowOnClick(n)}>
                    <td className="pos-cat pt-label" style={{ paddingLeft: INDENT[n.level] }}>
                      {n.collapsible
                        ? <span className="pt-ind">{isCollapsed ? '▶' : '▼'}</span>
                        : <span className="pt-spacer" />}
                      {n.label}
                      {n.collapsible && isCollapsed && <span className="pt-count">({n.leafCount})</span>}
                    </td>
                    {[0, 1, 2].map((i) => {
                      const v = nodeVal(n, i);
                      return <td key={i} className={`pos-num pt-num ${absTone(v)}`} style={{ background: cellBg(v) }}>{fmtCell(v)}</td>;
                    })}
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="pos-total pt-total">
                <td className="pos-cat" style={{ fontFamily: 'var(--font-mono)' }}>Grand Total</td>
                {[0, 1, 2].map((i) => {
                  const v = block === 'absolute' ? GT_ABS[i] : GT_DUR[i];
                  return <td key={i} className="pos-num pt-num" style={block === 'duration' ? { color: 'var(--warning)' } : undefined}>{fmtCell(v)}</td>;
                })}
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* slide-in detail panel (leaf rows only): Absoluto (con suma) + Duración */}
      {detailRow && (
        <>
          <div className="pos-detail-overlay" onClick={() => setDetailRow(null)} />
          <div className="pos-detail">
            <div className="pos-detail-head">
              <span className="pos-detail-title">{detailRow.label}</span>
              <button type="button" className="measure-close" onClick={() => setDetailRow(null)} aria-label="Close detail">×</button>
            </div>

            <div className="pos-detail-block">
              <div className="pos-detail-block-title" style={{ color: BLOCK_META.absolute.accent }}>Absolute Positioning</div>
              {[0, 1, 2].map((i) => (
                <div className="pos-detail-row" key={i}>
                  <span className="pos-detail-label">{SLEEVES[i]}</span>
                  <span className="pos-detail-val">{(detailRow.abs[i] * 100).toFixed(2)}%</span>
                </div>
              ))}
              <div className="pos-detail-row pos-detail-sum">
                <span className="pos-detail-label">Total exposure (sum)</span>
                <span className="pos-detail-val">{((detailRow.abs[0] + detailRow.abs[1] + detailRow.abs[2]) * 100).toFixed(2)}%</span>
              </div>
            </div>

            <div className="pos-detail-block">
              <div className="pos-detail-block-title" style={{ color: BLOCK_META.duration.accent }}>Duration Contribution</div>
              {[0, 1, 2].map((i) => (
                <div className="pos-detail-row" key={i}>
                  <span className="pos-detail-label">Dur{SLEEVES[i]}</span>
                  <span className="pos-detail-val">{detailRow.dur[i].toFixed(2)}yr</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
