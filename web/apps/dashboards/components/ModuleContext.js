// web/apps/dashboards/components/ModuleContext.js
// ---------------------------------------------------------------------------
// OURS. The context our dashboards share through the floating pill: the fund
// type in view. The period comes from DashboardProvider (the same quick
// select the upstream dashboards use), the view is the route itself; the
// fund is the one thing the upstream context has no place for, so it lives
// here, persisted in localStorage like the rest of the pill's state.
//
// `fund` is a fund type (0..3) or 'all' on the views that can show every
// fund at once (the books, the Tradebook); the pill corrects it to a fund
// type when the view cannot (lib/routes.js says which can).
// ---------------------------------------------------------------------------
'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';

const Ctx = createContext(null);
export const useModule = () => useContext(Ctx);

const LS_KEY = 'profuturo.module';
export const DEFAULT_FUND = 2;

export default function ModuleProvider({ children }) {
  const [fund, setFundState] = useState(DEFAULT_FUND);

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
      if (stored.fund === 'all' || Number.isInteger(stored.fund)) setFundState(stored.fund);
    } catch { /* ignore */ }
  }, []);

  const setFund = useCallback((v) => {
    setFundState(v);
    try { localStorage.setItem(LS_KEY, JSON.stringify({ fund: v })); } catch { /* ignore */ }
  }, []);

  return <Ctx.Provider value={{ fund, setFund }}>{children}</Ctx.Provider>;
}
