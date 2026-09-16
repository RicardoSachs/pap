
// web/apps/dashboards/components/Shell.js
// ---------------------------------------------------------------------------
// App chrome: fixed header + collapsible sidebar + main content area. Owns the
// sidebar expanded/collapsed state (persisted to localStorage) so the main
// content margin tracks it.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import Header from './Header';
import Sidebar from './Sidebar';

const LS_KEY = 'profuturo.sidebar';

export default function Shell({ children }) {
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    try { setExpanded(localStorage.getItem(LS_KEY) === '1'); } catch { /* ignore */ }
  }, []);

  const toggle = () =>
    setExpanded((e) => {
      const next = !e;
      try { localStorage.setItem(LS_KEY, next ? '1' : '0'); } catch { /* ignore */ }
      return next;
    });

  return (
    <>
      <Header />
      <Sidebar expanded={expanded} onToggle={toggle} />
      <main className={`main ${expanded ? 'exp' : ''}`}>{children}</main>
    </>
  );
}

