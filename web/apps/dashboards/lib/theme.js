
// web/apps/dashboards/lib/theme.js
// ---------------------------------------------------------------------------
// Chart theming bridge. Plotly is plain JS and can't read CSS custom properties,
// so chartTheme() pulls the live token values off <html> via getComputedStyle —
// keeping the CSS tokens the single source of truth. useThemeVersion() lets a
// chart re-read them (re-render) when the theme toggles.
// ---------------------------------------------------------------------------
import { useState, useEffect } from 'react';

// Dark fallback used during SSR/prerender (no document) and before hydration.
const DARK = { surface: '#1C2030', panel: '#141720', border: '#2E3348', text: '#E8EAF0', muted: '#8892A4',
  positive: '#2DD4A0', negative: '#F06580', brand: '#5B8CFF',
};

export function chartTheme() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return DARK;
  const cs = getComputedStyle(document.documentElement);
  const v = (name, fallback) => (cs.getPropertyValue(name).trim() || fallback);
  return {
    surface: v('--s2', DARK.surface),
    panel: v('--s1', DARK.panel),
    border: v('--s4', DARK.border),
    text: v('--text-primary', DARK.text),
    muted: v('--text-secondary', DARK.muted),
    // NUESTRO: Plotly no resuelve var(--x) en marker.color ni line.color; se
    // queda con su paleta por defecto. Se le da el valor ya resuelto, leido de
    // los tokens de esta hoja: teal, rose y blue.
    positive: v('--teal', DARK.positive),
    negative: v('--rose', DARK.negative),
    brand: v('--blue', DARK.brand),
  };
}

// Bumps on mount (so the first client render reads real CSS vars) and whenever
// ThemeToggle dispatches a 'themechange' event.
export function useThemeVersion() {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const handler = () => setVersion((x) => x + 1);
    window.addEventListener('themechange', handler);
    setVersion((x) => x + 1);
    return () => window.removeEventListener('themechange', handler);
  }, []);
  return version;
}

