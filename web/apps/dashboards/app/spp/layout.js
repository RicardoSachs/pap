// web/apps/dashboards/app/spp/layout.js
// ---------------------------------------------------------------------------
// Wrapper of the Valor Cuota SPP tablero views.
//
// It exists for one reason: to load the tablero's stylesheets here and not in
// globals.css. They are only needed under /spp/, and mixing them into the base
// design system meant rescuing them by hand every time a new version of the
// interface arrived. Next injects them for every route anyway, but the
// SEPARATION is what matters: globals.css is replaced whole and this survives.
//
// Two sheets: the widgets shared by our dashboards (styles/widgets.css) and
// this tablero's own (spp.css).
// ---------------------------------------------------------------------------
import '../styles/widgets.css';
import './spp.css';

export default function SppLayout({ children }) {
  return children;
}
