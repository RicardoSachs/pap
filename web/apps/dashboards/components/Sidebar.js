
// web/apps/dashboards/components/Sidebar.js
// ---------------------------------------------------------------------------
// Collapsible text-only sidebar. 48px collapsed (active items still show their
// blue left border), expands to 200px on hover or via the toggle (persisted in
// localStorage by Shell). Active page gets a blue left border. Future tools are
// shown at 30% opacity with a "Coming soon" tooltip (not clickable). Nav links
// carry the current query so the dashboard context sticks across pages.
// ---------------------------------------------------------------------------
'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';

const ITEMS = [
  { href: '/prices/', label: 'Prices' },
  { href: '/positioning/', label: 'Positioning' },
  { href: '/contribution/', label: 'Contribution' },
];
const SOON = ['Attribution', 'Risk'];

export default function Sidebar({ expanded, onToggle }) {
  const path = usePathname();
  const params = useSearchParams();
  const qs = params.toString();
  const q = qs ? `?${qs}` : '';
  const isActive = (href) => path === href || path === href.replace(/\/$/, '');

  return (
    <aside className={`sidebar ${expanded ? 'expanded' : ''}`}>
      <button className="side-toggle" onClick={onToggle} aria-label="Toggle sidebar"
        title={expanded ? 'Collapse' : 'Expand'}>
        <span className="icon">{expanded ? '«' : '☰'}</span>
        <span className="label">Collapse</span>
      </button>

      {ITEMS.map((it) => (
        <Link key={it.href} href={`${it.href}${q}`} className={`side-item ${isActive(it.href) ? 'active' : ''}`}>
          <span className="label">{it.label}</span>
        </Link>
      ))}

      <div className="side-sep" />

      {SOON.map((label) => (
        <div key={label} className="side-item soon" title="Coming soon" aria-disabled="true">
          <span className="label">{label}</span>
        </div>
      ))}
    </aside>
  );
}

