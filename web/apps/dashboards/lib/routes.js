// web/apps/dashboards/lib/routes.js
// ---------------------------------------------------------------------------
// The ONE active-route matcher, shared by Nav and Sidebar so the two
// indicators can never disagree on sub-routes. Prefix match with a segment
// boundary: '/spp/' is active on '/spp/libro', but '/s' never matches '/spp'
// and sibling prefixes never light together.
// ---------------------------------------------------------------------------
export const activeRoute = (path, href) => {
  const base = href.replace(/\/$/, '');
  // The root is the edge case: its base is empty, and an empty prefix
  // matches EVERYTHING - the menu's Home lit up on every page.
  if (!base) return path === '/' || path === '';
  return path === href || path === base || path.startsWith(`${base}/`);
};

// OURS. Our dashboards, the ones that do not exist upstream: the sidebar
// entry of each, its views, and which controls of the floating pill each
// view uses (`fund`: the fund type on the left; `fundAll`: that view can
// show every fund at once; `period`: the quick period in the middle). A
// view with neither shows only the view switch.
//
// Listed in ONE place: the pill, the upstream pill's bypass and the URL
// sync all read it, so a third module or a new view touches nothing
// upstream.
export const MODULES = [
  { base: '/spp/', label: 'Valor Cuota SPP', views: [
    { href: '/spp/', label: 'Panel', fund: true, period: true },
    { href: '/spp/libro/', label: 'Libro', fund: true, fundAll: true },
    { href: '/spp/carga/', label: 'Registro y carga' },
  ] },
  { base: '/benchmarks/', label: 'Benchmarks', views: [
    { href: '/benchmarks/', label: 'Panel', fund: true, fundAll: true, period: true },
    { href: '/benchmarks/libro/', label: 'Libro', fund: true, fundAll: true },
    { href: '/benchmarks/registro/', label: 'Registro' },
  ] },
  { base: '/tradebook/', label: 'Tradebook', views: [
    { href: '/tradebook/', label: 'Panel', fund: true, fundAll: true, period: true },
    { href: '/tradebook/carga/', label: 'Registro y carga' },
  ] },
];

const trimSlash = (href) => href.replace(/\/$/, '');
export const moduleOf = (path) => MODULES.find((m) => activeRoute(path, m.base)) || null;
// Views are leaf routes: an exact match, with or without the trailing slash.
export const viewOf = (path) => {
  const m = moduleOf(path);
  return m ? (m.views.find((v) => path === v.href || path === trimSlash(v.href)) || null) : null;
};
export const isOurDashboard = (path) => moduleOf(path) !== null;
