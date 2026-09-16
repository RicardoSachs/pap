// web/apps/dashboards/components/SortableTable.js
// ---------------------------------------------------------------------------
// Small client-side sortable table. Columns: {key, label, align, render, sortable}.
// Click a header to sort; click again to flip direction.
// ---------------------------------------------------------------------------
'use client';

import { useState, useMemo } from 'react';

export default function SortableTable({ columns, rows, initialSort, initialDir = 'desc' }) {
  const [sortKey, setSortKey] = useState(initialSort || columns[0]?.key);
  const [dir, setDir] = useState(initialDir);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      const cmp = typeof va === 'number' && typeof vb === 'number'
        ? va - vb
        : String(va).localeCompare(String(vb));
      return dir === 'asc' ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, dir]);

  function toggle(key) {
    if (key === sortKey) {
      setDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setDir('desc');
    }
  }

  return (
    <table>
      <thead>
        <tr>
          {columns.map((c) => (
            <th
              key={c.key}
              onClick={() => c.sortable !== false && toggle(c.key)}
              style={{ textAlign: c.align || 'right', cursor: c.sortable === false ? 'default' : 'pointer' }}
            >
              {c.label}
              {sortKey === c.key ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((row, i) => (
          <tr key={row.__key ?? i}>
            {columns.map((c) => (
              <td key={c.key} className={c.className} style={{ textAlign: c.align || 'right' }}>
                {c.render ? c.render(row[c.key], row) : row[c.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
