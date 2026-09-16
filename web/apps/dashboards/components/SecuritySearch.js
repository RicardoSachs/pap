// web/apps/dashboards/components/SecuritySearch.js
// ---------------------------------------------------------------------------
// Server-side typeahead security picker. Queries /api/securities?search=&limit=
// as the user types (debounced), so it scales to a DB of any size — only matches
// are fetched, never the whole universe. On mount it loads the top N and
// auto-selects the first so the chart isn't empty.
//
// UI: "Security" label, ticker/name + ISIN per row, match highlighting, focus-open
// dropdown, a "no results" message, a hint line, and a × clear button.
//
// Props:
//   value     selected security { entity_id, display_name, ticker, isin } | null
//   onSelect  called with the chosen security, or null when cleared
//   limit     max matches fetched per query (default 50 — do not change)
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';
import { apiGet } from '../lib/api';

const HINT = 'e.g. AAPL US, EWY US, BGFPABA LN';

const label = (s) => `${s.ticker ? `${s.ticker} ` : ''}${s.display_name}`;

// Wrap the first case-insensitive match of `term` in `text` with a highlight span.
function highlight(text, term) {
  if (!term) return text;
  const i = text.toLowerCase().indexOf(term.toLowerCase());
  if (i < 0) return text;
  return (
    <>
      {text.slice(0, i)}
      <span className="combo-hl">{text.slice(i, i + term.length)}</span>
      {text.slice(i + term.length)}
    </>
  );
}

// `autoSelectFirst` (default true) auto-picks the top result on mount so a chart
// loads non-empty; the Comparación add-picker passes false so opening it doesn't
// silently add a security.
export default function SecuritySearch({ value, onSelect, limit = 50, autoSelectFirst = true }) {
  const [query, setQuery] = useState('');   // text shown in the input
  const [term, setTerm] = useState('');     // search string behind the current results (for highlight)
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const debounce = useRef(null);
  const didInit = useRef(false);
  const typing = useRef(false);

  // keep the input text in sync with the externally-selected value (unless the user is typing)
  useEffect(() => {
    if (value && !typing.current) setQuery(label(value));
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  // initial load: top N + auto-select the first (once)
  useEffect(() => {
    apiGet(`/api/securities?limit=${limit}`)
      .then((rows) => {
        setResults(rows);
        if (autoSelectFirst && !didInit.current && !value && rows.length) { didInit.current = true; onSelect(rows[0]); }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // close the dropdown on outside click
  useEffect(() => {
    const onDoc = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  function runSearch(q) {
    const t = q.trim();
    const qs = t ? `search=${encodeURIComponent(t)}&limit=${limit}` : `limit=${limit}`;
    apiGet(`/api/securities?${qs}`)
      .then((rows) => { setResults(rows); setTerm(t); setActive(0); setOpen(true); })
      .catch(() => {});
  }

  function onChange(e) {
    const q = e.target.value;
    typing.current = true;
    setQuery(q);
    setOpen(true);
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => runSearch(q), 250);
  }

  function choose(s) {
    typing.current = false;
    onSelect(s);
    setQuery(label(s));
    setOpen(false);
  }

  function clear() {
    typing.current = false;
    setQuery('');
    setTerm('');
    onSelect(null);
    runSearch('');     // refresh back to the top-N
    setOpen(true);
  }

  function onKeyDown(e) {
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter')) { setOpen(true); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(i + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); if (results[active]) choose(results[active]); }
    else if (e.key === 'Escape') { setOpen(false); }
  }

  return (
    <div className="field" ref={boxRef}>
      <span className="combo-label">Security</span>
      <div className="combo">
        <input
          type="text"
          className="combo-field"
          value={query}
          placeholder="Search by ticker, name, or ISIN..."
          onChange={onChange}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          aria-label="Security search"
          autoComplete="off"
        />
        {value && (
          <button type="button" className="combo-clear" onClick={clear} title="Clear" aria-label="Clear selection">×</button>
        )}
        {open && (
          <div className="combo-results">
            {results.length ? (
              results.map((s, i) => (
                <div
                  key={s.entity_id}
                  className={`combo-item ${i === active ? 'active' : ''}`}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => { e.preventDefault(); choose(s); }}
                >
                  <div className="combo-line1">{highlight(label(s), term)}</div>
                  {s.isin && <div className="combo-isin">{highlight(s.isin, term)}</div>}
                </div>
              ))
            ) : (
              <div className="combo-empty">No securities found for this search</div>
            )}
          </div>
        )}
      </div>
      {!value && <div className="combo-hint">{HINT}</div>}
    </div>
  );
}
