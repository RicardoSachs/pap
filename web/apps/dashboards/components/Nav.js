
// web/apps/dashboards/components/Nav.js
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { rutaActiva } from '../lib/rutas';

const LINKS = [
  { href: '/prices/', label: 'Price Viewer' },
  { href: '/positioning/', label: 'Positioning' },
  { href: '/contribution/', label: 'Contribution' },
  { href: '/spp/', label: 'Valor Cuota SPP' },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="nav">
      <span className="brand">Portfolio Analytics</span>
      {LINKS.map((l) => {
        const active = rutaActiva(path, l.href);
        return (
          <Link key={l.href} href={l.href} className={active ? 'active' : ''}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}

