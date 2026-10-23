// web/apps/dashboards/lib/spp.js
// ---------------------------------------------------------------------------
// SPP tablero helpers: es-PE number/date formatting and the domain constants,
// ported from the monitor's base.js. Valor cuota carries 7 decimals (as the
// SBS publishes it); cuotas and fondo are billions and abbreviate with the
// Peruvian desk convention (M = thousands, MM = millions).
//
// The interface names no AFP and no metric: everything comes from
// /api/spp/config. These are the one copy of the cfg lookups the pages share.
// ---------------------------------------------------------------------------

import { BASE } from './api';

// Absolute URL for download links (CSV/XLSX) that bypass fetch.
export const apiUrl = (path) => `${BASE}${path}`;

// FALLBACKS only, for the instant before /api/spp/config arrives: the metric
// universe and its labels are owned by the backend (cfg.metrics). 'Cuotas' is
// neither here nor there: the figure exists and the closing table shows it,
// but charting it says nothing. METRIC_NAMES keeps it because the API still
// accepts metric=cuotas and it has to be called something.
export const METRICS = [
  ['Valor cuota', 'valor_cuota'],
  ['Fondo (S/)', 'fondo'],
];
export const METRIC_NAMES = {
  valor_cuota: 'Valor cuota', cuotas: 'Cuotas', fondo: 'Fondo (S/)',
};

// The ONE neutral gray of the house-vs-grays scheme (charts, heatmap,
// fallback chip) - retune it here and every consumer follows.
export const COMPETITOR_GRAY = 'rgb(128, 138, 152)';
export const GRAY_HEX = '#8892A4';
export const grayLine = (alpha) => `rgba(128, 138, 152, ${alpha})`;

// The ONE house-first ordering (legends, tables, heatmap rows): the house
// AFP (cfg.house) leads, the rest keep their relative order.
export const houseFirst = (cfg, list) => {
  const house = cfg?.house;
  return house && list.includes(house)
    ? [house, ...list.filter((a) => a !== house)]
    : [...list];
};

export const afpOf = (cfg, afp) => (cfg?.afps || []).find((a) => a.name === afp);
export const operates = (cfg, afp, fund) => {
  const a = afpOf(cfg, afp);
  return a ? a.funds.includes(fund) : true;
};
export const fundsOf = (cfg, afp) => (cfg?.funds || []).filter((f) => operates(cfg, afp, f));
export const colorOf = (cfg, afp, solid = false) => {
  const a = afpOf(cfg, afp);
  return a ? (solid ? a.color_solid : a.color) : GRAY_HEX;
};
export const metricsOf = (cfg) =>
  (cfg?.metrics?.length ? cfg.metrics.map((m) => [m.label, m.key]) : METRICS);
export const metricName = (cfg, key) =>
  (cfg?.metrics || []).find((m) => m.key === key)?.label
    || METRIC_NAMES[key] || key;

// Ordered by what they span. FY is the fiscal year, 31/10 to 31/10: it goes
// after YTD because it is almost always longer - only in November and
// December, just started, is it shorter than the calendar year.
export const WINDOWS = [
  ['MTD', 'mtd'], ['YTD', 'ytd'], ['FY', 'fy'], ['1A', 1], ['3A', 3], ['5A', 5], ['10A', 10],
];

export const sign = (v) => (v == null ? '' : (v < 0 ? 'neg' : (v > 0 ? 'pos' : '')));

export const nf = (v, d = 7) =>
  (v == null ? '—' : v.toLocaleString('es-PE',
    { minimumFractionDigits: d, maximumFractionDigits: d }));

export const nInt = (v) => (v == null ? '—' : v.toLocaleString('es-PE'));

export function fmtMetric(v, metric, compact = false) {
  if (v == null) return '—';
  const fixed = (x, d) => x.toLocaleString('es-PE',
    { minimumFractionDigits: d, maximumFractionDigits: d });
  if (metric === 'valor_cuota') return fixed(v, 7);
  if (compact) {
    const a = Math.abs(v);
    if (a >= 1e6) return `${fixed(v / 1e6, 2)} MM`;
    if (a >= 1e3) return `${fixed(v / 1e3, 2)} M`;
  }
  return fixed(v, 2);
}

export const fDate = (s) => {
  if (!s) return '—';
  const [y, m, d] = String(s).split('-');
  return `${d}/${m}/${y}`;
};

// Timestamp with the hour in 24h, like every other hour in the tablero (the
// scheduled task reads "16:00"; es-PE's default would print "04:00 p. m."
// right next to it). The API serializes timestamps as ISO at the source, so
// plain Date parsing here is unambiguous.
export const fTime = (t) => {
  if (!t) return '—';
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleString('es-PE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
};

// Today in the user's zone. valueAsDate interprets Dates in UTC, so from
// 19:00 Lima onward the naive approach yields tomorrow and the form
// rejects it as a future date.
export function todayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Value as displayed, already rounded. Sign and color derive from THIS
// number, not the raw one - otherwise -0.4 bps prints as "-0 bps".
// `bpsDigits` is how many decimals a basis-point figure keeps (one by
// default; the relative table asks for none).
export function shownValue(v, unit, bpsDigits = 1) {
  if (v == null) return null;
  if (unit === 'pct') return +(v * 100).toFixed(2);
  if (unit === 'level') return v;
  return +(v * 10000).toFixed(bpsDigits);
}

// A window without enough history (a 10A on a fund born in 2016) is a plain
// dash, not a figure.
export function fmtReturn(v, unit, metric = 'valor_cuota', bpsDigits = 1) {
  const x = shownValue(v, unit, bpsDigits);
  if (x == null) return '-';
  if (unit === 'level') return fmtMetric(x, metric, metric !== 'valor_cuota');
  const s = x > 0 ? '+' : (x < 0 ? '-' : '');
  const digits = unit === 'pct' ? 2 : bpsDigits;
  const abs = Math.abs(x).toLocaleString('es-PE', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  // Basis points carry no suffix: the tables say which columns are in
  // basis points, and " bps" seventeen times a row only widened them.
  return s + abs + (unit === 'pct' ? '%' : '');
}

// MTD/YTD/FY start at the LAST CLOSE of the prior period (same base the
// windows tables use); numeric values are years back from the control date.
//
// The calendar branch below is the FALLBACK for the instant before
// /api/spp/windows arrives. It lands on the calendar day, which may not be a
// trading day; once the reference dates arrive the close wins.
export function windowStart(w, status, refDates) {
  const base = refDates || {};
  if (w === 'mtd' && base.month) return base.month;
  if (w === 'ytd' && base.year) return base.year;
  if (w === 'fy' && base.fy) return base.fy;
  const h = status && status.to ? new Date(`${status.to}T00:00:00`) : new Date();
  if (w === 'mtd') { const d = new Date(h.getFullYear(), h.getMonth(), 0); return d.toISOString().slice(0, 10); }
  if (w === 'ytd') { const d = new Date(h.getFullYear(), 0, 0); return d.toISOString().slice(0, 10); }
  if (w === 'fy') {
    // 31/10 closes the fiscal year, it does not open it: standing on that
    // date one reads the year that ends. Hence the cut is "after 31/10",
    // the same as the backend (fiscal_year_start).
    const yearEnd = new Date(h.getFullYear(), 9, 31);
    const year = h > yearEnd ? h.getFullYear() : h.getFullYear() - 1;
    return new Date(year, 9, 31).toISOString().slice(0, 10);
  }
  h.setFullYear(h.getFullYear() - w);
  return h.toISOString().slice(0, 10);
}

// The chart window of our panels from the pill's quick period (the same
// keys the upstream dashboards use). The range ends at `to` - the control
// date, or the series' own last date - and starts the period before it.
// YTD starts at the last close of the prior year when the reference dates
// are known (the base the return tables use), else at 31/12. 'Custom' is
// the pill's own two dates. Dates are built by parts: toISOString would
// drift a day from 19:00 Lima onward.
export function periodWindow(period, to, { customFrom, customTo, refDates } = {}) {
  if (period === 'Custom' && customFrom && customTo) return { from: customFrom, to: customTo };
  if (!to) return { from: null, to: null };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const end = new Date(`${to}T00:00:00`);
  if (period === 'YTD') {
    if (refDates?.year) return { from: refDates.year, to };
    return { from: iso(new Date(end.getFullYear(), 0, 0)), to };
  }
  const start = new Date(end);
  if (period === '1M') start.setMonth(start.getMonth() - 1);
  else if (period === '3M') start.setMonth(start.getMonth() - 3);
  else start.setFullYear(start.getFullYear() - 1);          // '1Y', and anything unknown
  return { from: iso(start), to };
}

// Cumulative alpha: the house's base-100 curve minus each competitor's, in
// basis points, from the first date with data in EVERY series (the same rule
// Base 100 uses: every line starts from the same zero). Only the arithmetic:
// the Panel and the PDF report each dress it their own way.
export function alphaOf(series, house) {
  const withData = (series || []).filter((s) => s.points?.length);
  const own = withData.find((s) => s.afp === house);
  const others = withData.filter((s) => s.afp !== house);
  if (!own || !others.length) return [];
  const starts = withData.map((s) => s.points[0][0]);
  const baseDate = starts.reduce((m, d) => (d > m ? d : m), starts[0]);
  const from = (s) => s.points.filter((p) => p[0] >= baseDate);
  const housePts = from(own);
  if (!housePts.length) return [];
  const houseBy = new Map(housePts.map((p) => [p[0], p[1]]));
  const house0 = housePts[0][1];
  return others.map((s) => {
    const pts = from(s).filter((p) => houseBy.has(p[0]));
    if (!pts.length) return null;
    const other0 = pts[0][1];
    return {
      afp: s.afp,
      x: pts.map((p) => p[0]),
      y: pts.map((p) => ((houseBy.get(p[0]) / house0) - (p[1] / other0)) * 10000),
    };
  }).filter(Boolean);
}
