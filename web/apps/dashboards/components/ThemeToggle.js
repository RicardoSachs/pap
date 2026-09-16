// web/apps/dashboards/components/ThemeToggle.js
// ---------------------------------------------------------------------------
// Dark/light theme toggle — a small floating pill (top-right) matching the
// floating context pill's design language. Reads the current theme on mount (set
// pre-paint by the inline script in layout.js), flips data-theme on <html>,
// persists to localStorage('theme'), and dispatches 'themechange' so charts
// re-read tokens. Label shows the mode you'll switch TO.
// ---------------------------------------------------------------------------
'use client';

import { useState, useEffect } from 'react';

export default function ThemeToggle() {
  const [theme, setTheme] = useState('dark');

  useEffect(() => {
    let t = 'dark';
    try { t = localStorage.getItem('theme') || document.documentElement.getAttribute('data-theme') || 'dark'; } catch { /* ignore */ }
    setTheme(t);
    document.documentElement.setAttribute('data-theme', t);
  }, []);

  function toggle() {
    setTheme((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('theme', next); } catch { /* ignore */ }
      document.documentElement.setAttribute('data-theme', next);
      window.dispatchEvent(new Event('themechange'));
      return next;
    });
  }

  const isDark = theme === 'dark';
  return (
    <button
      className="theme-pill"
      onClick={toggle}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {isDark ? 'Light mode' : 'Dark mode'}
    </button>
  );
}
