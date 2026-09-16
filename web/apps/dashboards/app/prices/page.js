// web/apps/dashboards/app/prices/page.js
// ---------------------------------------------------------------------------
// Price Viewer (by source): a security's price history, one line per source.
// Range comes from the global header (period). Rich Bloomberg-style chart
// interactivity (custom floating data card + stats ribbon, full crosshair,
// axis bubbles, hover lock, point-compare, drag-measure, shift-zoom, divergence
// bands/flag, right-click menu + annotations), plus a KPI bar and a
// source-comparison table below the chart.
//
// react-plotly.js is a CONTROLLED wrapper: it re-applies layout via Plotly.react
// on every render, and this page re-renders on hover (the floating card is React
// state). So all chart-state that must survive hover — dragmode, shapes, the
// transient + persistent annotations — is driven DECLARATIVELY through the
// controlled layout (keyed on React state) rather than imperative Plotly.relayout
// (which would be clobbered on the next render). uirevision preserves zoom/pan
// across those hover re-renders.
//
// NOTE on sources: price sources are bloomberg / sbs / scraper (FMS is a
// *positions* source, not a price source).
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import dynamic from 'next/dynamic';
import { apiGet, pct, num } from '../../lib/api';
import { downloadCsv } from '../../lib/csv';
import { useDashboard } from '../../components/DashboardProvider';
import KpiBar from '../../components/KpiBar';
import SecuritySearch from '../../components/SecuritySearch';
import { fmtDisplay } from '../../lib/period';
import { useThemeVersion } from '../../lib/theme';

const PlotlyChart = dynamic(() => import('../../components/PlotlyChart'), { ssr: false });

const SOURCE_COLOR = { bloomberg: '#5B8CFF', sbs: '#2DD4A0', scraper: '#F5A623', fms: '#A78BFA', benchmark: '#A78BFA' };
const SOURCE_LABEL = { bloomberg: 'Bloomberg', sbs: 'SBS', scraper: 'Scraper', fms: 'FMS' };

// Highlight a row's Return Difference when |Bloomberg return − SBS return| exceeds this.
const RETURN_DIFF_THRESHOLD = 0.005; // 0.50%

const PLEX = "var(--font-plex), 'IBM Plex Mono', monospace";

const fmtPrice = (v) => (v == null ? '—' : v.toFixed(2));
const fmtReturn = (v) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`);
const retClass = (v) => (v == null ? '' : v >= 0 ? 'pos' : 'neg');
// percent value (already in %) -> "+1.23%" style
const sgnPct = (v) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`);
const sgnNum = (v) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}`);

// user annotations (chart notes) persist under this localStorage key across reloads
const ANNO_STORAGE_KEY = 'priceChartAnnotations';
const STAMP_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad2 = (n) => String(n).padStart(2, '0');
// ISO timestamp -> "DD MMM YYYY HH:mm"
const fmtStamp = (iso) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${pad2(d.getDate())} ${STAMP_MONTHS[d.getMonth()]} ${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};

// Source-comparison table columns (Date is always shown and is NOT toggleable).
const CMP_STORAGE_KEY = 'priceTableColumns';
const CMP_COLUMNS = [
  { key: 'bPrice', label: 'Bloomberg Price', src: 'bloomberg' },
  { key: 'bRet', label: 'Bloomberg Return', src: 'bloomberg' },
  { key: 'sPrice', label: 'SBS Price', src: 'sbs' },
  { key: 'sRet', label: 'SBS Return', src: 'sbs' },
  { key: 'diff', label: 'Return Difference', src: 'cmp' },
];
const CMP_GROUPS = [
  { label: 'Bloomberg', src: 'bloomberg', cols: [
    { key: 'bPrice', label: 'Price', width: 120, type: 'price' },
    { key: 'bRet', label: 'Return', width: 110, type: 'ret' },
  ] },
  { label: 'SBS', src: 'sbs', cols: [
    { key: 'sPrice', label: 'Price', width: 120, type: 'price' },
    { key: 'sRet', label: 'Return', width: 110, type: 'ret' },
  ] },
  { label: 'Comparison', src: 'cmp', cols: [
    { key: 'diff', label: 'Return Diff', width: 130, type: 'diff' },
  ] },
];
const CMP_VAL = { bPrice: (r) => r.bPrice, bRet: (r) => r.bRet, sPrice: (r) => r.sPrice, sRet: (r) => r.sRet, diff: (r) => r.diff };

// Feature 1 — full crosshair. x tracks the cursor date, y snaps to the data price.
const X_SPIKE = { showspikes: true, spikemode: 'across', spikesnap: 'cursor', spikedash: 'dot', spikecolor: '#5B8CFF', spikethickness: 1 };
const Y_SPIKE = { showspikes: true, spikemode: 'across', spikesnap: 'data', spikedash: 'dot', spikecolor: '#5B8CFF', spikethickness: 1 };

// Feature 10 — stats ribbon: price `n` data points back, falling back to the
// earliest available point (flagged) when the series is shorter than `n`.
function priceBack(points, idx, n) {
  const j = idx - n;
  if (j < 0) { const f = points.find((p) => p.price != null); return { price: f ? f.price : null, fellBack: true }; }
  for (let k = j; k >= 0; k--) if (points[k].price != null) return { price: points[k].price, fellBack: false };
  const f = points.find((p) => p.price != null);
  return { price: f ? f.price : null, fellBack: true };
}
function buildRibbon(points, idx) {
  const cur = points[idx]?.price;
  if (cur == null) return null;
  const mk = (n, label) => {
    const { price, fellBack } = priceBack(points, idx, n);
    const value = price ? ((cur - price) / price) * 100 : null;
    return { label: fellBack ? 'Since load' : label, value };
  };
  const year = String(points[idx].date).slice(0, 4);
  let ytdBase = points.find((p) => String(p.date).slice(0, 4) === year && p.price != null);
  let ytdFell = false;
  if (!ytdBase) { ytdBase = points.find((p) => p.price != null); ytdFell = true; }
  const ytdVal = ytdBase?.price ? ((cur - ytdBase.price) / ytdBase.price) * 100 : null;
  return { items: [mk(1, '1D Return'), mk(5, '1W Return'), mk(22, '1M Return'), { label: ytdFell ? 'Since load' : 'YTD Return', value: ytdVal }] };
}

export default function PricesPage() {
  const { range, period } = useDashboard();
  const [selected, setSelected] = useState(null);
  const [entityId, setEntityId] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState(null); // floating data card + ribbon + axis bubbles snapshot
  const [hidden, setHidden] = useState(() => new Set()); // sources toggled off via the legend
  const [xRange, setXRange] = useState(null); // controlled x-axis range for the zoom buttons (null = autorange)
  const [analysing, setAnalysing] = useState(false); // Analyse mode (two-click point selection)
  const [pointA, setPointA] = useState(null); // first clicked point { date, price, fmtDate }
  const [pointB, setPointB] = useState(null); // second clicked point
  const [analysis, setAnalysis] = useState(null); // two-point analysis result panel
  const [locked, setLocked] = useState(false); // mirrors tooltipLockedRef for the LOCKED indicator
  const [ctxMenu, setCtxMenu] = useState(null); // right-click menu: { x, y, dataX, dataY, annoId } or null
  const [annotations, setAnnotations] = useState([]); // chart notes: [{ id, date, price, text, createdAt }]
  const [popover, setPopover] = useState(null); // add/edit note popover descriptor
  const [popoverText, setPopoverText] = useState(''); // controlled note input value
  const [popoverDate, setPopoverDate] = useState(''); // popover date field (YYYY-MM-DD)
  const [popoverErr, setPopoverErr] = useState({}); // { date?: bool, note?: bool } -> "Required" hints
  const chartWrapRef = useRef(null);
  const gdRef = useRef(null); // Plotly graph div (captured on init)
  const tooltipLockedRef = useRef(false); // hover-lock source of truth (read synchronously by handlers)
  const ctxMenuRef = useRef(null); // menu DOM node, for outside-click dismissal
  const annotationsRef = useRef([]); // mirror of `annotations` for synchronous reads in event handlers
  const popRef = useRef(null); // popover DOM node, for outside-click dismissal
  const annoObserverRef = useRef(null); // MutationObserver giving annotation text a pointer cursor
  useThemeVersion(); // re-render on theme toggle so themed colors re-read

  useEffect(() => {
    if (!entityId) return;
    setLoading(true); setError(null);
    apiGet(`/api/prices?entity_id=${entityId}&from=${range.from}&to=${range.to}`)
      .then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [entityId, range.from, range.to]);

  // reset legend hide-state when the security changes
  useEffect(() => { setHidden(new Set()); }, [entityId]);
  // reset zoom whenever the underlying data window changes
  useEffect(() => { setXRange(null); }, [entityId, range.from, range.to]);
  // a new security / window clears any pinned tooltip, modes, comparison + annotations (now stale)
  useEffect(() => {
    tooltipLockedRef.current = false;
    setLocked(false);
    setHover(null);
    setAnalysing(false); setPointA(null); setPointB(null); setAnalysis(null);
    setPopover(null); setPopoverText(''); // close any open note popover (notes themselves persist)
  }, [entityId, range.from, range.to]);

  // restore persisted notes on mount (into both the ref and state -> the controlled chart)
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(ANNO_STORAGE_KEY) || 'null');
      if (Array.isArray(saved)) { annotationsRef.current = saved; setAnnotations(saved); }
    } catch { /* ignore */ }
  }, []);
  // disconnect the annotation-cursor observer on unmount
  useEffect(() => () => { try { annoObserverRef.current?.disconnect(); } catch { /* ignore */ } }, []);

  // right-click context menu: dismiss on outside click or Escape
  useEffect(() => {
    if (!ctxMenu) return undefined;
    const onDown = (e) => { if (ctxMenuRef.current && !ctxMenuRef.current.contains(e.target)) setCtxMenu(null); };
    const onKey = (e) => { if (e.key === 'Escape') setCtxMenu(null); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [ctxMenu]);

  // note popover: dismiss (without saving) on outside click
  useEffect(() => {
    if (!popover) return undefined;
    const onDown = (e) => { if (popRef.current && !popRef.current.contains(e.target)) { setPopover(null); setPopoverText(''); } };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [popover]);

  const entity = data?.entity;
  const series = data?.series || [];

  const traces = series.map((s) => {
    const color = SOURCE_COLOR[s.source] || '#8892A4';
    const firstValid = s.points.find((p) => p.price != null);
    const base = firstValid ? firstValid.price : null;
    const isHidden = hidden.has(s.source);
    return {
      x: s.points.map((p) => p.date),
      y: s.points.map((p) => p.price),
      customdata: s.points.map((p, i) => {
        const prev = i > 0 ? s.points[i - 1] : null;
        const dayRet = (prev && prev.price) ? (p.price - prev.price) / prev.price : null;
        return [p.date, base ? (p.price / base - 1) * 100 : 0, SOURCE_LABEL[s.source] || s.source, p.price, dayRet, fmtDisplay(p.date), color];
      }),
      type: 'scatter', mode: 'lines', name: s.source,
      line: { color, width: 2 },
      // Native hover label invisible (custom card replaces it); crosshair + hover events still fire.
      hoverinfo: isHidden ? 'skip' : 'none',
      hoverlabel: { opacity: 0 },
      visible: isHidden ? 'legendonly' : true,
    };
  });

  // KPI inputs: prefer bloomberg as the primary series
  const primary = series.find((s) => s.source === 'bloomberg') || series[0];
  const lastPt = primary?.points?.[primary.points.length - 1];
  const firstPt = primary?.points?.find((p) => p.price != null);
  const periodRet = (firstPt && lastPt && firstPt.price) ? lastPt.price / firstPt.price - 1 : null;
  const latest = series.map((s) => s.points[s.points.length - 1]?.price).filter((v) => v != null);
  const spread = latest.length > 1 ? (Math.max(...latest) - Math.min(...latest)) / (latest.reduce((a, b) => a + b, 0) / latest.length) : 0;

  // sparkline inputs from the primary series (last 30 priced points)
  const primaryPts = (primary?.points || []).filter((p) => p.price != null);
  const priceSpark = primaryPts.slice(-30).map((p) => p.price);
  const spark0 = primaryPts[0]?.price;
  const retSpark = spark0 ? primaryPts.slice(-30).map((p) => (p.price / spark0 - 1) * 100) : null;

  const kpis = [
    { label: 'Security', value: entity?.ticker || entity?.display_name || '—', meta: entity?.display_name || '' },
    { label: 'Latest Price', value: lastPt ? num(lastPt.price, 4) : '—', meta: lastPt ? `${primary.source} · ${lastPt.date}` : '', accent: true, spark: priceSpark },
    { label: 'Period Return', value: periodRet != null ? pct(periodRet) : '—', tone: periodRet >= 0 ? 'pos' : 'neg', meta: 'window', spark: retSpark },
    { label: 'Sources', value: series.length <= 1 ? 'Single' : (spread > 0.0025 ? 'Diverge' : 'Agree'), meta: `${series.length} src · ${(spread * 100).toFixed(2)}% spread` },
  ];

  const bbgSeries = series.find((s) => s.source === 'bloomberg');
  const sbsSeries = series.find((s) => s.source === 'sbs');
  const isoDay = (ms) => new Date(ms).toISOString().slice(0, 10);

  // Returns table — which of the two compared sources actually have priced data
  const availableSources = [];
  if (bbgSeries?.points.some((p) => p.price != null)) availableSources.push('bloomberg');
  if (sbsSeries?.points.some((p) => p.price != null)) availableSources.push('sbs');
  const multiSource = availableSources.length >= 2;
  // a column group/key is shown only when its source is present (Comparison needs both)
  const colAvail = (src) => (src === 'cmp' ? multiSource : availableSources.includes(src));

  // Feature 12 — divergence: shapes (bands), a date->% map, and the ordered date list
  // (so we can flag a hovered date that is on OR within one data point of a divergence).
  const divergence = useMemo(() => {
    if (!bbgSeries || !sbsSeries || hidden.has('bloomberg') || hidden.has('sbs')) return { shapes: [], map: new Map(), dates: [] };
    const sbsMap = new Map(sbsSeries.points.map((p) => [p.date, p.price]));
    const shapes = []; const map = new Map(); const dates = [];
    for (const p of bbgSeries.points) {
      dates.push(p.date);
      const sp = sbsMap.get(p.date);
      if (p.price == null || sp == null) continue;
      if (Math.abs(p.price - sp) > RETURN_DIFF_THRESHOLD) {
        map.set(p.date, ((p.price - sp) / sp) * 100);
        shapes.push({
          type: 'rect', xref: 'x', yref: 'paper',
          x0: p.date, x1: isoDay(Date.parse(p.date) + 86400000), y0: 0, y1: 1,
          fillcolor: 'rgba(240,101,128,0.12)', line: { width: 0 }, layer: 'below',
        });
      }
    }
    return { shapes, map, dates };
  }, [data, hidden]); // eslint-disable-line react-hooks/exhaustive-deps

  const divergenceAt = (date) => {
    const { map, dates } = divergence;
    if (map.has(date)) return map.get(date);
    const i = dates.indexOf(date);
    if (i >= 0) {
      if (i > 0 && map.has(dates[i - 1])) return map.get(dates[i - 1]);
      if (i < dates.length - 1 && map.has(dates[i + 1])) return map.get(dates[i + 1]);
    }
    return null;
  };

  // --- hover (Features 2, 3, 4, 10, 11, 12, 13) ----------------------------
  const handleHover = (e) => {
    if (tooltipLockedRef.current) return; // pinned: freeze card + bubbles
    const pts = e?.points;
    if (!pts || !pts.length) return;
    const first = pts[0];
    const date = first.x;
    const fmtDate = first.customdata?.[5] ?? fmtDisplay(date);
    // bubbles / ribbon / period anchor: Bloomberg if visible, else the first visible series
    const chosenPt = pts.find((p) => p.data?.name === 'bloomberg') || pts[0];
    const bubblePrice = chosenPt?.y ?? chosenPt?.customdata?.[3] ?? null;
    const chosenSeries = series.find((s) => s.source === chosenPt?.data?.name);
    const idx = chosenPt?.pointNumber ?? chosenPt?.pointIndex;
    // one section per visible *source* series (benchmark handled separately)
    const sections = pts
      .filter((p) => p.data?.name !== 'benchmark')
      .map((p) => { const cd = p.customdata || []; return { source: p.data?.name, label: cd[2], color: cd[6], price: cd[3], dayRet: cd[4], periodRet: cd[1] }; });
    const b = sections.find((s) => s.source === 'bloomberg');
    const sb = sections.find((s) => s.source === 'sbs');
    const diff = (b && sb && b.periodRet != null && sb.periodRet != null) ? (b.periodRet - sb.periodRet) : null;
    const divPct = divergenceAt(date);
    // Feature 13 — benchmark section (only if a Benchmark trace is loaded + visible)
    let benchmark = null;
    const benchPt = pts.find((p) => p.data?.name === 'benchmark' || p.customdata?.[2] === 'Benchmark');
    if (benchPt && b && b.periodRet != null && benchPt.customdata?.[1] != null) {
      benchmark = { periodRet: benchPt.customdata[1], activeRet: b.periodRet - benchPt.customdata[1] };
    }
    const ribbon = (chosenSeries && idx != null) ? buildRibbon(chosenSeries.points, idx) : null;
    // position the card: 16px right + above the cursor, flipped left in the right 40%
    const wrap = chartWrapRef.current; const ev = e.event;
    let left = 16; let top = 16;
    if (wrap && ev) {
      const rect = wrap.getBoundingClientRect();
      const mx = ev.clientX - rect.left; const my = ev.clientY - rect.top;
      const W = 240;
      const H = 60 + sections.length * 70 + (benchmark ? 64 : 0) + (diff != null ? 26 : 0) + (divPct != null ? 22 : 0);
      left = Math.max(4, mx > rect.width * 0.6 ? mx - 16 - W : mx + 16);
      top = Math.max(4, my - 16 - H);
    }
    setHover({ date, fmtDate, bubblePrice, sections, diff, divPct, benchmark, ribbon, left, top });
  };
  const handleUnhover = () => { if (tooltipLockedRef.current) return; setHover(null); };

  // --- analyse: two-click point selection ----------------------------------
  // hovermode 'x' gives e.points = the closest point of every *visible* trace at the clicked x,
  // so we capture a { source -> price } map alongside the clicked date for each point.
  const analysePtFromEvent = (e) => {
    const pts = e?.points;
    if (!pts || !pts.length) return null;
    const first = pts.find((x) => x.data?.name === 'bloomberg') || pts[0];
    const prices = {};
    for (const p of pts) { if (p.data?.name != null && p.y != null) prices[p.data.name] = p.y; }
    return { date: first.x, fmtDate: first.customdata?.[5] ?? fmtDisplay(first.x), prices };
  };
  const handleAnalyseClick = (e) => {
    const cp = analysePtFromEvent(e);
    if (!cp) return;
    if (!pointA) { setPointA(cp); return; } // first click: point A
    // second click: point B -> compute one section per visible source, then deactivate
    setPointB(cp);
    const aFirst = Date.parse(pointA.date) <= Date.parse(cp.date);
    const startPt = aFirst ? pointA : cp;
    const endPt = aFirst ? cp : pointA;
    const days = Math.round(Math.abs(Date.parse(endPt.date) - Date.parse(startPt.date)) / 86400000);
    // one section per currently-visible source, in the order the traces appear
    const sections = series
      .filter((s) => !hidden.has(s.source))
      .map((s) => {
        const startPrice = startPt.prices[s.source];
        const endPrice = endPt.prices[s.source];
        if (startPrice == null || endPrice == null) return null;
        const change = endPrice - startPrice;
        const ret = startPrice ? ((endPrice - startPrice) / startPrice) * 100 : 0;
        const annualized = days > 0 ? (Math.pow(1 + ret / 100, 365 / days) - 1) * 100 : null;
        return { source: s.source, label: SOURCE_LABEL[s.source] || s.source, color: SOURCE_COLOR[s.source] || '#8892A4', startPrice, endPrice, change, ret, annualized };
      })
      .filter(Boolean);
    // pairwise source comparison (only when 2+ visible sources): first − second of each pair
    const comparison = [];
    for (let i = 0; i < sections.length; i++) {
      for (let j = i + 1; j < sections.length; j++) {
        comparison.push({ pair: `${sections[i].label} vs ${sections[j].label}`, retDiff: sections[i].ret - sections[j].ret, priceDiff: sections[i].endPrice - sections[j].endPrice });
      }
    }
    setAnalysis({ startDate: startPt.date, endDate: endPt.date, days, sections, comparison });
    setAnalysing(false); // auto-deactivate; markers stay until the panel is dismissed
  };

  // --- click: A/B selection while analysing, otherwise tooltip lock ---------
  const handleChartClick = (e) => {
    if (analysing) { handleAnalyseClick(e); return; } // Analyse consumes clicks -> no lock
    if (tooltipLockedRef.current) { tooltipLockedRef.current = false; setLocked(false); return; }
    if (!e?.points?.[0]) return;                 // only pin on an actual data point
    tooltipLockedRef.current = true; setLocked(true); // freeze current hover snapshot
  };

  // Legend interaction: visibility owned in state so it survives hover re-renders.
  const toggleSource = (src) => setHidden((prev) => {
    const next = new Set(prev);
    next.has(src) ? next.delete(src) : next.add(src);
    return next;
  });
  const isolateSource = (src) => setHidden((prev) => {
    const others = series.map((s) => s.source).filter((s) => s !== src);
    const alreadyIsolated = !prev.has(src) && others.every((s) => prev.has(s));
    return alreadyIsolated ? new Set() : new Set(others);
  });
  const handleLegendClick = (e) => { const src = series[e?.curveNumber]?.source; if (src) toggleSource(src); return false; };
  const handleLegendDoubleClick = (e) => { const src = series[e?.curveNumber]?.source; if (src) isolateSource(src); return false; };

  // Zoom buttons drive the controlled x-axis range (survives re-renders).
  const zoomPts = (series.find((s) => s.source === 'bloomberg') || series[0])?.points || [];
  const fullLo = zoomPts[0]?.date;
  const fullHi = zoomPts[zoomPts.length - 1]?.date;
  const zoom = (factor) => {
    if (!fullLo || !fullHi) return;
    const fLo = Date.parse(fullLo); const fHi = Date.parse(fullHi);
    const [lo, hi] = xRange || [fullLo, fullHi];
    const center = (Date.parse(lo) + Date.parse(hi)) / 2;
    const span = Math.min((Date.parse(hi) - Date.parse(lo)) * factor, fHi - fLo);
    let nLo = center - span / 2; let nHi = center + span / 2;
    if (nLo < fLo) { nHi += fLo - nLo; nLo = fLo; }
    if (nHi > fHi) { nLo -= nHi - fHi; nHi = fHi; }
    setXRange([isoDay(Math.max(nLo, fLo)), isoDay(Math.min(nHi, fHi))]);
  };
  // Feature 9 — Reset: clear the controlled range AND force both axes back to autorange
  // (a drag-zoom sets the range imperatively, which uirevision would otherwise keep pinned).
  const resetZoom = async () => {
    setXRange(null);
    const gd = gdRef.current;
    if (!gd) return;
    try { const Plotly = (await import('plotly.js-dist-min')).default; Plotly.relayout(gd, { 'xaxis.autorange': true, 'yaxis.autorange': true }); } catch { /* ignore */ }
  };

  // --- notes / annotations -------------------------------------------------
  // single source of truth = annotationsRef; mirror to state (re-renders the controlled chart
  // + the notes panel) and to localStorage (survives reloads).
  const writeAnnotations = (next) => {
    annotationsRef.current = next;
    setAnnotations(next);
    try { localStorage.setItem(ANNO_STORAGE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };
  // data coords -> absolute viewport pixel, via the chart's _fullLayout (inverse of the p2d below)
  const annoPixel = (a) => {
    const gd = gdRef.current; if (!gd) return null;
    try {
      const fl = gd._fullLayout; const bb = gd.getBoundingClientRect();
      return { px: bb.left + fl.xaxis._offset + fl.xaxis.d2p(a.date), py: bb.top + fl.yaxis._offset + fl.yaxis.d2p(a.price) };
    } catch { return null; }
  };
  // popover placement (fixed/viewport): flip left past the right edge, up past the bottom
  const placePopover = (clientX, clientY, w) => {
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1200;
    const vh = typeof window !== 'undefined' ? window.innerHeight : 800;
    const h = 150;
    let left = clientX; let top = clientY;
    if (left + w > vw - 8) left = clientX - w;
    if (top + h > vh - 8) top = clientY - h;
    return { left: Math.max(8, left), top: Math.max(8, top) };
  };
  const todayIso = () => new Date().toISOString().slice(0, 10);
  // resolve a price for a chosen date: nearest data point in the visible series (Bloomberg first,
  // else first visible). Outside the loaded range -> nearest boundary point, flagged outOfRange.
  const resolvePriceAtDate = (date) => {
    const s = (bbgSeries && !hidden.has('bloomberg')) ? bbgSeries : series.find((x) => !hidden.has(x.source));
    const pts = (s?.points || []).filter((p) => p.price != null);
    if (!pts.length) return { price: null, outOfRange: false };
    const t = Date.parse(date);
    const outOfRange = t < Date.parse(pts[0].date) || t > Date.parse(pts[pts.length - 1].date);
    let best = pts[0]; let bd = Infinity;
    for (const p of pts) { const d = Math.abs(Date.parse(p.date) - t); if (d < bd) { bd = d; best = p; } }
    return { price: best.price, outOfRange };
  };
  const openAddPopover = (clientX, clientY, date, price) => {
    const { left, top } = placePopover(clientX, clientY, 248);
    setPopover({ mode: 'add', date, price, left, top, width: 248 });
    setPopoverText(''); setPopoverDate(date || todayIso()); setPopoverErr({});
  };
  const openEditPopover = (clientX, clientY, anno) => {
    const { left, top } = placePopover(clientX, clientY, 248);
    setPopover({ mode: 'edit', id: anno.id, createdAt: anno.createdAt, left, top, width: 248 });
    setPopoverText(anno.text); setPopoverDate(anno.date); setPopoverErr({});
  };
  const closePopover = () => { setPopover(null); setPopoverText(''); setPopoverDate(''); setPopoverErr({}); };
  const savePopover = () => {
    const text = popoverText.trim();
    const errs = {};
    if (!popoverDate) errs.date = true;
    if (!text) errs.note = true;
    if (errs.date || errs.note) { setPopoverErr(errs); return; } // show "Required", keep open
    if (popover.mode === 'add') {
      // use the date from the date input (not the right-clicked x); resolve the price at that date
      const { price } = resolvePriceAtDate(popoverDate);
      const a = { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, date: popoverDate, price: price ?? 0, text, createdAt: new Date().toISOString() };
      writeAnnotations([...annotationsRef.current, a]);
    } else {
      writeAnnotations(annotationsRef.current.map((x) => {
        if (x.id !== popover.id) return x;
        const upd = { ...x, text };
        if (popoverDate && popoverDate !== x.date) { // date moved -> re-resolve the price
          upd.date = popoverDate;
          const { price } = resolvePriceAtDate(popoverDate);
          if (price != null) upd.price = price;
        }
        return upd;
      }));
    }
    closePopover();
  };
  const deleteAnnotation = (id) => { writeAnnotations(annotationsRef.current.filter((x) => x.id !== id)); };

  // give annotation text a pointer cursor (Plotly has no native cursor option); the observer
  // below re-applies it after every chart re-render that rebuilds annotations.
  const applyAnnoCursor = () => {
    const gd = gdRef.current; if (!gd) return;
    try { gd.querySelectorAll('.annotation, .annotation-text-g, .annotation-arrow-g, .annotation text, .annotation rect').forEach((el) => { el.style.cursor = 'pointer'; }); } catch { /* ignore */ }
  };
  // captureevents -> plotly_clickannotation fires; match by index (then date+text) to open the editor
  const handleClickAnnotation = (ev) => {
    const a = ev?.annotation;
    if (!a) return;
    const idx = ev.index;
    const found = (idx != null && idx < annotationsRef.current.length)
      ? annotationsRef.current[idx]
      : annotationsRef.current.find((x) => x.date === a.x && x.text === a.text);
    if (!found) return;
    const me = ev.event;
    let cx = me ? me.clientX : null; let cy = me ? me.clientY : null;
    if (cx == null) { const p = annoPixel(found); cx = p ? p.px : 200; cy = p ? p.py : 200; }
    openEditPopover(cx, cy, found);
  };

  // --- right-click menu ----------------------------------------------------
  // map a right-clicked annotation SVG element back to our stored note: Plotly doesn't write our
  // `id` into the DOM, so match by visible text, disambiguating duplicates by the nearest date.
  const matchAnnoId = (text, clientX) => {
    const t = (text || '').trim();
    const matches = annotationsRef.current.filter((a) => a.text === t);
    if (matches.length === 0) return null;
    if (matches.length === 1) return matches[0].id;
    let dataX = null;
    try { const fl = gdRef.current._fullLayout; const bb = gdRef.current.getBoundingClientRect(); dataX = fl.xaxis.p2d(clientX - bb.left - fl.xaxis._offset); } catch { /* ignore */ }
    if (dataX == null) return matches[0].id;
    const tx = (typeof dataX === 'number') ? dataX : Date.parse(dataX);
    let best = matches[0]; let bd = Infinity;
    for (const a of matches) { const d = Math.abs(Date.parse(a.date) - tx); if (d < bd) { bd = d; best = a; } }
    return best.id;
  };
  const handleContextMenu = (e) => {
    const gd = gdRef.current;
    // 1) right-click ON an annotation box? (SVG-element hit, then a 20px proximity fallback)
    let annoId = null;
    const onAnno = e.target?.closest?.('.annotation-text-g, .annotation, [class*="annotation"]');
    if (onAnno) annoId = matchAnnoId(onAnno.textContent, e.clientX);
    if (!annoId) {
      for (const a of annotationsRef.current) {
        const p = annoPixel(a);
        if (p && Math.hypot(e.clientX - p.px, e.clientY - p.py) <= 20) { annoId = a.id; break; }
      }
    }
    if (annoId) { // annotation menu only — suppress the browser + standard chart menus
      e.preventDefault();
      e.stopPropagation();
      setCtxMenu({ x: e.clientX, y: e.clientY, annoId });
      return;
    }
    // 2) standard chart context menu: data coords under the cursor for Add annotation / zoom items
    e.preventDefault();
    let dataX = null; let dataY = null;
    try {
      const fl = gd._fullLayout; const bb = gd.getBoundingClientRect();
      const dx = fl.xaxis.p2d(e.clientX - bb.left - fl.xaxis._offset);
      dataX = (typeof dx === 'number') ? isoDay(dx) : dx;
      dataY = fl.yaxis.p2d(e.clientY - bb.top - fl.yaxis._offset);
    } catch { /* ignore: menu still opens, coordinate-dependent items no-op */ }
    setCtxMenu({ x: e.clientX, y: e.clientY, dataX, dataY, annoId: null });
  };
  const zoomHere = () => { if (ctxMenu?.dataX) { const t = Date.parse(ctxMenu.dataX); setXRange([isoDay(t - 30 * 86400000), isoDay(t + 30 * 86400000)]); } };
  const setStartDate = () => { if (ctxMenu?.dataX) setXRange([ctxMenu.dataX, (xRange?.[1]) ?? fullHi]); };
  const setEndDate = () => { if (ctxMenu?.dataX) setXRange([(xRange?.[0]) ?? fullLo, ctxMenu.dataX]); };
  const exportImage = async () => {
    const gd = gdRef.current;
    if (!gd) return;
    const name = entity?.ticker || entity?.display_name || 'security';
    try {
      const Plotly = (await import('plotly.js-dist-min')).default;
      Plotly.downloadImage(gd, { format: 'png', filename: `prices_${name}_${period}`, width: 1400, height: 600 });
    } catch { /* ignore */ }
  };

  // --- graph div capture + Analyse-mode controls ---------------------------
  const handleInitialized = (_figure, gd) => {
    gdRef.current = gd;
    applyAnnoCursor();
    // watch the SVG for annotation elements (re)added on each Plotly.react and re-apply the cursor
    try {
      if (!annoObserverRef.current && typeof MutationObserver !== 'undefined') {
        const obs = new MutationObserver(() => applyAnnoCursor());
        obs.observe(gd, { childList: true, subtree: true });
        annoObserverRef.current = obs;
      }
    } catch { /* ignore */ }
  };
  const onAnalyseClick = () => {
    // clicking again while a panel/selection is up dismisses it and starts fresh
    setAnalysis(null); setPointA(null); setPointB(null);
    tooltipLockedRef.current = false; setLocked(false); // Analyse and the tooltip lock are mutually exclusive
    setAnalysing((a) => !a);
  };
  // dismiss the panel + clear the A/B markers/annotations (declarative shapes/annotations,
  // so clearing the points removes them on the next render — the controlled-layout equivalent
  // of a Plotly.relayout that drops them).
  const dismissAnalysis = () => { setAnalysis(null); setPointA(null); setPointB(null); setAnalysing(false); };

  // active theme (re-render forced by useThemeVersion on toggle)
  const isLight = (typeof document !== 'undefined') && document.documentElement.getAttribute('data-theme') === 'light';

  // --- declarative annotations + shapes (merged: persistent + compare + hover) ---
  const userAnnotations = annotations.map((a) => ({
    xref: 'x', yref: 'y', x: a.date, y: a.price, text: a.text,
    showarrow: true, arrowhead: 2, arrowsize: 1, arrowcolor: '#F5A623', ax: 0, ay: -40,
    font: { color: '#F5A623', family: PLEX, size: 10 },
    bgcolor: isLight ? '#FFFFFF' : '#1F1918', bordercolor: '#F5A623', borderpad: 5, borderwidth: 1,
    captureevents: true,
  }));
  const analyseAnnotations = [];
  if (pointA) analyseAnnotations.push({ x: pointA.date, xref: 'x', y: 1.02, yref: 'paper', text: 'A', showarrow: false, xanchor: 'center', yanchor: 'bottom', font: { color: '#5B8CFF', family: PLEX, size: 11 } });
  if (pointB) analyseAnnotations.push({ x: pointB.date, xref: 'x', y: 1.02, yref: 'paper', text: 'B', showarrow: false, xanchor: 'center', yanchor: 'bottom', font: { color: '#5B8CFF', family: PLEX, size: 11 } });
  const hoverAnnotations = hover ? [
    { x: hover.date, xref: 'x', y: -0.08, yref: 'paper', text: hover.fmtDate, showarrow: false, bgcolor: '#5B8CFF', font: { color: '#FFFFFF', family: PLEX, size: 10 }, borderpad: 4, xanchor: 'center', yanchor: 'top' },
    ...(hover.bubblePrice != null ? [{ x: -0.01, xref: 'paper', y: hover.bubblePrice, yref: 'y', text: hover.bubblePrice.toFixed(2), showarrow: false, bgcolor: '#5B8CFF', font: { color: '#FFFFFF', family: PLEX, size: 10 }, borderpad: 4, xanchor: 'right', yanchor: 'middle' }] : []),
  ] : [];
  const chartAnnotations = [...userAnnotations, ...analyseAnnotations, ...hoverAnnotations];

  const analyseShapes = [];
  if (pointA) analyseShapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: pointA.date, x1: pointA.date, y0: 0, y1: 1, line: { color: '#5B8CFF', width: 1, dash: 'dot' } });
  if (pointB) analyseShapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: pointB.date, x1: pointB.date, y0: 0, y1: 1, line: { color: '#5B8CFF', width: 1, dash: 'dot' } });
  // divergence bands removed from the chart; only the Analyse A/B markers remain as shapes
  const shapes = [...analyseShapes];

  // Mode priority: Analyse active -> dragmode false (click-only point selection);
  // otherwise drag-to-zoom is the default. Driven declaratively through the controlled
  // layout so it survives hover re-renders (the relayout equivalent, without clobbering).
  const dragmode = analysing ? false : 'zoom';

  // Returns table — single-period (daily) returns vs the previous date, in chronological
  // (oldest -> newest) order; this is the "unsorted" order the Date sort can restore. Works
  // with one source or both: the date spine comes from Bloomberg when present, else SBS.
  const cmpRows = useMemo(() => {
    if (availableSources.length === 0) return [];
    const baseSeries = availableSources.includes('bloomberg') ? bbgSeries : sbsSeries;
    const bMap = bbgSeries ? new Map(bbgSeries.points.map((p) => [p.date, p.price])) : null;
    const sMap = sbsSeries ? new Map(sbsSeries.points.map((p) => [p.date, p.price])) : null;
    const pts = baseSeries.points;
    return pts.map((p, i) => {
      const prev = i > 0 ? pts[i - 1] : null;
      const date = p.date;
      const bPrice = bMap ? (bMap.get(date) ?? null) : null;
      const prevB = (bMap && prev) ? (bMap.get(prev.date) ?? null) : null;
      const bRet = (bPrice != null && prevB != null && prevB) ? (bPrice - prevB) / prevB : null;
      const sPrice = sMap ? (sMap.get(date) ?? null) : null;
      const prevS = (sMap && prev) ? (sMap.get(prev.date) ?? null) : null;
      const sRet = (sPrice != null && prevS != null && prevS) ? (sPrice - prevS) / prevS : null;
      const diff = (bRet != null && sRet != null) ? bRet - sRet : null;
      return { date, bPrice, bRet, sPrice, sRet, diff };
    });
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  // comparison-table column visibility (persisted) + the chooser dropdown
  const [cmpVisible, setCmpVisible] = useState(() => new Set(CMP_COLUMNS.map((c) => c.key)));
  const [cmpChooser, setCmpChooser] = useState(false);
  const [cmpSort, setCmpSort] = useState('desc'); // Date sort: 'desc' | 'asc' | null (original order)
  const cmpToolsRef = useRef(null);
  const cycleSort = () => setCmpSort((s) => (s === 'desc' ? 'asc' : s === 'asc' ? null : 'desc'));

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(CMP_STORAGE_KEY) || 'null');
      if (Array.isArray(saved)) setCmpVisible(new Set(saved));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!cmpChooser) return undefined;
    const onDoc = (e) => { if (cmpToolsRef.current && !cmpToolsRef.current.contains(e.target)) setCmpChooser(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [cmpChooser]);

  const toggleCmpCol = (key) => setCmpVisible((prev) => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    try { localStorage.setItem(CMP_STORAGE_KEY, JSON.stringify([...next])); } catch { /* ignore */ }
    return next;
  });

  // only groups/columns whose source is available, then apply the visibility filter
  const cmpGroups = CMP_GROUPS
    .filter((g) => colAvail(g.src))
    .map((g) => ({ label: g.label, cols: g.cols.filter((c) => cmpVisible.has(c.key)) }))
    .filter((g) => g.cols.length > 0);
  const activeColumns = CMP_COLUMNS.filter((c) => colAvail(c.src)); // chooser options for this layout

  // client-side Date sort over the already-fetched rows (no API call on sort change)
  const cmpSorted = useMemo(() => {
    if (cmpSort === 'desc') return [...cmpRows].sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
    if (cmpSort === 'asc') return [...cmpRows].sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
    return cmpRows; // unsorted -> original (chronological) order
  }, [cmpRows, cmpSort]);

  const exportCmpCsv = () => {
    const cols = cmpGroups.flatMap((g) => g.cols);
    const headers = ['Date', ...cols.map((c) => CMP_COLUMNS.find((x) => x.key === c.key)?.label || c.key)];
    const rows = cmpSorted.map((r) => [r.date, ...cols.map((c) => {
      const v = CMP_VAL[c.key](r);
      if (v == null) return '';
      return c.type === 'price' ? v.toFixed(2) : (v * 100).toFixed(2);
    })]);
    downloadCsv(`${entity?.ticker || 'security'}_prices_${range.from}_${range.to}`, headers, rows);
  };

  return (
    <div>
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">Price Viewer</div>
      </div>
      <p className="page-sub">Daily prices for one security, one line per source.</p>

      <KpiBar tiles={kpis} />

      <div className="panel">
        <div className="controls">
          <SecuritySearch
            value={selected}
            onSelect={(s) => { setSelected(s); setEntityId(s ? String(s.entity_id) : ''); }}
          />
        </div>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      <div className="panel">
        {loading ? (
          <div className="loading">Loading…</div>
        ) : traces.length ? (
          <>
            <div className="px-chart-wrap" ref={chartWrapRef} onContextMenu={handleContextMenu}>
              <PlotlyChart
                data={traces}
                onHover={handleHover}
                onUnhover={handleUnhover}
                onClick={handleChartClick}
                onLegendClick={handleLegendClick}
                onLegendDoubleClick={handleLegendDoubleClick}
                onInitialized={handleInitialized}
                onClickAnnotation={handleClickAnnotation}
                config={{ doubleClick: 'reset+autosize' }}
                layout={{
                  hovermode: 'x', hoverdistance: -1,
                  uirevision: 'price-chart-stable',
                  dragmode,
                  margin: { l: 60, r: 20, t: 30, b: 64 },
                  annotations: chartAnnotations,
                  shapes,
                  showlegend: false,
                  xaxis: { title: '', hoverformat: '%Y-%m-%d', ...X_SPIKE, ...(xRange ? { range: xRange, autorange: false } : { autorange: true }) },
                  yaxis: { title: entity?.base_currency || 'Price', zeroline: false, ...Y_SPIKE },
                }}
              />

              {hover && (
                <div className="px-hover" style={{ left: hover.left, top: hover.top }}>
                  <div className="px-tip">
                    {hover.divPct != null && (
                      <div className="px-tip-warn">⚠ Sources diverge · {sgnPct(hover.divPct)}</div>
                    )}
                    <div className="px-tip-date">{hover.fmtDate}</div>
                    {hover.sections.map((s, i) => (
                      <div key={s.source ?? i}>
                        <div className="px-tip-div" />
                        <div className="px-tip-head" style={{ color: s.color }}>{(s.label || s.source || '').toUpperCase()}</div>
                        <div className="px-tip-row"><span className="px-tip-label">Price</span><span className="px-tip-val">{s.price != null ? s.price.toFixed(2) : '—'}</span></div>
                        <div className="px-tip-row"><span className="px-tip-label">Daily Return</span><span className={`px-tip-val ${s.dayRet == null ? '' : s.dayRet >= 0 ? 'pos' : 'neg'}`}>{s.dayRet == null ? '—' : sgnPct(s.dayRet * 100)}</span></div>
                        <div className="px-tip-row"><span className="px-tip-label">Period Return</span><span className="px-tip-val">{s.periodRet == null ? '—' : sgnPct(s.periodRet)}</span></div>
                      </div>
                    ))}
                    {hover.benchmark && (
                      <>
                        <div className="px-tip-div" />
                        <div className="px-tip-head" style={{ color: SOURCE_COLOR.benchmark }}>BENCHMARK</div>
                        <div className="px-tip-row"><span className="px-tip-label">Period Return</span><span className="px-tip-val">{sgnPct(hover.benchmark.periodRet)}</span></div>
                        <div className="px-tip-row"><span className="px-tip-label">Active Return</span><span className="px-tip-val" style={{ color: hover.benchmark.activeRet >= 0 ? 'var(--teal)' : 'var(--rose)' }}>{sgnPct(hover.benchmark.activeRet)}</span></div>
                      </>
                    )}
                    {hover.diff != null && (
                      <>
                        <div className="px-tip-div" />
                        <div className="px-tip-row"><span className="px-tip-label">Return Diff</span><span className="px-tip-val" style={{ color: Math.abs(hover.diff) >= RETURN_DIFF_THRESHOLD * 100 ? 'var(--rose)' : 'var(--teal)' }}>{sgnPct(hover.diff)}</span></div>
                      </>
                    )}
                  </div>
                  {hover.ribbon && (
                    <div className="px-ribbon">
                      {hover.ribbon.items.map((it, i) => (
                        <div className="px-ribbon-item" key={i}>
                          <span className="px-ribbon-label">{it.label}</span>
                          <span className={`px-ribbon-val ${it.value == null ? '' : it.value >= 0 ? 'pos' : 'neg'}`}>{it.value == null ? '—' : sgnPct(it.value)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {locked && <div className="px-lock">LOCKED</div>}
            </div>

            <div className="chart-controls">
              <div className="chart-legend">
                {series.map((s) => {
                  const off = hidden.has(s.source);
                  return (
                    <button
                      key={s.source}
                      type="button"
                      className={`legend-item ${off ? 'off' : ''}`}
                      onClick={() => toggleSource(s.source)}
                      title={off ? 'Show series' : 'Hide series'}
                    >
                      <span className="legend-dot" style={{ background: SOURCE_COLOR[s.source] || '#8892A4' }} />
                      {SOURCE_LABEL[s.source] || s.source}
                    </button>
                  );
                })}
              </div>
              <div className="chart-zoom">
                <button type="button" className={`btn ${analysing ? 'active' : ''}`} onClick={onAnalyseClick} title="Analyse the change between two points">
                  {analysing ? 'Analysing — click two points' : 'Analyse'}
                </button>
                <button type="button" className="btn" onClick={() => zoom(1 / 0.6)} title="Zoom out">−</button>
                <button type="button" className="btn" onClick={resetZoom} title="Reset zoom">Reset</button>
                <button type="button" className="btn" onClick={() => zoom(0.6)} title="Zoom in">+</button>
              </div>
            </div>
          </>
        ) : (
          <div className="muted">No price data for this selection.</div>
        )}
      </div>

      {analysis && (
        <div className="measure-panel">
          <div className="measure-head">
            <div className="measure-head-text">
              <span className="measure-title">ANALYSIS</span>
              <span className="measure-range">{fmtDisplay(analysis.startDate)} → {fmtDisplay(analysis.endDate)}</span>
            </div>
            <button type="button" className="measure-close" onClick={dismissAnalysis} title="Dismiss" aria-label="Dismiss analysis">×</button>
          </div>
          <div className="measure-days">{analysis.days} days</div>
          {analysis.sections.map((sec) => (
            <div key={sec.source}>
              <div className="measure-div" />
              <div className="measure-head-text"><span className="measure-title" style={{ color: sec.color }}>{sec.label.toUpperCase()}</span></div>
              <div className="measure-rows">
                <div className="measure-row"><span className="measure-label">Start price</span><span className="measure-val">{sec.startPrice.toFixed(2)}</span></div>
                <div className="measure-row"><span className="measure-label">End price</span><span className="measure-val">{sec.endPrice.toFixed(2)}</span></div>
                <div className="measure-row"><span className="measure-label">Change</span><span className={`measure-val ${sec.change >= 0 ? 'pos' : 'neg'}`}>{sgnNum(sec.change)}</span></div>
                <div className="measure-row"><span className="measure-label">Return</span><span className={`measure-val ${sec.ret >= 0 ? 'pos' : 'neg'}`}>{sgnPct(sec.ret)}</span></div>
                <div className="measure-row"><span className="measure-label">Annualized</span><span className={`measure-val ${(sec.annualized ?? 0) >= 0 ? 'pos' : 'neg'}`}>{sec.annualized == null ? '—' : sgnPct(sec.annualized)}</span></div>
              </div>
            </div>
          ))}
          {analysis.comparison.length > 0 && (
            <>
              <div className="measure-div" />
              <div className="measure-head-text"><span className="measure-title">SOURCE COMPARISON</span></div>
              <div className="measure-rows">
                {analysis.comparison.map((c, i) => (
                  <div key={i}>
                    <div className="measure-row"><span className="measure-label">{analysis.comparison.length > 1 ? `Return diff · ${c.pair}` : 'Return diff'}</span><span className={`measure-val ${c.retDiff >= 0 ? 'pos' : 'neg'}`}>{sgnPct(c.retDiff)}</span></div>
                    <div className="measure-row"><span className="measure-label">{analysis.comparison.length > 1 ? `Price diff (end) · ${c.pair}` : 'Price diff (end)'}</span><span className="measure-val">{sgnNum(c.priceDiff)}</span></div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      <div className="panel">
        <div className="panel-title">Returns</div>
        {cmpRows.length ? (
          <>
            <div className="table-tools">
              <div />
              <div className="right" ref={cmpToolsRef}>
                <button className="btn" onClick={exportCmpCsv} title="Export visible columns as CSV">↓ CSV</button>
                <button className="btn" onClick={() => setCmpChooser((v) => !v)} title="Show / hide columns">⊞ Columns</button>
                {cmpChooser && (
                  <div className="col-chooser">
                    {activeColumns.map((c) => (
                      <label className="row" key={c.key}>
                        <input type="checkbox" checked={cmpVisible.has(c.key)} onChange={() => toggleCmpCol(c.key)} />
                        {c.label}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="cmp-wrap">
              <table className="cmp-table">
                <colgroup>
                  <col style={{ width: 110 }} />
                  {cmpGroups.flatMap((g) => g.cols.map((c) => <col key={c.key} style={{ width: c.width }} />))}
                </colgroup>
                <thead>
                  <tr className="cmp-grp">
                    <th rowSpan={2} className="cmp-date cmp-sortable" onClick={cycleSort} title="Sort by date">
                      Date <span className={`cmp-sort-ind ${cmpSort ? 'on' : ''}`}>{cmpSort === 'desc' ? '↓' : cmpSort === 'asc' ? '↑' : '↕'}</span>
                    </th>
                    {cmpGroups.map((g, gi) => (
                      <th key={g.label} colSpan={g.cols.length} className={gi > 0 ? 'cmp-div' : ''}>{g.label}</th>
                    ))}
                  </tr>
                  <tr className="cmp-col">
                    {cmpGroups.flatMap((g, gi) => g.cols.map((c, ci) => (
                      <th key={c.key} className={gi > 0 && ci === 0 ? 'cmp-div' : ''}>{c.label}</th>
                    )))}
                  </tr>
                </thead>
                <tbody>
                  {cmpSorted.map((r) => (
                    <tr key={r.date}>
                      <td className="cmp-date num">{r.date}</td>
                      {cmpGroups.flatMap((g, gi) => g.cols.map((c, ci) => {
                        const divider = gi > 0 && ci === 0 ? 'cmp-div' : '';
                        const v = CMP_VAL[c.key](r);
                        if (c.type === 'price') {
                          return <td key={c.key} className={`num ${divider}`}>{fmtPrice(v)}</td>;
                        }
                        if (c.type === 'ret') {
                          return <td key={c.key} className={`num ${retClass(v)} ${divider} ${v == null ? 'dim' : ''}`}>{fmtReturn(v)}</td>;
                        }
                        const hot = v != null && Math.abs(v) > RETURN_DIFF_THRESHOLD;
                        return <td key={c.key} className={`num ${retClass(v)} ${divider} ${hot ? 'cmp-hot' : ''} ${v == null ? 'dim' : ''}`}>{fmtReturn(v)}</td>;
                      }))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="notes-empty">No return data available for the selected security and period.</div>
        )}
      </div>

      {ctxMenu && typeof document !== 'undefined' && createPortal(
        <div ref={ctxMenuRef} className="px-ctx" style={{ left: ctxMenu.x, top: ctxMenu.y }}>
          {ctxMenu.annoId ? (
            <>
              <button type="button" className="px-ctx-item" onClick={() => { const m = ctxMenu; setCtxMenu(null); const a = annotationsRef.current.find((x) => x.id === m.annoId); if (a) openEditPopover(m.x, m.y, a); }}>Edit note</button>
              <button type="button" className="px-ctx-item" style={{ color: 'var(--rose)' }} onClick={() => { deleteAnnotation(ctxMenu.annoId); setCtxMenu(null); }}>Delete note</button>
            </>
          ) : (
            <>
              <button type="button" className="px-ctx-item" onClick={() => { onAnalyseClick(); setCtxMenu(null); }}>Measure return</button>
              <button type="button" className="px-ctx-item" onClick={() => { zoomHere(); setCtxMenu(null); }}>Zoom here</button>
              <button type="button" className="px-ctx-item" onClick={() => { setStartDate(); setCtxMenu(null); }}>Set start date</button>
              <button type="button" className="px-ctx-item" onClick={() => { setEndDate(); setCtxMenu(null); }}>Set end date</button>
              <button type="button" className="px-ctx-item" onClick={() => { const m = ctxMenu; setCtxMenu(null); if (m.dataX != null && m.dataY != null) openAddPopover(m.x, m.y, m.dataX, m.dataY); }}>Add annotation</button>
              <div className="px-ctx-div" />
              <button type="button" className="px-ctx-item" onClick={() => { exportImage(); setCtxMenu(null); }}>Export image</button>
              <button type="button" className="px-ctx-item" onClick={() => { exportCmpCsv(); setCtxMenu(null); }}>Export data (CSV)</button>
            </>
          )}
        </div>,
        document.body,
      )}

      {popover && typeof document !== 'undefined' && createPortal(
        <div ref={popRef} className="px-pop" style={{ left: popover.left, top: popover.top, width: popover.width }}>
          <div className="px-pop-title">{popover.mode === 'add' ? 'Add note' : 'Edit note'}</div>
          <div className="px-pop-div" />
          <div className="px-pop-label">Date</div>
          <input
            type="date"
            className="px-pop-input px-date"
            value={popoverDate}
            onChange={(e) => setPopoverDate(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') savePopover(); else if (e.key === 'Escape') closePopover(); }}
          />
          {popoverErr.date && <div className="notes-err">Required</div>}
          {popoverDate && resolvePriceAtDate(popoverDate).outOfRange && (
            <div className="notes-warn">Outside loaded range — using nearest available price</div>
          )}
          <div className="px-pop-label" style={{ marginTop: 8 }}>Note</div>
          <input
            className="px-pop-input"
            autoFocus
            value={popoverText}
            placeholder="e.g. Fed meeting, rebalance, dividend..."
            onChange={(e) => setPopoverText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') savePopover(); else if (e.key === 'Escape') closePopover(); }}
          />
          {popoverErr.note && <div className="notes-err">Required</div>}
          {popover.mode === 'edit' && popover.createdAt && (
            <div className="px-pop-meta">Added: {fmtStamp(popover.createdAt)}</div>
          )}
          <div className="px-pop-actions">
            {popover.mode === 'edit' && (
              <button type="button" className="px-pop-del" onClick={() => { deleteAnnotation(popover.id); closePopover(); }}>Delete</button>
            )}
            <span className="px-pop-spacer" />
            <button type="button" className="btn" onClick={closePopover}>Cancel</button>
            <button type="button" className="btn active" onClick={savePopover}>Save</button>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
