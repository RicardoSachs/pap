// web/apps/dashboards/lib/period.js
// ---------------------------------------------------------------------------
// Period quick-select -> concrete {from, to} ISO date range. Computed relative
// to "today" on the client. The API snaps to the nearest available data.
// ---------------------------------------------------------------------------
export const PERIODS = ['1M', '3M', 'YTD', '1Y'];
export const DEFAULT_PERIOD = 'YTD';

function iso(d) {
  return d.toISOString().slice(0, 10);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// 'YYYY-MM-DD' -> '01 Jan 2026' (parsed by parts to avoid timezone drift).
export function fmtDisplay(isoDate) {
  if (!isoDate) return '';
  const [y, m, dd] = isoDate.split('-');
  return `${dd} ${MONTHS[Number(m) - 1]} ${y}`;
}

export function periodToRange(period, asOf = new Date()) {
  const to = new Date(asOf);
  let from = new Date(to);
  switch (period) {
    case '1M': from.setMonth(from.getMonth() - 1); break;
    case '3M': from.setMonth(from.getMonth() - 3); break;
    case '1Y': from.setFullYear(from.getFullYear() - 1); break;
    case 'YTD':
    default: from = new Date(to.getFullYear(), 0, 1); break;
  }
  return { from: iso(from), to: iso(to) };
}
