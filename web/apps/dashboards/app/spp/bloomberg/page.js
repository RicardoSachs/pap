
// web/apps/dashboards/app/spp/bloomberg/page.js
// ---------------------------------------------------------------------------
// SPP tablero · Bloomberg: the manual series registry ported from the
// monitor. Register/update a series, bulk-register from a file, delete
// (double-confirmed when it has data), trigger the download (background
// task followed by polling /api/spp/tarea), template and export.
//
// Every action answers even without a terminal on this machine: download
// routes return 503 with the reason, which is shown as-is.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';
import { apiGet } from '../../../lib/api';
import { apiSend, apiUrl, fFecha, nEnt } from '../../../lib/spp';
import SppTabs from '../../../components/SppTabs';

const INTERVALOS = ['diario', 'semanal', 'mensual', 'trimestral', 'semestral', 'anual'];

export default function SppBloombergPage() {
  const [estado, setEstado] = useState(null);
  const [error, setError] = useState(null);
  const [eco, setEco] = useState('');
  const [tarea, setTarea] = useState(null);
  const [form, setForm] = useState({ ticker: '', campo: '', intervalo: 'diario', fecha_inicio: '', descripcion: '' });
  const fileRef = useRef(null);
  const [informe, setInforme] = useState(null);
  const pollRef = useRef(null);

  const cargar = () => apiGet('/api/spp/bloomberg').then(setEstado).catch((e) => setError(e.message));
  useEffect(() => { cargar(); return () => clearInterval(pollRef.current); }, []);

  // Poll the background task while active; refresh the registry when done.
  const seguirTarea = () => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const t = await apiGet('/api/spp/tarea');
        setTarea(t);
        if (!t.activa) { clearInterval(pollRef.current); cargar(); }
      } catch { clearInterval(pollRef.current); }
    }, 1200);
  };

  const agregar = async () => {
    setEco('');
    const r = await apiSend('/api/spp/bloomberg/serie', 'POST', {
      ticker: form.ticker, campo: form.campo, intervalo: form.intervalo,
      fecha_inicio: form.fecha_inicio || null, descripcion: form.descripcion || null,
    });
    if (r.ok) {
      setEco(`Registrada: ${r.data.serie.ticker} ${r.data.serie.campo} (${r.data.serie.intervalo})`);
      setForm({ ticker: '', campo: '', intervalo: 'diario', fecha_inicio: '', descripcion: '' });
      cargar();
    } else setEco(`Error: ${r.data.motivo || r.status}`);
  };

  const borrar = async (s) => {
    const tiene = Number(s.filas) > 0;
    const msg = tiene
      ? `${s.ticker} ${s.campo} tiene ${nEnt(Number(s.filas))} dato(s) cargados. ¿Borrar la serie Y sus datos?`
      : `¿Borrar la serie ${s.ticker} ${s.campo}?`;
    if (!window.confirm(msg)) return;
    const r = await apiSend(`/api/spp/bloomberg/serie/${s.serie_id}${tiene ? '?datos=1' : ''}`, 'DELETE');
    setEco(r.ok ? `Serie ${s.serie_id} borrada.` : `Error: ${r.data.motivo || r.status}`);
    cargar();
  };

  const extraer = async (corregir) => {
    setEco('');
    const r = await apiSend('/api/spp/bloomberg/extraer', 'POST', { corregir });
    if (r.ok) { setTarea({ activa: true, accion: 'descarga de Bloomberg', bitacora: [] }); seguirTarea(); }
    else setEco(`No se pudo lanzar: ${r.data.motivo || r.status}`);
  };

  const subirArchivo = async (soloRevisar) => {
    const f = fileRef.current?.files?.[0];
    if (!f) { setEco('Elige un archivo primero.'); return; }
    const fd = new FormData();
    fd.append('archivo', f);
    fd.append('revisar', soloRevisar ? '1' : '');
    const r = await apiSend('/api/spp/bloomberg/archivo', 'POST', fd, true);
    if (r.ok) {
      setInforme({ ...r.data.informe, revisado: r.data.revisado });
      if (!r.data.revisado) cargar();
    } else setEco(`Error: ${r.data.motivo || r.status}`);
  };

  const detalle = estado?.detalle || [];

  return (
    <div>
      <h1 className="page-title">Valor Cuota SPP</h1>
      <p className="page-sub">
        Series de Bloomberg · {estado ? `${estado.series} serie(s), ${nEnt(estado.datos)} datos` : '—'}
      </p>
      <SppTabs />

      {error && <div className="panel error">Error: {error}</div>}
      {estado && !estado.disponible && (
        <div className="panel"><span className="flag-warn">Sin terminal en esta máquina</span>
          <p className="page-sub" style={{ whiteSpace: 'pre-wrap' }}>{estado.motivo}</p>
          <p className="page-sub">El registro se puede editar igual; la descarga corre en la máquina con terminal.</p>
        </div>
      )}

      <div className="panel">
        <div className="panel-title">Agregar o corregir una serie</div>
        <p className="page-sub">Idempotente por ticker + campo + intervalo: volver a enviarla actualiza
          en lugar de duplicar, y lo que no se manda no se borra.</p>
        <div className="controls spp-controls">
          <div className="field"><label>Ticker</label>
            <input className="date-input" placeholder="SPX Index" value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value })} /></div>
          <div className="field"><label>Campo</label>
            <input className="date-input" placeholder="PX_LAST" value={form.campo}
              onChange={(e) => setForm({ ...form, campo: e.target.value })} /></div>
          <div className="field"><label>Intervalo</label>
            <select className="select" value={form.intervalo}
              onChange={(e) => setForm({ ...form, intervalo: e.target.value })}>
              {INTERVALOS.map((i) => <option key={i} value={i}>{i}</option>)}
            </select></div>
          <div className="field"><label>Desde</label>
            <input className="date-input" type="date" value={form.fecha_inicio}
              onChange={(e) => setForm({ ...form, fecha_inicio: e.target.value })} /></div>
          <div className="field" style={{ flex: '1 1 220px' }}><label>Descripción</label>
            <input className="date-input" placeholder="S&P 500" value={form.descripcion}
              onChange={(e) => setForm({ ...form, descripcion: e.target.value })} /></div>
          <div className="field"><label>&nbsp;</label>
            <button className="btn" onClick={agregar}>Agregar serie</button></div>
        </div>

        <div className="controls" style={{ marginTop: 10 }}>
          <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" className="date-input" />
          <button className="btn" onClick={() => subirArchivo(true)}>Revisar archivo</button>
          <button className="btn" onClick={() => subirArchivo(false)}>Registrar las series</button>
          <a className="btn" href={apiUrl('/api/spp/bloomberg/plantilla')}>↓ Plantilla</a>
          <a className="btn" href={apiUrl('/api/spp/bloomberg/exportar')}>↓ Bajar lo cargado</a>
        </div>
        {informe && (
          <p className="page-sub">
            Archivo {informe.archivo}: {informe.total} serie(s) leídas
            {informe.revisado ? ' (solo revisión, nada registrado)' :
              ` · ${informe.nuevas} nuevas, ${informe.actualizadas} actualizadas`}
            {informe.total_omitidas ? ` · ${informe.total_omitidas} omitida(s)` : ''}
          </p>
        )}
        {eco && <p className="page-sub"><b>{eco}</b></p>}
      </div>

      <div className="panel">
        <div className="controls" style={{ justifyContent: 'space-between' }}>
          <div className="panel-title">Descarga</div>
          <div className="controls">
            <button className="btn" onClick={() => extraer(false)}
              disabled={tarea?.activa || (estado && !estado.disponible)}>Bajar lo que falta</button>
            <button className="btn" onClick={() => extraer(true)}
              disabled={tarea?.activa || (estado && !estado.disponible)}>Bajar y corregir</button>
          </div>
        </div>
        <p className="page-sub">Cada serie se pide desde el día siguiente a su último dato; las que ya
          están al día no consumen cuota. Las peticiones se agrupan por ventana, campo e intervalo.</p>
        {tarea && (
          <div className="spp-bitacora mono">
            {(tarea.bitacora || []).map((l, i) => <div key={i}>{l}</div>)}
            {tarea.activa ? <div className="dim">…</div>
              : tarea.error ? <div className="neg">ERROR: {tarea.error}</div>
                : <div className="pos">Descarga terminada.</div>}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-title">Series registradas</div>
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th>Ticker</th><th>Campo</th><th>Intervalo</th><th>Descripción</th>
              <th className="num">Puntos</th><th>Cobertura</th><th>Último resultado</th><th>Activa</th><th></th>
            </tr></thead>
            <tbody>
              {detalle.length ? detalle.map((s) => (
                <tr key={s.serie_id}>
                  <td className="mono">{s.ticker}</td>
                  <td className="mono">{s.campo}</td>
                  <td>{s.intervalo}</td>
                  <td>{s.descripcion || <span className="dim">—</span>}</td>
                  <td className="num">{nEnt(Number(s.filas) || 0)}</td>
                  <td>{s.desde ? `${fFecha(s.desde)} a ${fFecha(s.hasta)}` : <span className="dim">sin datos</span>}</td>
                  <td>{s.ultimo_resultado
                    ? <span className={s.ultimo_resultado === 'ok' ? 'pos' : (s.ultimo_resultado === 'error' ? 'neg' : 'dim')}>
                        {s.ultimo_resultado}</span>
                    : <span className="dim">—</span>}</td>
                  <td>{s.activa ? 'sí' : <span className="dim">no</span>}</td>
                  <td><button className="btn" onClick={() => borrar(s)}>Borrar</button></td>
                </tr>
              )) : <tr><td colSpan={9} className="dim">Ninguna serie registrada todavía.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
