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

// OURS. Our dashboards, the ones that do not exist upstream.
//
// The adopted design system brings two pieces that assume every page is
// one of its dashboards: the context pill (portfolio, dates, source) and
// the sync of those filters with the URL. Neither makes sense here, and the
// sync also rewrote the page's URL.
//
// Listed in ONE place so a third module does not require touching two
// upstream components again, where every patch of ours has to be reapplied
// on the next update.
const OURS = ['/spp/', '/tradebook/'];
export const isOurDashboard = (path) =>
  OURS.some((base) => activeRoute(path, base));
