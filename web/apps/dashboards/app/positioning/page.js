
// web/apps/dashboards/app/positioning/page.js
// ---------------------------------------------------------------------------
// Positioning dashboard. Portfolio + period come from the global header; the
// period END drives the "as of" snapshot (backend snaps to latest <= date).
// KPI bar + holdings table (with Δ Weight vs the prior snapshot) + breakdown donut.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { apiGet, pct, num } from '../../lib/api';
import { useDashboard } from '../../components/DashboardProvider';
import KpiBar from '../../components/KpiBar';
import DataTable from '../../components/DataTable';

const PlotlyChart = dynamic(() => import('../../components/PlotlyChart'), { ssr: false });
const ASSET_COLOR = { equity: '#5B8CFF', bond: '#2DD4A0', fund: '#F5A623', cash: '#8892A4' };

export default function PositioningPage() {
  const { portfolioId, range } = useDashboard();
  const [data, setData] = useState(null);
  const [prevWeights, setPrevWeights] = useState({}); // entity_id -> weight (prior snapshot)
  const [breakdown, setBreakdown] = useState('asset_class');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!portfolioId) return;
    setLoading(true); setError(null);
    apiGet(`/api/portfolios/${portfolioId}/holdings?date=${range.to}`)
      .then(async (d) => {
        setData(d);
        // prior snapshot for Δ weight
        try {
          const dates = await apiGet(`/api/portfolios/${portfolioId}/dates`); // newest-first
          const idx = dates.indexOf(d.reference_date);
          const prior = idx >= 0 ? dates[idx + 1] : dates.find((x) => x < d.reference_date);
          if (prior) {
            const pd = await apiGet(`/api/portfolios/${portfolioId}/holdings?date=${prior}`);
            const m = {};
            (pd.holdings || []).forEach((h) => { m[h.entity_id] = h.weight; });
            setPrevWeights(m);
          } else setPrevWeights({});
        } catch { setPrevWeights({}); }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [portfolioId, range.to]);

  const holdings = (data?.holdings || []).map((h) => ({
    ...h, __key: h.entity_id,
    d_weight: prevWeights[h.entity_id] != null ? h.weight - prevWeights[h.entity_id] : null,
  }));
  const buckets = breakdown === 'asset_class'
    ? (data?.summary?.by_asset_class || [])
    : (data?.summary?.by_currency || []);

  const aum = data?.total_market_value;
  const ccy = data?.portfolio?.base_currency || '';
  const largest = holdings.reduce((mx, h) => (!mx || h.weight > mx.weight ? h : mx), null);
  const cashPct = holdings.filter((h) => h.asset_class === 'cash').reduce((a, h) => a + (h.weight || 0), 0);

  const kpis = [
    { label: 'AUM', value: aum != null ? num(aum, 0) : '—', meta: ccy },
    { label: '# Positions', value: holdings.length, meta: `as of ${data?.reference_date || '—'}` },
    { label: 'Largest Position', value: largest ? pct(largest.weight) : '—', meta: largest ? largest.display_name : '' },
    { label: 'Cash %', value: pct(cashPct), meta: 'of AUM' },
  ];

  const pieTrace = {
    type: 'pie',
    labels: buckets.map((b) => b.key),
    values: buckets.map((b) => b.weight),
    marker: breakdown === 'asset_class' ? { colors: buckets.map((b) => ASSET_COLOR[b.key] || '#8892A4') } : undefined,
    textinfo: 'label+percent', hole: 0.5, sort: false,
  };

  const cols = [
    { key: 'display_name', label: 'Security', align: 'left' },
    { key: 'asset_class', label: 'Class', align: 'left', render: (v) => <span className="tag">{v}</span> },
    { key: 'sector', label: 'Sector', align: 'left', render: (v) => v || '—' },
    { key: 'source', label: 'Source', align: 'left' },
    { key: 'quantity', label: 'Quantity', numeric: true, render: (v) => num(v, 0) },
    { key: 'market_value', label: 'Market Value', numeric: true, render: (v) => num(v, 0) },
    { key: 'weight', label: 'Weight', numeric: true, render: (v) => pct(v) },
    {
      key: 'd_weight', label: 'Δ Weight', numeric: true,
      render: (v) => (v == null ? '—' : <span className={v >= 0 ? 'pos' : 'neg'}>{v >= 0 ? '+' : ''}{(v * 100).toFixed(2)}pp</span>),
      csv: (v) => (v == null ? '' : (v * 100).toFixed(4)),
    },
  ];
  const totalRow = {
    display_name: 'Total',
    market_value: <span className="num">{num(aum, 0)}</span>,
    weight: <span className="num">{pct(holdings.reduce((a, h) => a + (h.weight || 0), 0))}</span>,
  };
  const exportName = `${data?.portfolio?.procode || 'portfolio'}_positioning_${range.from}_${range.to}`;

  return (
    <div>
      <h1 className="page-title">Positioning</h1>
      <p className="page-sub">Holdings as of the period end (latest snapshot on/before), with weight breakdown.</p>

      <KpiBar tiles={kpis} />

      {error && <div className="panel error">Error: {error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 18, alignItems: 'start' }}>
        <div className="panel">
          {loading ? <div className="loading">Loading…</div>
            : holdings.length
              ? <DataTable columns={cols} rows={holdings} initialSort="weight" totalRow={totalRow} exportName={exportName} storageKey="positioning" />
              : <div className="muted">No holdings.</div>}
        </div>
        <div className="panel">
          <div className="panel-title">Weight by {breakdown === 'asset_class' ? 'asset class' : 'currency'}</div>
          <div className="field" style={{ marginBottom: 10 }}>
            <select className="select" value={breakdown} onChange={(e) => setBreakdown(e.target.value)}>
              <option value="asset_class">By asset class</option>
              <option value="currency">By currency</option>
            </select>
          </div>
          {buckets.length
            ? <PlotlyChart data={[pieTrace]} layout={{ showlegend: false }} style={{ height: '340px' }} />
            : <div className="muted">—</div>}
        </div>
      </div>
    </div>
  );
}

