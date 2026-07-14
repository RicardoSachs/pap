
// web/apps/dashboards/components/KpiBar.js
// ---------------------------------------------------------------------------
// Horizontal KPI strip. Each tile: small uppercase label, large monospace
// value, small metadata line. tone: 'pos' (teal) | 'neg' (rose) | undefined.
// ---------------------------------------------------------------------------
'use client';

export default function KpiBar({ tiles }) {
  return (
    <div className="kpi-bar">
      {tiles.map((t, i) => (
        <div className="kpi-tile" key={i}>
          <span className="kpi-label">{t.label}</span>
          <span className={`kpi-value ${t.tone === 'pos' ? 'pos' : t.tone === 'neg' ? 'neg' : ''}`}>
            {t.value}
          </span>
          {t.meta != null && t.meta !== '' && <span className="kpi-meta">{t.meta}</span>}
        </div>
      ))}
    </div>
  );
}

