// web/apps/dashboards/app/comparacion/page.js
// ---------------------------------------------------------------------------
// Comparación (Price Comparison): cumulative return of several securities on one
// chart, indexed to 0% at the start of the period, so they're visually
// comparable regardless of price level. Summary cards + multi-security selector
// + Bloomberg-style chart (crosshair, axis bubbles, floating multi-series card,
// zoom, drag-zoom, Analyse, annotations, context menu, legend) + a Retornos table.
//
// TODO: extract shared chart interaction logic into a hook,
// currently duplicated from app/prices/page.js (crosshair, axis bubbles, floating
// card, Analyse, annotations, context menu). Refactor as a separate, lower-risk task.
//
// DATA: /api/prices is single-security, so each security is fetched in parallel;
// the primary (Bloomberg, else first) source series is used as the price line.
// ---------------------------------------------------------------------------
'use client';

import { Fragment, useEffect, useMemo, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import dynamic from 'next/dynamic';
import { apiGet } from '../../lib/api';
import { downloadCsv } from '../../lib/csv';
import { useDashboard } from '../../components/DashboardProvider';
import SecuritySearch from '../../components/SecuritySearch';
import { fmtDisplay } from '../../lib/period';
import { useThemeVersion } from '../../lib/theme';

const PlotlyChart = dynamic(() => import('../../components/PlotlyChart'), { ssr: false });

const PLEX = "var(--font-plex), 'IBM Plex Mono', monospace";
const PALETTE = ['#5B8CFF', '#2DD4A0', '#F5A623', '#F06580', '#C9A84C', '#8892A4'];
const MAX_SECURITIES = 6;

const STAMP_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad2 = (n) => String(n).padStart(2, '0');
const fmtStamp = (iso) => { const d = new Date(iso); if (Number.isNaN(d.getTime())) return iso; return `${pad2(d.getDate())} ${STAMP_MONTHS[d.getMonth()]} ${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
const sgn = (v) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`);
const sgn1 = (v) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`);

// Always format a hovered x value as a readable date (the chart x values are ISO
// date strings, but never render a raw x — a Date/ms/hex could leak through).
function formatDateLabel(rawX) {
  const d = new Date(rawX);
  if (Number.isNaN(d.getTime())) return String(rawX);
  return d.toLocaleDateString('es-PE', { day: '2-digit', month: 'short', year: 'numeric' });
}

const X_SPIKE = { showspikes: true, spikemode: 'across', spikesnap: 'cursor', spikedash: 'dot', spikecolor: '#5B8CFF', spikethickness: 1 };
const Y_SPIKE = { showspikes: true, spikemode: 'across', spikesnap: 'data', spikedash: 'dot', spikecolor: '#5B8CFF', spikethickness: 1 };

export default function ComparacionPage() {
  const { range } = useDashboard();
  const [securities, setSecurities] = useState([]); // [{ entity_id, ticker, display_name, isin, color }]
  const [seriesData, setSeriesData] = useState({}); // entity_id -> { entity, points:[{date,price}] }
  const [adding, setAdding] = useState(false);
  const [maxMsg, setMaxMsg] = useState(false);
  const [hidden, setHidden] = useState(() => new Set()); // entity_ids toggled off via legend
  const [xRange, setXRange] = useState(null);
  const [hover, setHover] = useState(null);
  const [analysing, setAnalysing] = useState(false);
  const [pointA, setPointA] = useState(null);
  const [pointB, setPointB] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [ctxMenu, setCtxMenu] = useState(null);
  const [annotations, setAnnotations] = useState([]);
  const [popover, setPopover] = useState(null);
  const [popoverText, setPopoverText] = useState('');
  const [popoverDate, setPopoverDate] = useState('');
  const [popoverErr, setPopoverErr] = useState({});
  const [sort, setSort] = useState('desc'); // table Date sort: 'desc' | 'asc' | null
  const chartWrapRef = useRef(null);
  const gdRef = useRef(null);
  const ctxMenuRef = useRef(null);
  const popRef = useRef(null);
  const annotationsRef = useRef([]);
  const annoObserverRef = useRef(null);
  useThemeVersion();

  // initial securities: AAPL/MSFT/NVDA if present, else the first three
  useEffect(() => {
    apiGet('/api/securities?limit=50').then((rows) => {
      const want = ['AAPL', 'MSFT', 'NVDA'];
      const pick = want.map((w) => rows.find((r) => r.ticker === w)).filter(Boolean);
      const chosen = (pick.length ? pick : rows.slice(0, 3)).slice(0, MAX_SECURITIES);
      setSecurities(chosen.map((r, i) => ({ entity_id: r.entity_id, ticker: r.ticker, display_name: r.display_name, isin: r.isin, color: PALETTE[i] })));
    }).catch(() => {});
  }, []);

  // fetch each security's price series in parallel whenever the set or window changes
  const secKey = securities.map((s) => s.entity_id).join(',');
  useEffect(() => {
    if (!securities.length) { setSeriesData({}); return undefined; }
    let cancelled = false;
    Promise.all(securities.map((s) => apiGet(`/api/prices?entity_id=${s.entity_id}&from=${range.from}&to=${range.to}`).then((d) => ({ s, d })).catch(() => ({ s, d: null }))))
      .then((results) => {
        if (cancelled) return;
        const map = {};
        results.forEach(({ s, d }) => {
          const series = d?.series || [];
          const primary = series.find((x) => x.source === 'bloomberg') || series[0];
          map[s.entity_id] = { entity: d?.entity, points: (primary?.points || []).filter((p) => p.price != null) };
        });
        setSeriesData(map);
      });
    return () => { cancelled = true; };
  }, [secKey, range.from, range.to]);

  // per-comparison-set annotation store (keyed by the sorted tickers)
  const annoKey = `cmpAnno:${securities.map((s) => s.ticker).slice().sort().join('|')}`;
  useEffect(() => {
    try { const saved = JSON.parse(localStorage.getItem(annoKey) || 'null'); const arr = Array.isArray(saved) ? saved : []; annotationsRef.current = arr; setAnnotations(arr); }
    catch { annotationsRef.current = []; setAnnotations([]); }
  }, [annoKey]);
  useEffect(() => () => { try { annoObserverRef.current?.disconnect(); } catch { /* ignore */ } }, []);

  // dismiss context menu / popover
  useEffect(() => {
    if (!ctxMenu) return undefined;
    const onDown = (e) => { if (ctxMenuRef.current && !ctxMenuRef.current.contains(e.target)) setCtxMenu(null); };
    const onKey = (e) => { if (e.key === 'Escape') setCtxMenu(null); };
    document.addEventListener('mousedown', onDown); document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [ctxMenu]);
  useEffect(() => {
    if (!popover) return undefined;
    const onDown = (e) => { if (popRef.current && !popRef.current.contains(e.target)) { setPopover(null); setPopoverText(''); setPopoverDate(''); setPopoverErr({}); } };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [popover]);

  // a new comparison window resets transient chart state
  useEffect(() => { setXRange(null); setHover(null); setAnalysing(false); setPointA(null); setPointB(null); setAnalysis(null); }, [secKey, range.from, range.to]);

  const isoDay = (ms) => new Date(ms).toISOString().slice(0, 10);
  const cumOf = (base, price) => ((base && price != null) ? (price / base - 1) * 100 : null);

  // --- per-security prepared data ------------------------------------------
  const prep = useMemo(() => securities.map((s) => {
    const pts = seriesData[s.entity_id]?.points || [];
    const base = pts.length ? pts[0].price : null;
    return { s, pts, base, priceMap: new Map(pts.map((p) => [p.date, p.price])), entity: seriesData[s.entity_id]?.entity };
  }), [securities, seriesData]);
  const firstVisible = prep.find((p) => !hidden.has(p.s.entity_id) && p.pts.length);

  // --- summary cards --------------------------------------------------------
  const cards = prep.map((p) => {
    const name = p.entity?.display_name || p.s.display_name || '';
    if (p.pts.length < 2) return { s: p.s, name, insufficient: true };
    const start = p.pts[0]; const end = p.pts[p.pts.length - 1];
    const totalRet = (end.price - start.price) / start.price * 100;
    const days = Math.max(1, Math.round((Date.parse(end.date) - Date.parse(start.date)) / 86400000));
    const annual = (Math.pow(1 + totalRet / 100, 365 / days) - 1) * 100;
    return { s: p.s, name, totalRet, annual, start, end };
  });
  // best performer (highest total return) is the accent card
  const bestId = (() => {
    const valid = cards.filter((c) => !c.insufficient);
    if (!valid.length) return null;
    return valid.reduce((mx, c) => (c.totalRet > mx.totalRet ? c : mx), valid[0]).s.entity_id;
  })();

  // --- chart traces (cumulative return) ------------------------------------
  const traces = prep.map((p) => {
    const isHidden = hidden.has(p.s.entity_id);
    return {
      x: p.pts.map((q) => q.date),
      y: p.pts.map((q) => cumOf(p.base, q.price) ?? 0),
      customdata: p.pts.map((q, i) => {
        const prev = i > 0 ? p.pts[i - 1] : null;
        const dayRet = (prev && prev.price) ? (q.price - prev.price) / prev.price : null;
        return [q.date, cumOf(p.base, q.price) ?? 0, p.s.ticker, dayRet, fmtDisplay(q.date), p.s.color, q.price];
      }),
      type: 'scatter', mode: 'lines', name: p.s.ticker,
      line: { color: p.s.color, width: 2 },
      hoverinfo: isHidden ? 'skip' : 'none', hoverlabel: { opacity: 0 },
      visible: isHidden ? 'legendonly' : true,
    };
  });

  // --- hover: floating multi-security card + axis bubbles ------------------
  const handleHover = (e) => {
    const pts = e?.points; if (!pts || !pts.length) return;
    const first = pts[0];
    const date = first.x;
    const fmtDate = formatDateLabel(date); // x-axis bubble + card header (was wrongly reading the color)
    const bubbleVal = first.customdata?.[1] ?? first.y ?? null;
    const sections = pts.map((p) => { const cd = p.customdata || []; return { ticker: cd[2], color: cd[5], cum: cd[1], dayRet: cd[3] }; });
    const wrap = chartWrapRef.current; const ev = e.event;
    let left = 16; let top = 16;
    if (wrap && ev) {
      const rect = wrap.getBoundingClientRect();
      const mx = ev.clientX - rect.left; const my = ev.clientY - rect.top;
      const W = 240; const H = 50 + sections.length * 56;
      left = Math.max(4, mx > rect.width * 0.6 ? mx - 16 - W : mx + 16);
      top = Math.max(4, my - 16 - H);
    }
    setHover({ date, fmtDate, bubbleVal, sections, left, top });
  };
  const handleUnhover = () => setHover(null);

  // --- analyse (two-click), multi-security ---------------------------------
  const analysePt = (e) => {
    const pts = e?.points; if (!pts || !pts.length) return null;
    const prices = {};
    for (const p of pts) { if (p.data?.name != null) prices[p.data.name] = p.customdata?.[6] ?? null; }
    return { date: pts[0].x, fmtDate: formatDateLabel(pts[0].x), prices };
  };
  const handleAnalyseClick = (e) => {
    const cp = analysePt(e); if (!cp) return;
    if (!pointA) { setPointA(cp); return; }
    setPointB(cp);
    const aFirst = Date.parse(pointA.date) <= Date.parse(cp.date);
    const startPt = aFirst ? pointA : cp; const endPt = aFirst ? cp : pointA;
    const days = Math.max(1, Math.round(Math.abs(Date.parse(endPt.date) - Date.parse(startPt.date)) / 86400000));
    const sections = prep.filter((p) => !hidden.has(p.s.entity_id)).map((p) => {
      const pa = startPt.prices[p.s.ticker]; const pb = endPt.prices[p.s.ticker];
      if (pa == null || pb == null || !pa) return null;
      const ret = (pb - pa) / pa * 100;
      const annual = (Math.pow(1 + ret / 100, 365 / days) - 1) * 100;
      return { ticker: p.s.ticker, color: p.s.color, ret, annual };
    }).filter(Boolean);
    setAnalysis({ startDate: startPt.date, endDate: endPt.date, days, sections });
    setAnalysing(false);
  };
  const handleChartClick = (e) => { if (analysing) handleAnalyseClick(e); };
  const onAnalyseClick = () => {
    setAnalysis(null); setPointA(null); setPointB(null);
    setAnalysing((a) => !a);
  };
  const dismissAnalysis = () => { setAnalysis(null); setPointA(null); setPointB(null); setAnalysing(false); };

  // --- legend ---------------------------------------------------------------
  const toggleSec = (eid) => setHidden((prev) => { const next = new Set(prev); next.has(eid) ? next.delete(eid) : next.add(eid); return next; });
  const isolateSec = (eid) => setHidden((prev) => {
    const others = securities.map((s) => s.entity_id).filter((x) => x !== eid);
    const alone = !prev.has(eid) && others.every((x) => prev.has(x));
    return alone ? new Set() : new Set(others);
  });
  const handleLegendClick = (e) => { const s = securities[e?.curveNumber]; if (s) toggleSec(s.entity_id); return false; };
  const handleLegendDoubleClick = (e) => { const s = securities[e?.curveNumber]; if (s) isolateSec(s.entity_id); return false; };

  // --- zoom -----------------------------------------------------------------
  const zoomPts = firstVisible?.pts || prep[0]?.pts || [];
  const fullLo = zoomPts[0]?.date; const fullHi = zoomPts[zoomPts.length - 1]?.date;
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
  const resetZoom = async () => {
    setXRange(null);
    const gd = gdRef.current; if (!gd) return;
    try { const Plotly = (await import('plotly.js-dist-min')).default; Plotly.relayout(gd, { 'xaxis.autorange': true, 'yaxis.autorange': true }); } catch { /* ignore */ }
  };

  // --- annotations + context menu (ported from Price Viewer) ---------------
  const writeAnnotations = (next) => { annotationsRef.current = next; setAnnotations(next); try { localStorage.setItem(annoKey, JSON.stringify(next)); } catch { /* ignore */ } };
  const annoPixel = (a) => {
    const gd = gdRef.current; if (!gd) return null;
    try { const fl = gd._fullLayout; const bb = gd.getBoundingClientRect(); return { px: bb.left + fl.xaxis._offset + fl.xaxis.d2p(a.date), py: bb.top + fl.yaxis._offset + fl.yaxis.d2p(a.value) }; } catch { return null; }
  };
  const placePopover = (cx, cy, w) => {
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1200; const vh = typeof window !== 'undefined' ? window.innerHeight : 800;
    let left = cx; let top = cy; if (left + w > vw - 8) left = cx - w; if (top + 150 > vh - 8) top = cy - 150;
    return { left: Math.max(8, left), top: Math.max(8, top) };
  };
  const todayIso = () => new Date().toISOString().slice(0, 10);
  const resolveValAtDate = (date) => {
    const p = firstVisible; if (!p) return { value: 0, outOfRange: false };
    const t = Date.parse(date); const pts = p.pts;
    const outOfRange = t < Date.parse(pts[0].date) || t > Date.parse(pts[pts.length - 1].date);
    let best = pts[0]; let bd = Infinity; for (const q of pts) { const d = Math.abs(Date.parse(q.date) - t); if (d < bd) { bd = d; best = q; } }
    return { value: cumOf(p.base, best.price) ?? 0, outOfRange };
  };
  const openAddPopover = (cx, cy, date, value) => { const { left, top } = placePopover(cx, cy, 248); setPopover({ mode: 'add', value, left, top, width: 248 }); setPopoverText(''); setPopoverDate(date || todayIso()); setPopoverErr({}); };
  const openEditPopover = (cx, cy, anno) => { const { left, top } = placePopover(cx, cy, 248); setPopover({ mode: 'edit', id: anno.id, createdAt: anno.createdAt, left, top, width: 248 }); setPopoverText(anno.text); setPopoverDate(anno.date); setPopoverErr({}); };
  const closePopover = () => { setPopover(null); setPopoverText(''); setPopoverDate(''); setPopoverErr({}); };
  const savePopover = () => {
    const text = popoverText.trim(); const errs = {};
    if (!popoverDate) errs.date = true; if (!text) errs.note = true;
    if (errs.date || errs.note) { setPopoverErr(errs); return; }
    if (popover.mode === 'add') {
      const { value } = resolveValAtDate(popoverDate);
      writeAnnotations([...annotationsRef.current, { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, date: popoverDate, value, text, createdAt: new Date().toISOString() }]);
    } else {
      writeAnnotations(annotationsRef.current.map((x) => {
        if (x.id !== popover.id) return x;
        const upd = { ...x, text };
        if (popoverDate && popoverDate !== x.date) { upd.date = popoverDate; upd.value = resolveValAtDate(popoverDate).value; }
        return upd;
      }));
    }
    closePopover();
  };
  const deleteAnnotation = (id) => writeAnnotations(annotationsRef.current.filter((x) => x.id !== id));
  const applyAnnoCursor = () => { const gd = gdRef.current; if (!gd) return; try { gd.querySelectorAll('.annotation, .annotation-text-g, .annotation text, .annotation rect').forEach((el) => { el.style.cursor = 'pointer'; }); } catch { /* ignore */ } };
  const handleInitialized = (_f, gd) => {
    gdRef.current = gd; applyAnnoCursor();
    try { if (!annoObserverRef.current && typeof MutationObserver !== 'undefined') { const obs = new MutationObserver(() => applyAnnoCursor()); obs.observe(gd, { childList: true, subtree: true }); annoObserverRef.current = obs; } } catch { /* ignore */ }
  };
  const handleClickAnnotation = (ev) => {
    const a = ev?.annotation; if (!a) return;
    const idx = ev.index;
    const found = (idx != null && idx < annotationsRef.current.length) ? annotationsRef.current[idx] : annotationsRef.current.find((x) => x.date === a.x && x.text === a.text);
    if (!found) return;
    const me = ev.event; let cx = me ? me.clientX : null; let cy = me ? me.clientY : null;
    if (cx == null) { const p = annoPixel(found); cx = p ? p.px : 200; cy = p ? p.py : 200; }
    openEditPopover(cx, cy, found);
  };
  const matchAnnoId = (text) => { const t = (text || '').trim(); const m = annotationsRef.current.filter((a) => a.text === t); return m.length ? m[0].id : null; };
  const handleContextMenu = (e) => {
    const gd = gdRef.current;
    let annoId = null;
    const onAnno = e.target?.closest?.('.annotation-text-g, .annotation, [class*="annotation"]');
    if (onAnno) annoId = matchAnnoId(onAnno.textContent);
    if (!annoId) { for (const a of annotationsRef.current) { const p = annoPixel(a); if (p && Math.hypot(e.clientX - p.px, e.clientY - p.py) <= 20) { annoId = a.id; break; } } }
    if (annoId) { e.preventDefault(); e.stopPropagation(); setCtxMenu({ x: e.clientX, y: e.clientY, annoId }); return; }
    e.preventDefault();
    let dataX = null; let dataY = null;
    try { const fl = gd._fullLayout; const bb = gd.getBoundingClientRect(); const dx = fl.xaxis.p2d(e.clientX - bb.left - fl.xaxis._offset); dataX = (typeof dx === 'number') ? isoDay(dx) : dx; dataY = fl.yaxis.p2d(e.clientY - bb.top - fl.yaxis._offset); } catch { /* ignore */ }
    setCtxMenu({ x: e.clientX, y: e.clientY, dataX, dataY, annoId: null });
  };
  const zoomHere = () => { if (ctxMenu?.dataX) { const t = Date.parse(ctxMenu.dataX); setXRange([isoDay(t - 30 * 86400000), isoDay(t + 30 * 86400000)]); } };
  const setStartDate = () => { if (ctxMenu?.dataX) setXRange([ctxMenu.dataX, (xRange?.[1]) ?? fullHi]); };
  const setEndDate = () => { if (ctxMenu?.dataX) setXRange([(xRange?.[0]) ?? fullLo, ctxMenu.dataX]); };
  const exportImage = async () => {
    const gd = gdRef.current; if (!gd) return;
    const name = securities.map((s) => s.ticker).join('-') || 'comparacion';
    try { const Plotly = (await import('plotly.js-dist-min')).default; Plotly.downloadImage(gd, { format: 'png', filename: `comparacion_${name}_${range.to}`, width: 1400, height: 600 }); } catch { /* ignore */ }
  };

  // active theme (for theme-aware annotation bg)
  const isLight = (typeof document !== 'undefined') && document.documentElement.getAttribute('data-theme') === 'light';

  // --- declarative annotations + shapes ------------------------------------
  const userAnnotations = annotations.map((a) => ({
    xref: 'x', yref: 'y', x: a.date, y: a.value, text: a.text,
    showarrow: true, arrowhead: 2, arrowsize: 1, arrowcolor: '#F5A623', ax: 0, ay: -40,
    font: { color: '#F5A623', family: PLEX, size: 10 }, bgcolor: isLight ? '#FFFFFF' : '#1F1918', bordercolor: '#F5A623', borderpad: 5, borderwidth: 1, captureevents: true,
  }));
  const abAnnotations = [];
  if (pointA) abAnnotations.push({ x: pointA.date, xref: 'x', y: 1.02, yref: 'paper', text: 'A', showarrow: false, xanchor: 'center', yanchor: 'bottom', font: { color: '#5B8CFF', family: PLEX, size: 11 } });
  if (pointB) abAnnotations.push({ x: pointB.date, xref: 'x', y: 1.02, yref: 'paper', text: 'B', showarrow: false, xanchor: 'center', yanchor: 'bottom', font: { color: '#5B8CFF', family: PLEX, size: 11 } });
  const hoverAnnotations = hover ? [
    { x: hover.date, xref: 'x', y: -0.08, yref: 'paper', text: hover.fmtDate, showarrow: false, bgcolor: '#5B8CFF', font: { color: '#FFFFFF', family: PLEX, size: 10 }, borderpad: 4, xanchor: 'center', yanchor: 'top' },
    ...(hover.bubbleVal != null ? [{ x: -0.01, xref: 'paper', y: hover.bubbleVal, yref: 'y', text: sgn(hover.bubbleVal), showarrow: false, bgcolor: '#5B8CFF', font: { color: '#FFFFFF', family: PLEX, size: 10 }, borderpad: 4, xanchor: 'right', yanchor: 'middle' }] : []),
  ] : [];
  const chartAnnotations = [...userAnnotations, ...abAnnotations, ...hoverAnnotations];
  const abShapes = [];
  if (pointA) abShapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: pointA.date, x1: pointA.date, y0: 0, y1: 1, line: { color: '#5B8CFF', width: 1, dash: 'dot' } });
  if (pointB) abShapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: pointB.date, x1: pointB.date, y0: 0, y1: 1, line: { color: '#5B8CFF', width: 1, dash: 'dot' } });
  const dragmode = analysing ? false : 'zoom';

  // --- selection -----------------------------------------------------------
  const addSecurity = (sec) => {
    if (!sec) return;
    if (securities.some((s) => s.entity_id === sec.entity_id)) { setAdding(false); return; }
    if (securities.length >= MAX_SECURITIES) { setMaxMsg(true); return; }
    const used = securities.map((s) => s.color);
    const color = PALETTE.find((c) => !used.includes(c)) || PALETTE[0];
    setSecurities((prev) => [...prev, { entity_id: sec.entity_id, ticker: sec.ticker, display_name: sec.display_name, isin: sec.isin, color }]);
    setMaxMsg(false); setAdding(false);
  };
  const removeSecurity = (eid) => {
    setSecurities((prev) => prev.filter((s) => s.entity_id !== eid));
    setHidden((prev) => { const n = new Set(prev); n.delete(eid); return n; });
    setMaxMsg(false);
  };

  // --- Retornos table -------------------------------------------------------
  const allDates = useMemo(() => {
    const set = new Set();
    prep.forEach((p) => p.pts.forEach((q) => set.add(q.date)));
    return [...set].sort();
  }, [prep]);
  const [cmpVisible, setCmpVisible] = useState(() => new Set());
  const [cmpChooser, setCmpChooser] = useState(false);
  const cmpToolsRef = useRef(null);
  // table columns: per security a Price + Cum Ret pair
  const COLS = securities.flatMap((s) => [
    { key: `${s.entity_id}-price`, label: 'Price', type: 'price', sec: s },
    { key: `${s.entity_id}-cum`, label: 'Cum Ret', type: 'cum', sec: s },
  ]);
  useEffect(() => { setCmpVisible(new Set(COLS.map((c) => c.key))); }, [secKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!cmpChooser) return undefined;
    const onDoc = (e) => { if (cmpToolsRef.current && !cmpToolsRef.current.contains(e.target)) setCmpChooser(false); };
    document.addEventListener('mousedown', onDoc); return () => document.removeEventListener('mousedown', onDoc);
  }, [cmpChooser]);
  const toggleCmpCol = (key) => setCmpVisible((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  // visible groups (one per security, only its visible columns)
  const cmpGroups = prep.map((p) => ({
    sec: p.s,
    cols: COLS.filter((c) => c.sec.entity_id === p.s.entity_id && cmpVisible.has(c.key)),
  })).filter((g) => g.cols.length > 0);
  const sortedDates = sort === 'asc' ? [...allDates] : sort === 'desc' ? [...allDates].reverse() : allDates;
  const cellFor = (p, date, type) => {
    const price = p.priceMap.get(date);
    if (price == null) return null;
    return type === 'price' ? price : cumOf(p.base, price);
  };
  const cycleSort = () => setSort((s) => (s === 'desc' ? 'asc' : s === 'asc' ? null : 'desc'));
  const exportCsv = () => {
    const flatCols = cmpGroups.flatMap((g) => g.cols);
    const headers = ['Date', ...flatCols.map((c) => `${c.sec.ticker} ${c.label}`)];
    const rows = sortedDates.map((date) => [date, ...flatCols.map((c) => {
      const p = prep.find((x) => x.s.entity_id === c.sec.entity_id);
      const v = cellFor(p, date, c.type);
      return v == null ? '' : v.toFixed(2);
    })]);
    downloadCsv(`comparacion_retornos_${range.to}`, headers, rows);
  };

  return (
    <div>
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">Comparison</div>
      </div>
      <p className="page-sub">Cumulative return of multiple securities, indexed to 0% at the start of the period.</p>

      {/* selector */}
      <div className="panel">
        <div className="pc-select">
          <span className="pc-select-lbl">Comparing:</span>
          {securities.map((s) => (
            <span key={s.entity_id} className="pc-chip" style={{ borderColor: s.color }}>
              <span className="pc-chip-dot" style={{ background: s.color }} />
              {s.ticker}
              <button type="button" className="pc-chip-x" onClick={() => removeSecurity(s.entity_id)} aria-label={`Remove ${s.ticker}`}>×</button>
            </span>
          ))}
          {adding ? (
            <div className="pc-add-box">
              <SecuritySearch value={null} autoSelectFirst={false} onSelect={(sec) => addSecurity(sec)} />
            </div>
          ) : (
            <button type="button" className="btn" onClick={() => { if (securities.length >= MAX_SECURITIES) { setMaxMsg(true); } else { setAdding(true); } }}>+ Add</button>
          )}
          {maxMsg && <span className="pc-max-msg">Maximum 6 securities</span>}
        </div>
      </div>

      {/* summary cards */}
      {cards.length > 0 && (
        <div className="pc-cards">
          {cards.map((c) => {
            const isBest = c.s.entity_id === bestId;
            return (
            <div key={c.s.entity_id} className={`pc-card ${isBest ? 'accent' : ''}`} style={{ borderLeft: isBest ? 'none' : `3px solid ${c.s.color}` }}>
              <div className="pc-card-ticker" style={{ color: isBest ? '#FFFFFF' : c.s.color }}>{c.s.ticker}{isBest ? ' ★' : ''}</div>
              <div className="pc-card-name">{c.name}</div>
              <div className="pc-card-div" />
              {c.insufficient ? (
                <>
                  <div className="pc-card-row"><span className="pc-card-lbl">Total Return</span><span className="pc-card-big">—</span></div>
                  <div className="pc-card-row"><span className="pc-card-lbl">Annualized</span><span className="pc-card-big">—</span></div>
                  <div className="pc-card-note">Insufficient data</div>
                </>
              ) : (
                <>
                  <div className="pc-card-row"><span className="pc-card-lbl">Total Return</span><span className={`pc-card-big ${c.totalRet >= 0 ? 'pos' : 'neg'}`}>{sgn(c.totalRet)}</span></div>
                  <div className="pc-card-row"><span className="pc-card-lbl">Annualized</span><span className={`pc-card-big ${c.annual >= 0 ? 'pos' : 'neg'}`}>{sgn1(c.annual)}</span></div>
                  <div className="pc-card-div" />
                  <div className="pc-card-se"><span className="pc-card-lbl">Start</span><span className="pc-card-price">{c.start.price.toFixed(2)}</span><span className="pc-card-date">{fmtDisplay(c.start.date)}</span></div>
                  <div className="pc-card-se"><span className="pc-card-lbl">End</span><span className="pc-card-price">{c.end.price.toFixed(2)}</span><span className="pc-card-date">{fmtDisplay(c.end.date)}</span></div>
                </>
              )}
            </div>
            );
          })}
        </div>
      )}

      {/* chart */}
      <div className="panel">
        {securities.length === 0 ? (
          <div className="muted">Add securities to compare.</div>
        ) : (
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
                  uirevision: 'cmp-chart-stable',
                  dragmode,
                  margin: { l: 60, r: 20, t: 30, b: 64 },
                  annotations: chartAnnotations,
                  shapes: abShapes,
                  showlegend: false,
                  xaxis: { title: '', hoverformat: '%Y-%m-%d', ...X_SPIKE, ...(xRange ? { range: xRange, autorange: false } : { autorange: true }) },
                  yaxis: { title: 'Cumulative Return (%)', zeroline: true, ...Y_SPIKE },
                }}
              />

              {hover && (
                <div className="px-hover" style={{ left: hover.left, top: hover.top }}>
                  <div className="px-tip">
                    <div className="px-tip-date">{hover.fmtDate}</div>
                    {hover.sections.map((s, i) => (
                      <div key={s.ticker ?? i}>
                        <div className="px-tip-div" />
                        <div className="px-tip-head" style={{ color: s.color }}>{s.ticker}</div>
                        <div className="px-tip-row"><span className="px-tip-label">Cumulative Return</span><span className={`px-tip-val ${s.cum == null ? '' : s.cum >= 0 ? 'pos' : 'neg'}`}>{sgn(s.cum)}</span></div>
                        <div className="px-tip-row"><span className="px-tip-label">Daily Return</span><span className={`px-tip-val ${s.dayRet == null ? '' : s.dayRet >= 0 ? 'pos' : 'neg'}`}>{s.dayRet == null ? '—' : sgn(s.dayRet * 100)}</span></div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="chart-controls">
              <div className="chart-legend">
                {securities.map((s) => {
                  const off = hidden.has(s.entity_id);
                  return (
                    <button key={s.entity_id} type="button" className={`legend-item ${off ? 'off' : ''}`} onClick={() => toggleSec(s.entity_id)} title={off ? 'Show' : 'Hide'}>
                      <span className="legend-dot" style={{ background: s.color }} />
                      {s.ticker}
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
        )}
      </div>

      {/* analysis panel */}
      {analysis && (
        <div className="measure-panel">
          <div className="measure-head">
            <div className="measure-head-text">
              <span className="measure-title">ANALYSIS</span>
              <span className="measure-range">{formatDateLabel(analysis.startDate)} → {formatDateLabel(analysis.endDate)}</span>
            </div>
            <button type="button" className="measure-close" onClick={dismissAnalysis} title="Dismiss" aria-label="Dismiss analysis">×</button>
          </div>
          <div className="measure-days">{analysis.days} days</div>
          {analysis.sections.map((sec) => (
            <div key={sec.ticker}>
              <div className="measure-div" />
              <div className="measure-head-text"><span className="measure-title" style={{ color: sec.color }}>{sec.ticker}</span></div>
              <div className="measure-rows">
                <div className="measure-row"><span className="measure-label">Return (period)</span><span className={`measure-val ${sec.ret >= 0 ? 'pos' : 'neg'}`}>{sgn(sec.ret)}</span></div>
                <div className="measure-row"><span className="measure-label">Annualized</span><span className={`measure-val ${sec.annual >= 0 ? 'pos' : 'neg'}`}>{sgn1(sec.annual)}</span></div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* table */}
      <div className="panel">
        <div className="panel-title">Returns</div>
        {securities.length && allDates.length ? (
          <>
            <div className="table-tools">
              <div />
              <div className="right" ref={cmpToolsRef}>
                <button className="btn" onClick={exportCsv} title="Export visible columns as CSV">↓ CSV</button>
                <button className="btn" onClick={() => setCmpChooser((v) => !v)} title="Show / hide columns">⊞ Columns</button>
                {cmpChooser && (
                  <div className="col-chooser">
                    {COLS.map((c) => (
                      <label className="row" key={c.key}>
                        <input type="checkbox" checked={cmpVisible.has(c.key)} onChange={() => toggleCmpCol(c.key)} />
                        {c.sec.ticker} {c.label}
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
                  {cmpGroups.flatMap((g) => g.cols.map((c) => <col key={c.key} style={{ width: 120 }} />))}
                </colgroup>
                <thead>
                  <tr className="cmp-grp">
                    <th rowSpan={2} className="cmp-date cmp-sortable" onClick={cycleSort} title="Sort by date">
                      Date <span className={`cmp-sort-ind ${sort ? 'on' : ''}`}>{sort === 'desc' ? '↓' : sort === 'asc' ? '↑' : '↕'}</span>
                    </th>
                    {cmpGroups.map((g, gi) => (
                      <th key={g.sec.entity_id} colSpan={g.cols.length} className={gi > 0 ? 'cmp-div' : ''} style={{ color: g.sec.color }}>{g.sec.ticker}</th>
                    ))}
                  </tr>
                  <tr className="cmp-col">
                    {cmpGroups.flatMap((g, gi) => g.cols.map((c, ci) => (
                      <th key={c.key} className={gi > 0 && ci === 0 ? 'cmp-div' : ''}>{c.label}</th>
                    )))}
                  </tr>
                </thead>
                <tbody>
                  {sortedDates.map((date) => (
                    <tr key={date}>
                      <td className="cmp-date num">{date}</td>
                      {cmpGroups.flatMap((g, gi) => {
                        const p = prep.find((x) => x.s.entity_id === g.sec.entity_id);
                        return g.cols.map((c, ci) => {
                          const divider = gi > 0 && ci === 0 ? 'cmp-div' : '';
                          const v = cellFor(p, date, c.type);
                          if (c.type === 'price') return <td key={c.key} className={`num ${divider}`}>{v == null ? '—' : v.toFixed(2)}</td>;
                          return <td key={c.key} className={`num ${divider} ${v == null ? '' : v >= 0 ? 'pos' : 'neg'}`}>{v == null ? '—' : sgn(v)}</td>;
                        });
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="muted">No data for the selected securities and period.</div>
        )}
      </div>

      {/* context menu */}
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
              <button type="button" className="px-ctx-item" onClick={() => { exportCsv(); setCtxMenu(null); }}>Export data (CSV)</button>
            </>
          )}
        </div>,
        document.body,
      )}

      {/* add/edit annotation popover */}
      {popover && typeof document !== 'undefined' && createPortal(
        <div ref={popRef} className="px-pop" style={{ left: popover.left, top: popover.top, width: popover.width }}>
          <div className="px-pop-title">{popover.mode === 'add' ? 'Add note' : 'Edit note'}</div>
          <div className="px-pop-div" />
          <div className="px-pop-label">Date</div>
          <input type="date" className="px-pop-input px-date" value={popoverDate} onChange={(e) => setPopoverDate(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') savePopover(); else if (e.key === 'Escape') closePopover(); }} />
          {popoverErr.date && <div className="notes-err">Required</div>}
          {popoverDate && resolveValAtDate(popoverDate).outOfRange && <div className="notes-warn">Outside loaded range — using nearest value</div>}
          <div className="px-pop-label" style={{ marginTop: 8 }}>Note</div>
          <input className="px-pop-input" autoFocus value={popoverText} placeholder="e.g. earnings, split, macro event..." onChange={(e) => setPopoverText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') savePopover(); else if (e.key === 'Escape') closePopover(); }} />
          {popoverErr.note && <div className="notes-err">Required</div>}
          {popover.mode === 'edit' && popover.createdAt && <div className="px-pop-meta">Added: {fmtStamp(popover.createdAt)}</div>}
          <div className="px-pop-actions">
            {popover.mode === 'edit' && <button type="button" className="px-pop-del" onClick={() => { deleteAnnotation(popover.id); closePopover(); }}>Delete</button>}
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
