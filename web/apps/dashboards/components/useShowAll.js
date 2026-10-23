// web/apps/dashboards/components/useShowAll.js
// ---------------------------------------------------------------------------
// Expand / collapse a long list, instead of boxing it with a scrollbar of
// its own.
//
// Our panels have no inner scroll: they grow with their content and the
// page is what scrolls. So that a long list does not push everything else
// out of view, a cap is shown and this control says how many are missing
// and brings them.
//
//   const [visible, ShowAll] = useShowAll(rows, 12);
//   ...render `visible`...
//   <ShowAll label="dates" />
// ---------------------------------------------------------------------------
'use client';

import { useState } from 'react';
import { nInt } from '../lib/spp';

export default function useShowAll(items, cap = 12) {
  const [all, setAll] = useState(false);
  const list = items || [];
  const visible = all ? list : list.slice(0, cap);

  const ShowAll = ({ label = 'rows', style }) => {
    if (list.length <= cap) return null;
    return (
      <div className="controls" style={{ marginTop: 10, ...style }}>
        <button className="btn" onClick={() => setAll((v) => !v)}>
          {all
            ? `Collapse to ${nInt(cap)}`
            : `Show all ${nInt(list.length)} ${label} · ${nInt(list.length - cap)} more`}
        </button>
      </div>
    );
  };

  return [visible, ShowAll, all];
}
