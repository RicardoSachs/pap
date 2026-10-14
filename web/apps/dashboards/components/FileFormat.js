// web/apps/dashboards/components/FileFormat.js
// ---------------------------------------------------------------------------
// NUESTRO. The help icon next to every upload field, and the window it
// opens with the format that site expects.
//
// It shows the TABLE and nothing else: the headers and one example row.
// That is the format; describing each column with a paragraph repeated in
// words what the row already shows, and the window needed a scroll to say
// less.
//
// The columns come from /api/formats/{key}, derived from the SAME constants
// the reader parses with. Writing them here by hand would have been shorter
// and would have started lying the day someone adds a column alias.
//
// Fetched on open, not on mount: there are four forms on screen and almost
// nobody opens all four.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';

import { apiGet } from '../lib/api';
import { apiUrl } from '../lib/spp';

export default function FileFormat({ formatKey, label = 'Ver el formato' }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const box = useRef(null);

  useEffect(() => {
    if (!open || data) return;
    apiGet(`/api/formats/${formatKey}`).then(setData)
      .catch((e) => setError(e.message));
  }, [open, formatKey, data]);

  // Escape and a click outside close it. A modal that only closes with its
  // own cross is the one that ends up trapping the operator.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    const onPress = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onPress);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onPress);
    };
  }, [open]);

  return (
    <>
      <button type="button" className="fmt-icono" title={label}
        aria-label={label} aria-haspopup="dialog" aria-expanded={open}
        onClick={() => setOpen((v) => !v)}>
        {/* A drawn table: it says "this is what the file looks like"
            without a word, and is not confused with the general help "?". */}
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none"
          stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
          <rect x="1.7" y="2.7" width="12.6" height="10.6" rx="1.4" />
          <path d="M1.7 6.2h12.6M6.2 6.2v7.1M10.3 6.2v7.1" />
        </svg>
      </button>

      {open && (
        <div className="fmt-fondo" role="dialog" aria-modal="true"
          aria-label={data?.title || label}>
          <div className="fmt-ventana" ref={box}>
            <div className="fmt-cabecera">
              <div className="fmt-titulo">{data?.title || 'Formato del archivo'}</div>
              <button type="button" className="fmt-cerrar" aria-label="Cerrar"
                onClick={() => setOpen(false)}>×</button>
            </div>

            {error && <p className="fmt-resumen neg">No se pudo leer el formato: {error}</p>}
            {!data && !error && <div className="loading">Cargando…</div>}

            {data && (
              <div className="fmt-cuerpo">
                {data.columns.length ? (
                  <>
                    {/* The table IS the answer: one example row under the
                        headers says the whole format at a glance. */}
                    <div className="table-wrap fmt-ejemplo">
                      <table>
                        <thead><tr>
                          {data.columns.map((c) => (
                            <th key={c.name}>
                              {c.name}{c.required && <span className="fmt-req">*</span>}
                            </th>
                          ))}
                        </tr></thead>
                        <tbody><tr>
                          {data.columns.map((c) => (
                            <td key={c.name}>{c.example || <span className="dim">—</span>}</td>
                          ))}
                        </tr></tbody>
                      </table>
                    </div>
                    <p className="fmt-pie">
                      <span className="fmt-req">*</span> obligatoria. El orden de
                      las columnas da igual y las que no se reconozcan se ignoran.
                    </p>
                  </>
                ) : (
                  /* No table to show - it is someone else's sheet, the SBS's -
                     so it has to be said in words or the icon would open empty. */
                  <ul className="fmt-notas">
                    {(data.notes || []).map((n) => <li key={n}>{n}</li>)}
                  </ul>
                )}

                {data.template && (
                  <a className="btn principal" href={apiUrl(data.template)}
                    style={{ marginTop: 4, display: 'inline-block' }}>
                    ↓ Bajar la plantilla · XLSX
                  </a>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
