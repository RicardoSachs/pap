// web/apps/dashboards/app/contribution/page.js
// ---------------------------------------------------------------------------
// Contribution dashboard. Portfolio, period, and source all come from the
// global header. Bars sorted by contribution magnitude (largest positive at
// top, largest negative at bottom), teal/rose with a vertical zero line.
// KPI bar in bps + enhanced detail table with a sticky portfolio total row.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { apiGet, pct, num } from '../../lib/api';
import { useDashboard } from '../../components/DashboardProvider';
import KpiBar from '../../components/KpiBar';
import DataTable from '../../components/DataTable';

const PlotlyChart = dynamic(() => import('../../components/PlotlyChart'), { ssr: false });
const TEAL = '#2DD4A0';
const ROSE = '#F06580';

const bps = (x) => `${x >= 0 ? '+' : ''}${Math.round(x * 10000)} bps`;

// Deterministic 30-point trend around a seed (contribution is a period snapshot
// with no intraperiod history — renders a stable KPI sparkline).
function synthSpark(seed, n = 30) {
  const s = seed || 1;
  const out = [];
  for (let i = 0; i < n; i++) {
    const trend = 0.9 + 0.1 * (i / (n - 1));
    const wiggle = Math.sin((i + 1) * (Math.abs(s) * 6.283 + 1)) * 0.04;
    out.push(s * (trend + wiggle));
  }
  return out;
}

export default function ContributionPage() {
  const { portfolioId, range, source } = useDashboard();
  const [data, setData] = useState(null);
  const [aum, setAum] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!portfolioId) return;
    setLoading(true); setError(null);
    (async () => {
      try {
        // Clamp the period start to the earliest available snapshot so the
        // beginning-weights lookup never falls before the data (e.g. YTD on a
        // portfolio whose history starts mid-year). Uses the existing /dates endpoint.
        const dates = await apiGet(`/api/portfolios/${portfolioId}/dates`); // newest-first
        const earliest = dates[dates.length - 1];
        const from = (earliest && range.from < earliest) ? earliest : range.from;
        const [c, h] = await Promise.all([
          apiGet(`/api/portfolios/${portfolioId}/contribution?from=${from}&to=${range.to}&source=${source}`),
          apiGet(`/api/portfolios/${portfolioId}/holdings?date=${range.to}`).catch(() => null),
        ]);
        setData(c);
        setAum(h?.total_market_value ?? null);
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, [portfolioId, range.from, range.to, source]);

  const holdings = (data?.holdings || []).map((h) => ({ ...h, __key: h.entity_id }));
  const ret = data?.portfolio_return ?? 0;
  const top = holdings.length ? holdings.reduce((mx, h) => (h.contribution > mx.contribution ? h : mx), holdings[0]) : null;
  const bottom = holdings.length ? holdings.reduce((mn, h) => (h.contribution < mn.contribution ? h : mn), holdings[0]) : null;

  const kpis = [
    { label: 'AUM', value: aum != null ? num(aum, 0) : '—', meta: data?.portfolio?.base_currency || '', spark: aum != null ? synthSpark(aum) : null },
    { label: 'Period Return', value: bps(ret), tone: ret >= 0 ? 'pos' : 'neg', meta: `${data?.period?.from || range.from} → ${data?.period?.to || range.to}`, accent: true, spark: synthSpark(ret) },
    { label: 'Top Contributor', value: top ? bps(top.contribution) : '—', tone: 'pos', meta: top ? top.display_name : '', spark: top ? synthSpark(top.contribution) : null },
    { label: 'Top Detractor', value: bottom ? bps(bottom.contribution) : '—', tone: 'neg', meta: bottom ? bottom.display_name : '' },
    { label: '# Positions', value: holdings.length, meta: `source: ${source}` },
  ];

  // sort ascending so the largest positive sits at the TOP of a horizontal bar
  const barRows = [...holdings].sort((a, b) => a.contribution - b.contribution);
  const barTrace = {
    type: 'bar', orientation: 'h',
    y: barRows.map((h) => h.display_name),
    x: barRows.map((h) => h.contribution * 100),
    marker: { color: barRows.map((h) => (h.contribution >= 0 ? TEAL : ROSE)) },
    hovertemplate: '%{y}: %{x:.3f}%<extra></extra>',
  };

  const cols = [
    { key: 'display_name', label: 'Security', align: 'left' },
    { key: 'asset_class', label: 'Class', align: 'left', render: (v) => <span className="tag">{v}</span> },
    { key: 'weight', label: 'Weight', numeric: true, render: (v) => pct(v) },
    { key: 'return', label: 'Return', numeric: true, render: (v) => <span className={v >= 0 ? 'pos' : 'neg'}>{pct(v)}</span>, csv: (v) => v },
    { key: 'contribution', label: 'Contribution', numeric: true, render: (v) => <span className={v >= 0 ? 'pos' : 'neg'}>{bps(v)}</span>, csv: (v) => Math.round(v * 10000) },
  ];
  const totalRow = {
    display_name: 'Portfolio',
    contribution: <span className={`num ${ret >= 0 ? 'pos' : 'neg'}`}>{bps(ret)}</span>,
  };
  const exportName = `${data?.portfolio?.procode || 'portfolio'}_contribution_${range.from}_${range.to}`;

  return (
    <div>
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">Contribution</div>
      </div>
      <p className="page-sub">Per-holding contribution to portfolio return over the period (weight × return).</p>

      <KpiBar tiles={kpis} />

      {error && <div className="panel error">Error: {error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, alignItems: 'start' }}>
        <div className="panel">
          <div className="panel-title">Contribution by holding (%)</div>
          {loading ? <div className="loading">Loading…</div>
            : holdings.length
              ? (
                <PlotlyChart
                  data={[barTrace]}
                  layout={{
                    margin: { l: 160, r: 20, t: 10, b: 40 },
                    xaxis: { title: '%', zeroline: true, zerolinewidth: 2 },
                    yaxis: { automargin: true },
                  }}
                  style={{ height: `${Math.max(360, holdings.length * 26)}px` }}
                />
              )
              : <div className="muted">—</div>}
        </div>
        <div className="panel">
          <div className="panel-title">Detail</div>
          {loading ? <div className="loading">Loading…</div>
            : holdings.length
              ? <DataTable columns={cols} rows={holdings} initialSort="contribution" totalRow={totalRow} exportName={exportName} storageKey="contribution" />
              : <div className="muted">No data.</div>}
        </div>
      </div>
    </div>
  );
}
