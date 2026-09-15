
// web/apps/dashboards/lib/rutas.js
// ---------------------------------------------------------------------------
// The ONE active-route matcher, shared by Nav and Sidebar so the two
// indicators can never disagree on sub-routes. Prefix match with a segment
// boundary: '/spp/' is active on '/spp/libro', but '/s' never matches '/spp'
// and sibling prefixes never light together.
// ---------------------------------------------------------------------------
export const rutaActiva = (path, href) => {
  const base = href.replace(/\/$/, '');
  // La raiz es el caso limite: su base queda vacia, y un prefijo vacio
  // coincide con TODO - el Home del menu se encendia en cada pagina.
  if (!base) return path === '/' || path === '';
  return path === href || path === base || path.startsWith(`${base}/`);
};
