
// web/apps/dashboards/lib/spp.js
// ---------------------------------------------------------------------------
// SPP tablero helpers: es-PE number/date formatting and the domain constants,
// ported from the monitor's base.js. Valor cuota carries 7 decimals (as the
// SBS publishes it); cuotas and fondo are billions and abbreviate with the
// Peruvian desk convention (M = thousands, MM = millions).
// ---------------------------------------------------------------------------

import { BASE } from './api';

// Absolute URL for download links (CSV/XLSX) that bypass fetch.
export const apiUrl = (path) => `${BASE}${path}`;

// Mutating fetch (JSON or FormData). Returns {ok, status, data} instead of
// throwing so callers can show the backend's `motivo` verbatim.
export async function apiSend(path, method, body, isForm = false) {
  const opts = { method };
  if (body !== undefined) {
    if (isForm) { opts.body = body; } else {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(`${BASE}${path}`, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

// FALLBACKS only, for the instant before /api/spp/config arrives: the
// metric universe and its labels are owned by the backend (cfg.metricas)
// - use metricasDe(cfg) / nombreMetrica(cfg, clave) below.
export const METRICAS = [
  ['Valor cuota', 'valor_cuota'],
  ['Cuotas', 'cuotas'],
  ['Fondo (S/)', 'fondo'],
];
export const NOMBRE_METRICA = {
  valor_cuota: 'Valor cuota', cuotas: 'Cuotas', fondo: 'Fondo (S/)',
};
// Presentation copy, legitimately client-side ("Último cuotas" can't be said).
export const ROTULO_KPI = {
  valor_cuota: 'Último valor cuota', cuotas: 'Cuotas al cierre',
  fondo: 'Fondo al cierre (S/)',
};

// ---- Config-driven helpers ------------------------------------------------
// The interface names no AFP and no metric: everything comes from
// /api/spp/config. These are the one copy of the cfg lookups the pages share.
export const afpDe = (cfg, afp) => (cfg?.afps || []).find((a) => a.nombre === afp);
export const opera = (cfg, afp, f) => {
  const a = afpDe(cfg, afp);
  return a ? a.fondos.includes(f) : true;
};
export const fondosDe = (cfg, afp) => (cfg?.fondos || []).filter((f) => opera(cfg, afp, f));
export const colorDe = (cfg, afp, solido = false) => {
  const a = afpDe(cfg, afp);
  return a ? (solido ? a.color_solido : a.color) : '#8892A4';
};
export const metricasDe = (cfg) =>
  (cfg?.metricas?.length ? cfg.metricas.map((m) => [m.etiqueta, m.clave]) : METRICAS);
export const nombreMetrica = (cfg, clave) =>
  (cfg?.metricas || []).find((m) => m.clave === clave)?.etiqueta
    || NOMBRE_METRICA[clave] || clave;
export const VENTANAS = [
  ['MTD', 'mtd'], ['YTD', 'ytd'], ['1A', 1], ['3A', 3], ['5A', 5], ['10A', 10],
];

export const signo = (v) => (v == null ? '' : (v < 0 ? 'neg' : (v > 0 ? 'pos' : '')));

export const nf = (v, d = 7) =>
  (v == null ? '—' : v.toLocaleString('es-PE',
    { minimumFractionDigits: d, maximumFractionDigits: d }));

export const nEnt = (v) => (v == null ? '—' : v.toLocaleString('es-PE'));

export function fmtMetrica(v, metrica, compacto = false) {
  if (v == null) return '—';
  const fijo = (x, d) => x.toLocaleString('es-PE',
    { minimumFractionDigits: d, maximumFractionDigits: d });
  if (metrica === 'valor_cuota') return fijo(v, 7);
  if (compacto) {
    const a = Math.abs(v);
    if (a >= 1e6) return `${fijo(v / 1e6, 2)} MM`;
    if (a >= 1e3) return `${fijo(v / 1e3, 2)} M`;
  }
  return fijo(v, 2);
}

export const fFecha = (s) => {
  if (!s) return '—';
  const [a, m, d] = String(s).split('-');
  return `${d}/${m}/${a}`;
};

// Today in the user's zone. valueAsDate interprets Dates in UTC, so from
// 19:00 Lima onward the naive approach yields tomorrow and the form
// rejects it as a future date.
export function hoyLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Value as displayed, already rounded. Sign and color derive from THIS
// number, not the raw one - otherwise -0.4 bps prints as "-0 bps".
export function valorMostrado(v, unidad) {
  if (v == null) return null;
  if (unidad === 'pct') return +(v * 100).toFixed(2);
  if (unidad === 'nivel') return v;
  return +(v * 10000).toFixed(1);
}

export function fmtRend(v, unidad, metrica = 'valor_cuota') {
  const x = valorMostrado(v, unidad);
  if (x == null) return '—';
  if (unidad === 'nivel') return fmtMetrica(x, metrica, metrica !== 'valor_cuota');
  const s = x > 0 ? '+' : (x < 0 ? '-' : '');
  const abs = Math.abs(x).toLocaleString('es-PE', {
    minimumFractionDigits: unidad === 'pct' ? 2 : 1,
    maximumFractionDigits: unidad === 'pct' ? 2 : 1,
  });
  return s + abs + (unidad === 'pct' ? '%' : ' bps');
}

// MTD/YTD start at the LAST CLOSE of the prior period (same base the
// windows tables use); numeric values are years back from the last close.
export function desdeVentana(v, estado, fechasVent) {
  const base = fechasVent || {};
  if (v === 'mtd' && base.mes) return base.mes;
  if (v === 'ytd' && base.anio) return base.anio;
  const h = estado && estado.hasta ? new Date(`${estado.hasta}T00:00:00`) : new Date();
  if (v === 'mtd') { const d = new Date(h.getFullYear(), h.getMonth(), 0); return d.toISOString().slice(0, 10); }
  if (v === 'ytd') { const d = new Date(h.getFullYear(), 0, 0); return d.toISOString().slice(0, 10); }
  h.setFullYear(h.getFullYear() - v);
  return h.toISOString().slice(0, 10);
}
