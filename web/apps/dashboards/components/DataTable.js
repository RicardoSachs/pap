// web/apps/dashboards/components/DataTable.js
// ---------------------------------------------------------------------------
// Enhanced table used across all dashboards:
//   - click-to-sort headers (sticky)
//   - [↓ CSV] export of the visible columns (uses col.csv accessor or raw value)
//   - [⚙ Columns] chooser to show/hide columns (persisted to localStorage)
//   - optional sticky total/portfolio row (tfoot)
//   - numeric columns right-aligned + monospace via col.numeric
//
// Column: { key, label, align, numeric, render, csv, sortable, defaultHidden, className }
// ---------------------------------------------------------------------------
'use client';

import { useState, useMemo, useEffect } from 'react';
import { downloadCsv } from '../lib/csv';

export default function DataTable({
  columns, rows, initialSort, initialDir = 'desc',
  totalRow, exportName = 'export', storageKey,
}) {
  const [sortKey, setSortKey] = useState(initialSort || columns[0]?.key);
  const [dir, setDir] = useState(initialDir);
  const [hidden, setHidden] = useState(() => new Set(columns.filter((c) => c.defaultHidden).map((c) => c.key)));
  const [chooser, setChooser] = useState(false);

  // restore hidden-columns preference
  useEffect(() => {
    if (!storageKey) return;
    try {
      const s = JSON.parse(localStorage.getItem(`cols.${storageKey}`) || 'null');
      if (Array.isArray(s)) setHidden(new Set(s));
    } catch { /* ignore */ }
  }, [storageKey]);

  function persist(next) {
    setHidden(next);
    if (storageKey) {
      try { localStorage.setItem(`cols.${storageKey}`, JSON.stringify([...next])); } catch { /* ignore */ }
    }
  }
  function toggleCol(key) {
    const n = new Set(hidden);
    n.has(key) ? n.delete(key) : n.add(key);
    persist(n);
  }

  const visible = columns.filter((c) => !hidden.has(c.key));
  const align = (c) => c.align || (c.numeric ? 'right' : 'left');
  const cellClass = (c) => [c.numeric ? 'num' : '', c.className || ''].join(' ').trim();

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const va = a[sortKey]; const vb = b[sortKey];
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      const cmp = (typeof va === 'number' && typeof vb === 'number')
        ? va - vb : String(va).localeCompare(String(vb));
      return dir === 'asc' ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, dir]);

  function toggleSort(c) {
    if (c.sortable === false) return;
    if (c.key === sortKey) setDir((dd) => (dd === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(c.key); setDir('desc'); }
  }

  function exportCsv() {
    const headers = visible.map((c) => c.label);
    const data = sorted.map((r) => visible.map((c) => (c.csv ? c.csv(r[c.key], r) : r[c.key])));
    downloadCsv(exportName, headers, data);
  }

  return (
    <div>
      <div className="table-tools">
        <div />
        <div className="right">
          <button className="btn" onClick={exportCsv} title="Export visible rows as CSV">↓ CSV</button>
          <button className="btn" onClick={() => setChooser((v) => !v)} title="Show / hide columns">⚙ Columns</button>
          {chooser && (
            <div className="col-chooser">
              {columns.map((c) => (
                <label className="row" key={c.key}>
                  <input type="checkbox" checked={!hidden.has(c.key)} onChange={() => toggleCol(c.key)} />
                  {c.label}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {visible.map((c) => (
                <th key={c.key} onClick={() => toggleSort(c)}
                  style={{ textAlign: align(c), cursor: c.sortable === false ? 'default' : 'pointer' }}>
                  {c.label}{sortKey === c.key ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr key={row.__key ?? i}>
                {visible.map((c) => (
                  <td key={c.key} className={cellClass(c)} style={{ textAlign: align(c) }}>
                    {c.render ? c.render(row[c.key], row) : row[c.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          {totalRow && (
            <tfoot>
              <tr>
                {visible.map((c, idx) => (
                  <td key={c.key} className={cellClass(c)} style={{ textAlign: align(c) }}>
                    {totalRow[c.key] !== undefined ? totalRow[c.key] : (idx === 0 ? 'Total' : '')}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
