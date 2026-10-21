// web/apps/dashboards/app/benchmarks/layout.js
// ---------------------------------------------------------------------------
// Wrapper of the Benchmarks module views. It loads the widgets our dashboards
// share (styles/widgets.css) here and not in globals.css, which stays
// verbatim as it comes from upstream; the module has no sheet of its own.
// ---------------------------------------------------------------------------
import '../styles/widgets.css';

export default function BenchmarksLayout({ children }) {
  return children;
}
