// web/apps/dashboards/app/spp/libro/page.js
// ---------------------------------------------------------------------------
// SPP tablero · Libro: the stored series, day by day.
//
// Two books, one on screen at a time: the AFPs' valor cuota (filtered by
// metric / fund / row count, with a CSV of exactly what is shown), and the
// benchmark. They are separate tables on purpose - side by side they would
// be one wide grid where neither reads well.
//
// The benchmark table is laid over the SAME date grid as the book, because
// the question it answers is "which days is the benchmark missing": listing
// only the days it has would hide exactly what one is looking for.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import { apiGet } from '../../../lib/api';
import { apiUrl, fFecha, fmtMetrica, metricasDe, nEnt, nombreMetrica } from '../../../lib/spp';
import SppSeg from '../../../components/SppSeg';
import SppTabs from '../../../components/SppTabs';

const LIMITES = [['60', '60'], ['250', '250'], ['1000', '1000'], ['Todas', 'todas']];
const LIBROS = [['Valor cuota', 'vc'], ['Benchmark', 'benchmark']];

export default function SppLibroPage() {
  const [cfg, setCfg] = useState(null);
  const [libro, setLibro] = useState('vc');
  const [metrica, setMetrica] = useState('valor_cuota');
  const [fondo, setFondo] = useState('todos');
  const [limite, setLimite] = useState('60');
  const [data, setData] = useState(null);
  const [bench, setBench] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet('/api/spp/config').then(setCfg).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setLoading(true); setError(null);
    // Stale-response guard: "Todas" over the whole book takes seconds while
    // "60" comes back instantly, so a late reply for a previous selection
    // could land on top of the current one - thousands of rows under a
    // segment that says 60, with nothing to signal the mismatch.
    let vigente = true;
    const ruta = libro === 'benchmark'
      ? `/api/spp/benchmark-tabla?${new URLSearchParams({ limite })}`
      : `/api/spp/tabla?${new URLSearchParams({ limite, metrica, fondo })}`;
    apiGet(ruta)
      .then((d) => { if (vigente) (libro === 'benchmark' ? setBench : setData)(d); })
      .catch((e) => { if (vigente) setError(e.message); })
      .finally(() => { if (vigente) setLoading(false); });
    return () => { vigente = false; };
  }, [libro, metrica, fondo, limite]);

  const esBench = libro === 'benchmark';
  const actual = esBench ? bench : data;
  const columnas = actual?.columnas || [];
  const filas = actual?.filas || [];

  const urlDescarga = esBench
    ? apiUrl('/api/spp/benchmark/exportar')
    : apiUrl(`/api/spp/exportar?${new URLSearchParams({ metrica, fondo, limite })}`);

  const cab = (c) => {
    if (esBench) return `Fondo ${c.fondo}`;
    const base = `${c.afp} F${c.fondo}`;
    return metrica === 'todas' ? `${base} · ${nombreMetrica(cfg, c.metrica)}` : base;
  };

  const resumen = () => {
    if (!filas.length) return '—';
    if (!esBench) return `${nEnt(filas.length)} filas en pantalla`;
    const faltan = bench?.faltantes || 0;
    return faltan
      ? `${nEnt(filas.length)} fechas · ${nEnt(faltan)} sin benchmark completo`
      : `${nEnt(filas.length)} fechas · sin huecos`;
  };

  return (
    <div>
      <h1 className="page-title">Valor Cuota SPP</h1>
      <p className="page-sub">
        Libro {esBench ? 'del benchmark' : 'de valores cuota'} · {resumen()}
      </p>
      <SppTabs />

      <div className="panel">
        <div className="controls spp-controls">
          <div className="field"><label>Libro</label>
            <SppSeg items={LIBROS} value={libro} onChange={setLibro} /></div>
          {!esBench && (
            <>
              <div className="field"><label>Métrica</label>
                <SppSeg items={[...metricasDe(cfg), ['Todas', 'todas']]}
                  value={metrica} onChange={setMetrica} /></div>
              <div className="field"><label>Tipo de fondo</label>
                <SppSeg items={[...(cfg?.fondos || []).map((f) => [`Fondo ${f}`, String(f)]),
                  ['Todos', 'todos']]}
                  value={fondo} onChange={setFondo} /></div>
            </>
          )}
          <div className="field"><label>Filas</label>
            <SppSeg items={LIMITES} value={limite} onChange={setLimite} /></div>
          <div className="field"><label aria-hidden="true">&nbsp;</label>
            <a className="btn" href={urlDescarga}>
              {esBench ? '↓ Bajar el benchmark · XLSX' : '↓ Bajar lo que veo · CSV'}</a></div>
        </div>
        {esBench && (
          <p className="page-sub dim" style={{ marginTop: 10, marginBottom: 0 }}>
            Las fechas son las del libro de valor cuota: así un día sin benchmark
            se ve como un hueco en vez de desaparecer de la lista. El benchmark lo
            produce el recálculo de la canasta, en <b>Registro y carga → Benchmark</b>.
          </p>
        )}
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      <div className="panel">
        {loading ? <div className="loading">Cargando…</div> : (
          <div className="table-wrap spp-vent" style={{ maxHeight: '70vh', overflowY: 'auto' }}>
            <table>
              <thead>
                <tr><th>Fecha</th>{columnas.map((c) => <th key={c.col} className="num">{cab(c)}</th>)}</tr>
              </thead>
              <tbody>
                {filas.map((f) => (
                  <tr key={f.fecha}>
                    <td>{fFecha(f.fecha)}</td>
                    {f.valores.map((v, i) => (
                      <td key={columnas[i]?.col || i} className={`num ${v == null ? 'dim' : ''}`}>
                        {v == null ? '—'
                          : esBench
                            // Niveles de indice: nunca abreviados. fmtMetrica en
                            // modo compacto convertiria 1.500 puntos en "1,50 M".
                            ? Number(v).toLocaleString('es-PE',
                              { minimumFractionDigits: 2, maximumFractionDigits: 4 })
                            : fmtMetrica(v, columnas[i]?.metrica || metrica, true)}
                      </td>
                    ))}
                  </tr>
                ))}
                {!filas.length && (
                  <tr><td colSpan={columnas.length + 1} className="dim">
                    {esBench
                      ? 'No hay fechas en el libro todavía.'
                      : 'El libro está vacío.'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
