// web/apps/dashboards/components/DataDownload.js
// ---------------------------------------------------------------------------
// OURS. "Download this chart's data": a CSV with EXACTLY what the chart
// draws, built in the browser from its traces.
//
// That is why it receives the Plotly traces and asks the API for nothing:
// the view already carries its conversion - level, base 100, alpha in bps,
// ranks - and what the operator wants in Excel is THAT reading, not the raw
// series they already have in the Book. One column per trace (its legend
// name), one row per X value, in order of appearance. Where a trace has no
// value for that X, the cell is empty.
//
// UTF-8 with BOM so Excel reads the accents; comma as separator, the same
// as the CSV the Book exports from the server.
// ---------------------------------------------------------------------------
'use client';

const esc = (v) => {
  const t = v == null ? '' : String(v);
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
};

export function csvFromTraces(traces, xAxis = 'date') {
  const xs = [];
  const seen = new Set();
  traces.forEach((t) => (t.x || []).forEach((x) => {
    const k = String(x);
    if (!seen.has(k)) { seen.add(k); xs.push(k); }
  }));
  const byTrace = traces.map((t) => {
    const m = new Map();
    (t.x || []).forEach((x, i) => m.set(String(x), t.y?.[i]));
    return m;
  });
  const header = [xAxis, ...traces.map((t) => t.name ?? '')].map(esc).join(',');
  const rows = xs.map((x) => [x, ...byTrace.map((m) => {
    const v = m.get(x);
    return v == null || Number.isNaN(v) ? '' : v;
  })].map(esc).join(','));
  return [header, ...rows].join('\n');
}

export function downloadText(name, text, type = 'text/csv;charset=utf-8') {
  const blob = new Blob(['﻿' + text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * The button. `name` is the file without extension; it should say what the
 * chart title says (scale, fund, window), because the file is looked at
 * later, far from the screen that produced it.
 */
export default function DataDownload({ traces, name, xAxis = 'date', label = '↓ Data · CSV' }) {
  const any = Array.isArray(traces) && traces.some((t) => t.x?.length);
  return (
    <button type="button" className="btn" disabled={!any}
      title={any ? 'Download what the chart shows, with its conversion' : 'Nothing to download'}
      onClick={() => downloadText(`${name}.csv`, csvFromTraces(traces, xAxis))}>
      {label}
    </button>
  );
}
