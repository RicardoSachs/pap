
// web/apps/dashboards/components/SppTabs.js
// ---------------------------------------------------------------------------
// Sub-tab bar of the SPP tablero: one sidebar entry (/spp/) fans out into the
// monitor's views, each its own statically-exported route.
// ---------------------------------------------------------------------------
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const TABS = [
  { href: '/spp/', label: 'Panel' },
  { href: '/spp/libro/', label: 'Libro' },
  { href: '/spp/carga/', label: 'Registro y carga' },
  { href: '/spp/bloomberg/', label: 'Bloomberg' },
];

export default function SppTabs() {
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
