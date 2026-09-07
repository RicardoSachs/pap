
// web/apps/dashboards/components/Header.js
// ---------------------------------------------------------------------------
// Fixed top header: brand, portfolio selector, period control (quick buttons +
// Custom date inputs), source selector, freshness indicator, theme toggle.
// All bound to DashboardProvider.
//
// On the SPP tablero (/spp/*) the dashboard context does not apply - that
// view has its own VENTANA control and no portfolio/source dimension - so
// the context controls are hidden there to avoid a dead selector that looks
// like it should drive the page.
// ---------------------------------------------------------------------------
'use client';

import { usePathname } from 'next/navigation';
import { useDashboard } from './DashboardProvider';
import ThemeToggle from './ThemeToggle';
import { fmtDisplay } from '../lib/period';
import { rutaActiva } from '../lib/rutas';

export default function Header() {
  const d = useDashboard();
  const path = usePathname();
  if (!d) return null;

  const isCustom = d.period === 'Custom';

  if (rutaActiva(path, '/spp/')) {
    return (
      <header className="header">
        <span className="brand">Profuturo Analytics</span>
        <div className="spacer" />
        <span className="freshness" title="Reference data — current as of the latest load">
          <span className="dot" /> Data current
        </span>
        <ThemeToggle />
      </header>
    );
  }

  return (
    <header className="header">
      <span className="brand">Profuturo Analytics</span>

      <div className="hgroup">
        <select
          className="select"
          value={d.portfolioId}
          onChange={(e) => d.setPortfolioId(e.target.value)}
          aria-label="Portfolio"
        >
          {d.portfolios.length === 0 && <option value="">Loading…</option>}
          {d.portfolios.map((p) => (
            <option key={p.portfolio_id} value={p.portfolio_id}>{p.display_name}</option>
          ))}
        </select>
      </div>

      <div className="period-control">
        <div className="period-group">
          {d.periods.map((p) => (
            <button
              key={p}
              className={`period-btn ${d.period === p ? 'active' : ''}`}
              onClick={() => d.setPeriod(p)}
            >
              {p}
            </button>
          ))}
          <button
            className={`period-btn ${isCustom ? 'active' : ''}`}
            onClick={() => d.setPeriod('Custom')}
          >
            Custom
          </button>
        </div>

        <div className="period-sub">
          {isCustom ? (
            <span className="custom-dates">
              <label>From
                <input
                  type="date"
                  className="date-input"
                  value={d.customFrom || ''}
                  max={d.customTo || undefined}
                  onChange={(e) => d.setCustomFrom(e.target.value)}
                />
              </label>
              <label>To
                <input
                  type="date"
                  className="date-input"
                  value={d.customTo || ''}
                  min={d.customFrom || undefined}
                  onChange={(e) => d.setCustomTo(e.target.value)}
                />
              </label>
            </span>
          ) : (
            <span className="period-resolved">{fmtDisplay(d.range.from)} – {fmtDisplay(d.range.to)}</span>
          )}
        </div>
      </div>

      <div className="hgroup">
        <span className="hlabel">Source</span>
        <select
          className="select"
          value={d.source}
          onChange={(e) => d.setSource(e.target.value)}
          aria-label="Data source"
        >
          <option value="bloomberg">Bloomberg</option>
          <option value="fms">FMS</option>
        </select>
      </div>

      <div className="spacer" />

      <span className="freshness" title="Reference data — current as of the latest load">
        <span className="dot" /> Data current
      </span>

      <ThemeToggle />
    </header>
  );
}

