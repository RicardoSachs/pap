// web/apps/dashboards/app/benchmarks/page.js
// ---------------------------------------------------------------------------
// Benchmarks · Panel: one composite index at a time - its level series over
// a window, in level or base 100, next to the house fund it is assigned to
// (SPP_BENCH_F2 -> PROFUTURO Fund 2); the returns over the standard
// windows; and the composition in force.
//
// Everything comes from /api/benchmarks (levels, versions) and, for the
// overlay, /api/spp/series. Nothing here is written.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import { apiGet } from '../../lib/api';
import {
  WINDOWS, colorOf, periodWindow, windowStart, fDate, fTime, fmtReturn, grayLine, nInt, sign,
  shownValue,
} from '../../lib/spp';
import DataDownload from '../../components/DataDownload';
import SppSeg from '../../components/SppSeg';
import { useDashboard } from '../../components/DashboardProvider';
import { useModule } from '../../components/ModuleContext';
import { chartTheme } from '../../lib/theme';

const PlotlyChart = dynamic(() => import('../../components/PlotlyChart'), { ssr: false });

const METHODS = {
  buy_and_hold: 'Manual rebalancing', fixed_weights: 'Fixed weights (periodic rebalancing)', heuristic: 'Heuristic',
};
const RETURN_WINDOWS = [['MTD', 'mtd'], ['YTD', 'ytd'], ['FY', 'fy'], ['1Y', 1], ['3Y', 3], ['5Y', 5]];

// The fund type a benchmark is paired with: the assignment made in
// Registry, or, for an index declared before assignments existed, its
// procode suffix.
const fundOf = (procode) => {
  const m = /_F(\d)$/.exec(procode || '');
  return m ? Number(m[1]) : null;
};

// Return of a [date, value] series over a window ending at its last point:
// the base is the last point at or before the window's calendar start.
function windowReturn(points, w) {
  if (!points?.length) return null;
  const last = points[points.length - 1];
  const start = windowStart(w, { to: last[0] }, null);
  const base = [...points].reverse().find((p) => p[0] <= start);
  return base && base[1] ? last[1] / base[1] - 1 : null;
}

export default function BenchmarksPanelPage() {
  const [list, setList] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [selected, setSelected] = useState('');
  // Fund type and period come from the floating pill: the fund narrows
  // the indices to those assigned to it ('all' shows every one), the
  // period is the chart's window.
  const pill = useModule();
  const dash = useDashboard();
  const pillFund = pill?.fund ?? 'all';
  const period = dash?.period || 'YTD';
  const [scale, setScale] = useState('base');
  const [compare, setCompare] = useState(true);
  const [levels, setLevels] = useState(null);       // the whole series, once per benchmark
  const [house, setHouse] = useState(null);         // the house fund over the window
  const [versions, setVersions] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet('/api/benchmarks').then((j) => {
      const items = j.benchmarks || [];
      setList(items);
      setSelected((s) => s || items.find((b) => b.points)?.procode || items[0]?.procode || '');
    }).catch((e) => setError(e.message));
    apiGet('/api/spp/config').then(setCfg).catch(() => {});
  }, []);

  const visible = useMemo(
    () => (list || []).filter((b) => pillFund === 'all' || b.fund === pillFund), [list, pillFund]);
  // Keep the selection inside the fund in view.
  useEffect(() => {
    if (list && !visible.some((b) => b.procode === selected)) {
      setSelected(visible.find((b) => b.points)?.procode || visible[0]?.procode || '');
    }
  }, [list, visible, selected]);

  const current = (list || []).find((b) => b.procode === selected) || null;
  const fund = current?.fund ?? fundOf(selected);
  const houseName = cfg?.house;

  // The benchmark's whole series: the window is cut client-side so the
  // returns table can look back further than the chart.
  useEffect(() => {
    if (!selected) return undefined;
    let live = true;
    setLevels(null); setHouse(null); setError(null);
    const p = encodeURIComponent(selected);
    apiGet(`/api/benchmarks/${p}/levels`)
      .then((j) => { if (live) setLevels(j.points || []); })
      .catch((e) => { if (live) setError(e.message); });
    apiGet(`/api/benchmarks/${p}/versions`)
      .then((j) => { if (live) setVersions(j.versions || []); })
      .catch(() => { if (live) setVersions([]); });
    return () => { live = false; };
  }, [selected]);

  // The window, from the pill's period counted back from the series' own
  // last date (Custom brings its own two dates).
  const lastDate = levels?.length ? levels[levels.length - 1][0] : null;
  const win = useMemo(() => periodWindow(period, lastDate,
    { customFrom: dash?.customFrom, customTo: dash?.customTo }),
  [period, lastDate, dash?.customFrom, dash?.customTo]);
  const from = win.from;
  const to = win.to || lastDate;
  const windowed = useMemo(
    () => (levels || []).filter((p) => (!from || p[0] >= from) && (!to || p[0] <= to)), [levels, from, to]);

  // The house fund of the same type, over the same window, for the overlay.
  useEffect(() => {
    if (!compare || fund == null || !houseName || !from || !to) { setHouse(null); return undefined; }
    let live = true;
    const q = new URLSearchParams({ fund: String(fund), afps: houseName, metric: 'valor_cuota', from, to });
    apiGet(`/api/spp/series?${q}`)
      .then((d) => { if (live) setHouse(d.series?.[0]?.points || []); })
      .catch(() => { if (live) setHouse(null); });
    return () => { live = false; };
  }, [compare, fund, houseName, from, to]);

  const ct = chartTheme();
  const traces = useMemo(() => {
    if (!windowed.length) return [];
    const base100 = scale === 'base';
    const rebase = (pts) => {
      const b = pts[0]?.[1];
      return pts.map((p) => (base100 && b ? (p[1] / b) * 100 : p[1]));
    };
    const out = [{
      x: windowed.map((p) => p[0]), y: rebase(windowed),
      type: 'scatter', mode: 'lines', name: current?.display_name || selected,
      line: { color: ct.brand, width: 2.6 },
      hovertemplate: `<b>${current?.display_name || selected}</b>  %{y:,.4f}<extra></extra>`,
    }];
    // The overlay only makes sense rebased: a cuota of 280 and an index of
    // 115 share no scale.
    if (base100 && house?.length) {
      // Start both lines on the first date both have: one zero for the two.
      const first = windowed[0][0] > house[0][0] ? windowed[0][0] : house[0][0];
      const hp = house.filter((p) => p[0] >= first);
      const bp = windowed.filter((p) => p[0] >= first);
      out[0].x = bp.map((p) => p[0]); out[0].y = rebase(bp);
      out.push({
        x: hp.map((p) => p[0]), y: rebase(hp),
        type: 'scatter', mode: 'lines', name: `${houseName} F${fund}`,
        line: { color: colorOf(cfg, houseName, true) || grayLine(0.8), width: 1.8, dash: 'dot' },
        hovertemplate: `<b>${houseName} F${fund}</b>  %{y:,.4f}<extra></extra>`,
      });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowed, house, scale, current, cfg]);

  const latest = versions.length ? versions[versions.length - 1] : null;
  const windowLabel = period === 'Custom' && dash?.customFrom && dash?.customTo
    ? `${fDate(dash.customFrom)} to ${fDate(dash.customTo)}` : period;
  const title = `${current?.display_name || '—'}`;
  const footer = scale === 'base' ? 'Rebased to 100' : 'In level';
  const fileName = (t) => t.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

  return (
    <div className="bm-page">
      {/* The upstream masthead: brand name over the dashboard title, then
          the one-line subtitle, so every dashboard opens the same way. */}
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">Benchmarks</div>
      </div>
      <p className="page-sub">
        The desk's composite indices · {list ? `${nInt(list.length)} declared` : '—'}
        {current?.points ? ` · ${current.display_name}: ${nInt(current.points)} dates (${fDate(current.from)} to ${fDate(current.to)})` : ''}
      </p>
      {error && <div className="panel error">Error: {error}</div>}

      <div className="panel">
        <div className="controls spp-controls">
          <div className="field"><label>Benchmark{pillFund === 'all' ? '' : ` · Fund ${pillFund}`}</label>
            {visible.length
              ? <SppSeg items={visible.map((b) => [b.display_name, b.procode])} value={selected} onChange={setSelected} />
              : <span className="dim">No benchmark assigned to this fund.</span>}</div>
          <div className="field"><label>Scale</label>
            <SppSeg items={[['Level', 'level'], ['Base 100', 'base']]} value={scale} onChange={setScale} /></div>
          {fund != null && houseName && (
            <div className="field"><label>Compare</label>
              <SppSeg items={[[`${houseName} F${fund}`, true], ['Index only', false]]}
                value={compare} onChange={setCompare} /></div>
          )}
        </div>
      </div>

      <div className="spp-two-up">
        <div className="panel">
          <div className="spp-chart-header">
            <span />
            <div className="panel-title" style={{ margin: 0 }}>{title}</div>
            <DataDownload traces={traces} name={fileName(`${title} · ${footer} · ${windowLabel}`)} />
          </div>
          {traces.length ? (
            <PlotlyChart
              data={traces}
              layout={{
                margin: { l: 70, r: 20, t: 10, b: 60 },
                hovermode: 'x unified',
                xaxis: { hoverformat: '%d %b %Y' },
                yaxis: { type: 'linear', title: scale === 'base' ? 'Base 100' : 'Level' },
              }}
            />
          ) : levels === null
            ? <div className="loading">Loading…</div>
            : <p className="page-sub dim">No computed levels for this benchmark: declare a version and rebuild in <b>Registry</b>.</p>}
          {traces.length > 0 && (
            <p className="page-sub dim" style={{ textAlign: 'center', margin: '6px 0 0' }}>
              {footer}{scale === 'base' && house?.length ? ` · ${houseName} F${fund} dotted, from the first common date` : ''}
            </p>
          )}
        </div>

        <div className="panel">
          <div className="panel-title">Performance</div>
          <p className="page-sub">At the last computed level{lastDate ? ` (${fDate(lastDate)})` : ''}; each window
            starts at the last close before its start.</p>
          <table className="spp-report"><tbody>
            {RETURN_WINDOWS.map(([label, w]) => {
              const r = windowReturn(levels, w);
              return (
                <tr key={label}><td>{label}</td>
                  <td className={`num ${r == null ? 'dim' : sign(shownValue(r, 'pct'))}`}>{fmtReturn(r, 'pct')}</td></tr>
              );
            })}
            <tr><td>Last level</td><td className="num">{current?.last_level == null ? '—'
              : current.last_level.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td></tr>
          </tbody></table>

          <div className="panel-title" style={{ marginTop: 16 }}>Current composition</div>
          {latest ? (
            <>
              <p className="page-sub" style={{ margin: '2px 0 6px' }}>
                Version {latest.version_id} · from {fDate(latest.effective_from)} · {METHODS[latest.method] || latest.method}
                {latest.rebalance_frequency ? ` (${latest.rebalance_frequency})` : ''}
                {' · '}<b>{latest.reason}</b> · recorded {fTime(latest.created_at)}
                {latest.recorded_by ? ` by ${latest.recorded_by}` : ''}
              </p>
              <table className="spp-report"><tbody>
                {latest.constituents.map((c) => (
                  <tr key={c.series_id}>
                    <td>{c.label}{c.fx_series_id ? ' (with FX)' : ''} <span className="dim">· {c.procode} · {c.source}</span></td>
                    <td className="num">{(c.weight * 100).toLocaleString('es-PE', { maximumFractionDigits: 2 })} %</td>
                  </tr>
                ))}
              </tbody></table>
              <p className="page-sub dim" style={{ marginTop: 8 }}>
                {versions.length} version(s) in total; the full history is in <b>Registry</b>.
              </p>
            </>
          ) : <p className="page-sub dim">No versions declared.</p>}
        </div>
      </div>
    </div>
  );
}
