// web/apps/dashboards/components/KpiBar.js
// ---------------------------------------------------------------------------
// Horizontal KPI strip. Each tile: small uppercase label, large monospace
// value, small metadata line. tone: 'pos' | 'neg' | undefined.
// A tile may be flagged accent:true (brand-filled, white text — used for the
// last/highlight tile per page) and may carry spark:[numbers] to render a tiny
// inline SVG trend line (72×24) under the value.
// ---------------------------------------------------------------------------
'use client';

// Build an SVG path across the value range, scaled to a 72×24 viewBox.
function sparkPath(data, w = 72, h = 24, pad = 2) {
  if (!Array.isArray(data) || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const n = data.length;
  const pts = data.map((v, i) => {
    const x = pad + (i / (n - 1)) * (w - 2 * pad);
    const y = h - pad - ((v - min) / span) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return `M${pts.join(' L')}`;
}

function Sparkline({ data }) {
  const d = sparkPath(data);
  if (!d) return null;
  return (
    <svg className="kpi-spark" viewBox="0 0 72 24" preserveAspectRatio="none" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export default function KpiBar({ tiles }) {
  return (
    <div className="kpi-bar">
      {tiles.map((t, i) => (
        <div className={`kpi-tile ${t.accent ? 'accent' : ''}`} key={i}>
          <span className="kpi-label">{t.label}</span>
          <span className={`kpi-value ${t.tone === 'pos' ? 'pos' : t.tone === 'neg' ? 'neg' : ''}`} style={t.valueStyle}>
            {t.value}
          </span>
          {t.spark && <Sparkline data={t.spark} />}
          {t.meta != null && t.meta !== '' && <span className="kpi-meta">{t.meta}</span>}
        </div>
      ))}
    </div>
  );
}
