// web/apps/dashboards/lib/theme.js
// ---------------------------------------------------------------------------
// Chart theming bridge. Plotly is plain JS and can't read CSS custom properties,
// so chartTheme() pulls the live token values off <html> via getComputedStyle —
// keeping the CSS tokens the single source of truth. useThemeVersion() lets a
// chart re-read them (re-render) when the theme toggles.
// ---------------------------------------------------------------------------
import { useState, useEffect } from 'react';

// Dark fallback used during SSR/prerender (no document) and before hydration.
const DARK = { surface: '#1F1918', panel: '#181413', border: '#332A29', text: '#EDE8E8', muted: '#9A8F8F' };

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
