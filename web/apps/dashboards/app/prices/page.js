
// web/apps/dashboards/app/prices/page.js
// ---------------------------------------------------------------------------
// Price Viewer (by source): a security's price history, one line per source.
// Range comes from the global header (period). Keeps the Bloomberg-style hover
// tooltip + crosshair + x-axis date tag, adds a KPI bar and a source-comparison
// table below the chart.
//
// NOTE on sources: the reference data has price sources bloomberg / sbs /
// scraper (FMS is a *positions* source, not a price source). The comparison
// table therefore compares Bloomberg against the next available price source.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState, useMemo } from 'react';
import dynamic from 'next/dynamic';
import { apiGet, pct, num } from '../../lib/api';
import { useDashboard } from '../../components/DashboardProvider';
import KpiBar from '../../components/KpiBar';
import DataTable from '../../components/DataTable';
import SecuritySearch from '../../components/SecuritySearch';
import { chartTheme } from '../../lib/theme';

const PlotlyChart = dynamic(() => import('../../components/PlotlyChart'), { ssr: false });

const SOURCE_COLOR = { bloomberg: '#5B8CFF', sbs: '#2DD4A0', scraper: '#F5A623', fms: '#A78BFA' };

const NBSP = String.fromCharCode(160);
const labelCell = (t) => { const b = `${t}:`; return b + NBSP.repeat(Math.max(1, 8 - b.length)); };
const hoverTemplate = (color) =>
  `<span style="color:#8892A4">${labelCell('Source')}</span><b><span style="color:${color}">%{customdata[2]}</span></b><br>` +
  `<span style="color:#8892A4">${labelCell('Date')}</span>%{customdata[0]}<br>` +
  `<span style="color:#8892A4">${labelCell('Return')}</span>%{customdata[1]:+.2f}%<br>` +
  `<span style="color:#8892A4">${labelCell('Price')}</span>%{customdata[3]:,.4f}<extra></extra>`;
// Structural spike config only; colors are injected by PlotlyChart from the theme.
const SPIKE = {
  showspikes: true, spikemode: 'across', spikesnap: 'hovered data',
  spikethickness: 1, spikedash: 'dot',
};

export default function PricesPage() {
  const { range } = useDashboard();
  const [selected, setSelected] = useState(null);
  const [entityId, setEntityId] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [hoverDate, setHoverDate] = useState(null);

  useEffect(() => {
    if (!entityId) return;
    setLoading(true); setError(null);
    apiGet(`/api/prices?entity_id=${entityId}&from=${range.from}&to=${range.to}`)
      .then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [entityId, range.from, range.to]);

  const entity = data?.entity;
  const series = data?.series || [];

  const traces = series.map((s) => {
    const color = SOURCE_COLOR[s.source] || '#8892A4';
    const firstValid = s.points.find((p) => p.price != null);
    const base = firstValid ? firstValid.price : null;
    return {
      x: s.points.map((p) => p.date),
      y: s.points.map((p) => p.price),
      customdata: s.points.map((p) => [p.date, base ? (p.price / base - 1) * 100 : 0, s.source.toUpperCase(), p.price]),
      type: 'scatter', mode: 'lines', name: s.source,
      line: { color, width: 2 },
      hovertemplate: hoverTemplate(color),
      hoverlabel: { bordercolor: color },
    };
  });

  // KPI inputs: prefer bloomberg as the primary series
  const primary = series.find((s) => s.source === 'bloomberg') || series[0];
  const lastPt = primary?.points?.[primary.points.length - 1];
  const firstPt = primary?.points?.find((p) => p.price != null);
  const periodRet = (firstPt && lastPt && firstPt.price) ? lastPt.price / firstPt.price - 1 : null;
  const latest = series.map((s) => s.points[s.points.length - 1]?.price).filter((v) => v != null);
  const spread = latest.length > 1 ? (Math.max(...latest) - Math.min(...latest)) / (latest.reduce((a, b) => a + b, 0) / latest.length) : 0;

  const kpis = [
    { label: 'Security', value: entity?.ticker || entity?.display_name || '—', meta: entity?.display_name || '' },
    { label: 'Latest Price', value: lastPt ? num(lastPt.price, 4) : '—', meta: lastPt ? `${primary.source} · ${lastPt.date}` : '' },
    { label: 'Period Return', value: periodRet != null ? pct(periodRet) : '—', tone: periodRet >= 0 ? 'pos' : 'neg', meta: 'window' },
    { label: 'Sources', value: series.length <= 1 ? 'Single' : (spread > 0.0025 ? 'Diverge' : 'Agree'), meta: `${series.length} src · ${(spread * 100).toFixed(2)}% spread` },
  ];

  // x-axis date tag (paper-anchored annotation, follows the hovered point)
  const handleHover = (e) => { const pt = e?.points?.[0]; if (pt) setHoverDate(pt.customdata?.[0] ?? pt.x); };
  const handleUnhover = () => setHoverDate(null);
  const ct = chartTheme();
  const dateTag = hoverDate ? [{
    x: hoverDate, xref: 'x', y: 0, yref: 'paper', yanchor: 'top', yshift: -6,
    text: hoverDate, showarrow: false,
    bgcolor: ct.panel, bordercolor: ct.border, borderwidth: 1, borderpad: 4,
    font: { family: "var(--font-plex), 'IBM Plex Mono', monospace", size: 11, color: ct.text },
  }] : [];

  // source comparison table: Bloomberg vs next available source
  const colA = series.find((s) => s.source === 'bloomberg') || series[0];
  const colB = series.find((s) => s !== colA);
  const cmpRows = useMemo(() => {
    if (!colA || !colB) return [];
    const mapB = new Map(colB.points.map((p) => [p.date, p.price]));
    return colA.points
      .filter((p) => mapB.has(p.date))
      .map((p) => {
        const a = p.price; const b = mapB.get(p.date); const delta = a - b;
        const rel = a ? Math.abs(delta) / a : 0;
        return { __key: p.date, date: p.date, a, b, delta, flag: rel > 0.005 ? '⚠ divergence' : '' };
      })
      .reverse();
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const cmpCols = [
    { key: 'date', label: 'Date' },
    { key: 'a', label: (colA?.source || 'A').toUpperCase(), numeric: true, render: (v) => num(v, 4) },
    { key: 'b', label: (colB?.source || 'B').toUpperCase(), numeric: true, render: (v) => num(v, 4) },
    { key: 'delta', label: 'Δ', numeric: true, render: (v) => <span className={v >= 0 ? 'pos' : 'neg'}>{v >= 0 ? '+' : ''}{num(v, 4)}</span>, csv: (v) => v },
    { key: 'flag', label: 'Flag', align: 'left', sortable: false, render: (v) => (v ? <span className="flag-warn">{v}</span> : '') },
  ];
  const cmpName = `${entity?.ticker || 'security'}_prices_${range.from}_${range.to}`;

  return (
    <div>
      <h1 className="page-title">Price Viewer</h1>
      <p className="page-sub">Daily prices for one security, one line per source.</p>

      <KpiBar tiles={kpis} />

      <div className="panel">
        <div className="controls">
          <div className="field">
            <label>Security</label>
            <SecuritySearch
              value={selected}
              onSelect={(s) => { setSelected(s); setEntityId(String(s.entity_id)); }}
            />
          </div>
        </div>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      <div className="panel">
        {loading ? (
          <div className="loading">Loading…</div>
        ) : traces.length ? (
          <PlotlyChart
            data={traces}
            onHover={handleHover}
            onUnhover={handleUnhover}
            layout={{
              hovermode: 'closest', hoverdistance: 30,
              margin: { l: 60, r: 20, t: 30, b: 64 },
              annotations: dateTag,
              xaxis: { title: '', hoverformat: '%Y-%m-%d', ...SPIKE },
              yaxis: { title: entity?.base_currency || 'Price', zeroline: false, ...SPIKE },
            }}
          />
        ) : (
          <div className="muted">No price data for this selection.</div>
        )}
      </div>

      <div className="panel">
        <div className="panel-title">Source comparison</div>
        {cmpRows.length ? (
          <DataTable columns={cmpCols} rows={cmpRows} initialSort="date" exportName={cmpName} storageKey="prices_cmp" />
        ) : (
          <div className="muted">Need at least two price sources to compare.</div>
        )}
      </div>
    </div>
  );
}

