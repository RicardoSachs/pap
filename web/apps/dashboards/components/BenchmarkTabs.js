// web/apps/dashboards/components/BenchmarkTabs.js
// ---------------------------------------------------------------------------
// Sub-tab bar of the Benchmarks module: one sidebar entry (/benchmarks/)
// fans out into its views, each its own statically-exported route. Same role
// as SppTabs; a separate component because the two modules change on their
// own schedule.
// ---------------------------------------------------------------------------
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const TABS = [
  { href: '/benchmarks/', label: 'Panel' },
  { href: '/benchmarks/libro/', label: 'Libro' },
  { href: '/benchmarks/series/', label: 'Series' },
  { href: '/benchmarks/registro/', label: 'Registro' },
];

export default function BenchmarkTabs() {
  const path = usePathname();
  const isActive = (href) => path === href || path === href.replace(/\/$/, '');
  return (
    <div className="spp-tabs">
      {TABS.map((t) => (
        <Link key={t.href} href={t.href}
          className={`spp-tab ${isActive(t.href) ? 'active' : ''}`}>
          {t.label}
        </Link>
      ))}
    </div>
  );
}
