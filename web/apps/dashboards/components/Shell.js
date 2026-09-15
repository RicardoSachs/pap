// web/apps/dashboards/components/Shell.js
// ---------------------------------------------------------------------------
// App chrome: fixed header + floating sidebar + full-width main content area.
// The sidebar floats over the content (it no longer participates in the layout,
// so the main area is full width). Owns the sidebar expanded/collapsed state
// (persisted to localStorage); clicking the content collapses an open sidebar.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import Sidebar from './Sidebar';
import ContextPill from './ContextPill';
import ThemeToggle from './ThemeToggle';

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

  // Clicking the content area collapses an expanded (overlaying) sidebar.
  const collapse = () => {
    setExpanded(false);
    try { localStorage.setItem(LS_KEY, '0'); } catch { /* ignore */ }
  };

  return (
    <>
      <Sidebar expanded={expanded} onToggle={toggle} />
      <ThemeToggle />
      <main className={`main ${expanded ? 'exp' : ''}`} onClick={() => { if (expanded) collapse(); }}>
        <ContextPill />
        {children}
      </main>
    </>
  );
}
