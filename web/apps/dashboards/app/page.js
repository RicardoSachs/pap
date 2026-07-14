
// web/apps/dashboards/app/page.js
import Link from 'next/link';

const CARDS = [
  { href: '/prices/', title: 'Price Viewer', desc: 'Compare a security’s price history across sources.' },
  { href: '/positioning/', title: 'Positioning', desc: 'Portfolio holdings with weights and breakdowns.' },
  { href: '/contribution/', title: 'Contribution', desc: 'Per-holding contribution to portfolio return.' },
];

export default function Home() {
  return (
    <div>
      <h1 className="page-title">Profuturo Analytics</h1>
      <p className="page-sub">Investment analytics dashboards — reference data.</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14 }}>
        {CARDS.map((c) => (
          <Link key={c.href} href={c.href} className="panel" style={{ display: 'block' }}>
            <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 6, color: 'var(--blue)' }}>
              {c.title}
            </div>
            <div className="muted">{c.desc}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}

