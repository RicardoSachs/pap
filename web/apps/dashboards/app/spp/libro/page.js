
// web/apps/dashboards/app/spp/libro/page.js
// ---------------------------------------------------------------------------
// SPP tablero · Libro: the full book of valor cuota values, filtered by
// metric / fund / row count, with a CSV download of exactly what is on
// screen (the /api/spp/exportar cut mirrors the /api/spp/tabla cut).
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import { apiGet } from '../../../lib/api';
import { apiUrl, fFecha, fmtMetrica, metricasDe, nEnt, nombreMetrica } from '../../../lib/spp';
import SppSeg from '../../../components/SppSeg';
import SppTabs from '../../../components/SppTabs';

const LIMITES = [['60', '60'], ['250', '250'], ['1000', '1000'], ['Todas', 'todas']];

export default function SppLibroPage() {
  const [cfg, setCfg] = useState(null);
  const [metrica, setMetrica] = useState('valor_cuota');
  const [fondo, setFondo] = useState('todos');
  const [limite, setLimite] = useState('60');
  const [data, setData] = useState(null);
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
    const q = new URLSearchParams({ limite, metrica, fondo });
    apiGet(`/api/spp/tabla?${q}`)
      .then((d) => { if (vigente) setData(d); })
      .catch((e) => { if (vigente) setError(e.message); })
      .finally(() => { if (vigente) setLoading(false); });
    return () => { vigente = false; };
  }, [metrica, fondo, limite]);

  const columnas = data?.columnas || [];
  const filas = data?.filas || [];
  const urlCsv = apiUrl(`/api/spp/exportar?${new URLSearchParams({ metrica, fondo, limite })}`);

  const cab = (c) => {
    const base = `${c.afp} F${c.fondo}`;
    return metrica === 'todas' ? `${base} · ${nombreMetrica(cfg, c.metrica)}` : base;
  };

  return (
    <div>
      <h1 className="page-title">Valor Cuota SPP</h1>
      <p className="page-sub">Libro de valores cuota · {filas.length ? `${nEnt(filas.length)} filas en pantalla` : '—'}</p>
      <SppTabs />

      <div className="panel">
        <div className="controls spp-controls">
          <div className="field"><label>Métrica</label>
            <SppSeg items={[...metricasDe(cfg), ['Todas', 'todas']]} value={metrica} onChange={setMetrica} /></div>
          <div className="field"><label>Tipo de fondo</label>
            <SppSeg items={[...(cfg?.fondos || []).map((f) => [`Fondo ${f}`, String(f)]), ['Todos', 'todos']]}
              value={fondo} onChange={setFondo} /></div>
          <div className="field"><label>Filas</label>
            <SppSeg items={LIMITES} value={limite} onChange={setLimite} /></div>
          <div className="field"><label>&nbsp;</label>
            <a className="btn" href={urlCsv}>↓ Bajar lo que veo · CSV</a></div>
        </div>
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
                        {v == null ? '—' : fmtMetrica(v, columnas[i]?.metrica || metrica, true)}
                      </td>
                    ))}
                  </tr>
                ))}
                {!filas.length && (
                  <tr><td colSpan={columnas.length + 1} className="dim">El libro está vacío.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
