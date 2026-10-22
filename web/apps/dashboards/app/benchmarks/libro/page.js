// web/apps/dashboards/app/benchmarks/libro/page.js
// ---------------------------------------------------------------------------
// Benchmarks · Libro: one index's levels day by day, over the SAME date grid
// as the valor cuota book, because the question it answers is "which days
// is the index missing": listing only the days it has would hide exactly
// what one is looking for. One book at a time, with the XLSX of the whole
// series.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import { apiGet } from '../../../lib/api';
import { apiUrl, fDate, nInt } from '../../../lib/spp';
import { useModule } from '../../../components/ModuleContext';
import SppSeg from '../../../components/SppSeg';

// 0 asks the API for the whole book.
const LIMITS = [['60', 60], ['250', 250], ['1000', 1000], ['Todas', 0]];

export default function BenchmarksLibroPage() {
  const [list, setList] = useState(null);
  const [selected, setSelected] = useState('');
  const [limit, setLimit] = useState(60);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet('/api/benchmarks').then((j) => {
      const items = j.benchmarks || [];
      setList(items);
      setSelected((s) => s || items.find((b) => b.points)?.procode || items[0]?.procode || '');
    }).catch((e) => setError(e.message));
  }, []);

  // The pill's fund narrows the books to the indices assigned to it
  // ('all' = every one); the selection stays inside it.
  const pill = useModule();
  const pillFund = pill?.fund ?? 'all';
  const visible = (list || []).filter((b) => pillFund === 'all' || b.fund === pillFund);
  useEffect(() => {
    if (list && !visible.some((b) => b.procode === selected)) {
      setSelected(visible.find((b) => b.points)?.procode || visible[0]?.procode || '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, pillFund]);

  useEffect(() => {
    if (!selected) return undefined;
    setLoading(true); setError(null);
    let current = true;
    apiGet(`/api/benchmarks/${encodeURIComponent(selected)}/table?${new URLSearchParams({ limit })}`)
      .then((d) => { if (current) setData(d); })
      .catch((e) => { if (current) setError(e.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [selected, limit]);

  const bench = (list || []).find((b) => b.procode === selected) || null;
  const columns = data?.columns || [];
  const rows = data?.rows || [];
  const missing = data?.missing || 0;

  return (
    <div className="bm-page">
      <h1 className="page-title">Benchmarks</h1>
      <p className="page-sub">
        Libro de {bench?.display_name || '—'} · {rows.length
          ? (missing ? `${nInt(rows.length)} fechas · ${nInt(missing)} sin nivel` : `${nInt(rows.length)} fechas · sin huecos`)
          : '—'}
      </p>
      <div className="panel">
        <div className="controls spp-controls">
          <div className="field"><label>Benchmark{pillFund === 'all' ? '' : ` · Fondo ${pillFund}`}</label>
            {visible.length
              ? <SppSeg items={visible.map((b) => [b.display_name, b.procode])} value={selected} onChange={setSelected} />
              : <span className="dim">Ningún benchmark vinculado a este fondo.</span>}</div>
          <div className="field"><label>Filas</label>
            <SppSeg items={LIMITS} value={limit} onChange={setLimit} /></div>
          <div className="field"><label aria-hidden="true">&nbsp;</label>
            {selected && (
              <a className="btn" href={apiUrl(`/api/benchmarks/${encodeURIComponent(selected)}/export`)}>
                ↓ Bajar la serie · XLSX</a>
            )}</div>
        </div>
        <p className="page-sub dim" style={{ marginTop: 10, marginBottom: 0 }}>
          Las fechas son las del libro de valor cuota: así un día sin nivel se ve como un hueco
          en vez de desaparecer de la lista. El nivel lo produce el recálculo de la canasta,
          en <b>Registro</b>.
        </p>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      <div className="panel">
        {loading ? <div className="loading">Cargando…</div> : (
          <div className="table-wrap spp-windows">
            <table>
              <thead>
                <tr><th>Fecha</th>{columns.map((c) => <th key={c.col} className="num">{c.label}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.date}>
                    <td>{fDate(r.date)}</td>
                    {r.values.map((v, i) => (
                      <td key={columns[i]?.col || i} className={`num ${v == null ? 'dim' : ''}`}>
                        {/* Index levels: never abbreviated. */}
                        {v == null ? '—' : Number(v).toLocaleString('es-PE',
                          { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                      </td>
                    ))}
                  </tr>
                ))}
                {!rows.length && (
                  <tr><td colSpan={columns.length + 1} className="dim">
                    {list && !list.length ? 'Ningún benchmark declarado.' : 'No hay fechas en el libro todavía.'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
