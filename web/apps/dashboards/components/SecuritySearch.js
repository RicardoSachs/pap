
// web/apps/dashboards/components/SecuritySearch.js
// ---------------------------------------------------------------------------
// Server-side typeahead security picker. Queries /api/securities?search=&limit=
// as the user types (debounced), so it scales to a DB of any size — only the
// matches are fetched, never the whole universe. On mount it loads the top N
// and auto-selects the first so the chart isn't empty (preserves prior behavior).
//
// Props:
//   value     selected security { entity_id, display_name, ticker } | null
//   onSelect  called with the chosen security object
//   limit     max matches fetched per query (default 50)
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';
import { apiGet } from '../lib/api';

export default function SecuritySearch({ value, onSelect, limit = 50 }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);   // highlighted row for keyboard nav
  const boxRef = useRef(null);
  const debounce = useRef(null);
  const didInit = useRef(false);

  const label = (s) => `${s.display_name}${s.ticker ? ` (${s.ticker})` : ''}`;

  // keep the input text in sync with the externally-selected value
  useEffect(() => {
    if (value) setQuery(label(value));
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  // initial load: top N + auto-select first (only once)
  useEffect(() => {
    apiGet(`/api/securities?limit=${limit}`)
      .then((rows) => {
        setResults(rows);
        if (!didInit.current && !value && rows.length) {
          didInit.current = true;
          onSelect(rows[0]);
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // close the dropdown on outside click
  useEffect(() => {
    const onDocClick = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  function runSearch(q) {
    const qs = q.trim() ? `search=${encodeURIComponent(q.trim())}&limit=${limit}` : `limit=${limit}`;
    apiGet(`/api/securities?${qs}`)
      .then((rows) => { setResults(rows); setActive(0); setOpen(true); })
      .catch(() => {});
  }

  function onChange(e) {
    const q = e.target.value;
    setQuery(q);
    setOpen(true);
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => runSearch(q), 250);
  }

  function choose(s) {
    onSelect(s);
    setQuery(label(s));
    setOpen(false);
  }

  function onKeyDown(e) {
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter')) { setOpen(true); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(i + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); if (results[active]) choose(results[active]); }
    else if (e.key === 'Escape') { setOpen(false); }
  }

  return (
    <div className="combo" ref={boxRef}>
      <input
        type="text"
        className="select"
        style={{ minWidth: 300 }}
        value={query}
        placeholder="Search name / ticker / ISIN…"
        onChange={onChange}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        aria-label="Security search"
        autoComplete="off"
      />
      {open && results.length > 0 && (
        <div className="combo-results">
          {results.map((s, i) => (
            <div
              key={s.entity_id}
              className={`combo-item ${i === active ? 'active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); choose(s); }}
            >
              <span>{s.display_name}</span>
              <span className="combo-meta">{s.ticker || s.isin || ''}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

