// web/apps/dashboards/components/ModulePill.js
// ---------------------------------------------------------------------------
// OURS. The floating pill of our dashboards, in the upstream pill's clothes:
// the fund type on the left, the quick period in the middle (the SAME
// period state the upstream dashboards use, from DashboardProvider) and, on
// the right, the views of the module (Panel, Libro, Registro...). ContextPill
// mounts it on our routes instead of its own pill, so the page keeps one
// control at the top whatever the module.
//
// Which segments a view shows comes from lib/routes.js MODULES: a write
// view reads no fund or period and shows only the view switch.
// ---------------------------------------------------------------------------
'use client';

import { Fragment, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { apiGet } from '../lib/api';
import { moduleOf, viewOf } from '../lib/routes';
import { useDashboard } from './DashboardProvider';
import { DEFAULT_FUND, useModule } from './ModuleContext';

export default function ModulePill() {
  const d = useDashboard();
  const m = useModule();
  const router = useRouter();
  const path = usePathname();
  const [open, setOpen] = useState(null);   // 'fund' | 'view' | 'custom' | null
  const [tmpFrom, setTmpFrom] = useState('');
  const [tmpTo, setTmpTo] = useState('');
  const [funds, setFunds] = useState([0, 1, 2, 3]);
  const wrapRef = useRef(null);

  const module = moduleOf(path);
  const view = viewOf(path);
  const fundAll = !!view?.fundAll;

  // The fund types come from the SPP registry; the fallback is the usual four.
  useEffect(() => {
    apiGet('/api/spp/config').then((c) => { if (c.funds?.length) setFunds(c.funds); }).catch(() => {});
  }, []);

  // A view that cannot show every fund at once gets a fund type.
  useEffect(() => {
    if (view?.fund && !fundAll && m && m.fund === 'all') m.setFund(DEFAULT_FUND);
  }, [view, fundAll, m]);

  // dismiss any dropdown/popover on outside click or Escape
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(null); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(null); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);

  if (!d || !m || !module) return null;
  const showFund = !!view?.fund;
  const showPeriod = !!view?.period;
  const fundLabel = m.fund === 'all' ? 'Todos los fondos' : `Fondo ${m.fund}`;
  const allPeriods = [...d.periods, 'Custom'];

  const onPeriod = (p) => {
    if (p === 'Custom') {
      setTmpFrom(d.customFrom || d.range.from);
      setTmpTo(d.customTo || d.range.to);
      setOpen('custom');
      return;
    }
    d.setPeriod(p);
    setOpen(null);
  };
  const applyCustom = () => {
    if (tmpFrom) d.setCustomFrom(tmpFrom);
    if (tmpTo) d.setCustomTo(tmpTo);
    setOpen(null);
  };

  return (
    <div className="pill-bar">
      <div className="pill-wrap" ref={wrapRef}>
        <div className="pill">
          {showFund && (
            <>
              <button type="button" className="pill-seg" onClick={() => setOpen(open === 'fund' ? null : 'fund')}>
                {fundLabel} <span className="pill-caret">▾</span>
              </button>
              <span className="pill-div" />
            </>
          )}

          {showPeriod && (
            <>
              <div className="pill-periods">
                {allPeriods.map((p, i) => (
                  <Fragment key={p}>
                    {i > 0 && <span className="pill-dot">·</span>}
                    <button type="button" className={`pill-period ${d.period === p ? 'on' : ''}`} onClick={() => onPeriod(p)}>{p}</button>
                  </Fragment>
                ))}
              </div>
              <span className="pill-div" />
            </>
          )}

          <button type="button" className="pill-seg" onClick={() => setOpen(open === 'view' ? null : 'view')}>
            {view?.label || module.label} <span className="pill-caret">▾</span>
          </button>
        </div>

        {open === 'fund' && showFund && (
          <div className="pill-dd pill-dd-left">
            {fundAll && (
              <button type="button" className={`pill-dd-item ${m.fund === 'all' ? 'on' : ''}`}
                onClick={() => { m.setFund('all'); setOpen(null); }}>
                Todos los fondos
              </button>
            )}
            {funds.map((f) => (
              <button key={f} type="button" className={`pill-dd-item ${m.fund === f ? 'on' : ''}`}
                onClick={() => { m.setFund(f); setOpen(null); }}>
                Fondo {f}
              </button>
            ))}
          </div>
        )}

        {open === 'view' && (
          <div className="pill-dd pill-dd-right">
            {module.views.map((v) => (
              <button key={v.href} type="button" className={`pill-dd-item ${view?.href === v.href ? 'on' : ''}`}
                onClick={() => { setOpen(null); router.push(v.href); }}>
                {v.label}
              </button>
            ))}
          </div>
        )}

        {open === 'custom' && showPeriod && (
          <div className="pill-pop">
            <div className="pill-pop-row">
              <div className="pill-pop-field">
                <label>Desde</label>
                <input type="date" className="date-input" value={tmpFrom} max={tmpTo || undefined} onChange={(e) => setTmpFrom(e.target.value)} />
              </div>
              <div className="pill-pop-field">
                <label>Hasta</label>
                <input type="date" className="date-input" value={tmpTo} min={tmpFrom || undefined} onChange={(e) => setTmpTo(e.target.value)} />
              </div>
            </div>
            <div className="pill-pop-actions">
              <button type="button" className="btn" onClick={() => setOpen(null)}>Cancelar</button>
              <button type="button" className="btn active" onClick={applyCustom}>Aplicar</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
