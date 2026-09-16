// web/apps/dashboards/components/Header.js
// ---------------------------------------------------------------------------
// Minimal global header bar: brand (left) + theme toggle (right). All dashboard
// context controls (fund / period / source) live in the floating ContextPill
// below the bar; their state still lives in DashboardProvider.
// ---------------------------------------------------------------------------
'use client';

import ThemeToggle from './ThemeToggle';

export default function Header() {
  return (
    <header className="header">
      <div className="spacer" />
      <ThemeToggle />
    </header>
  );
}
