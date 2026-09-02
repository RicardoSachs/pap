
// web/apps/dashboards/app/spp/carga/page.js
// ---------------------------------------------------------------------------
// SPP tablero · Registro y carga (phase 2): everything that writes.
//
// One grammar for the whole view, ported from the monitor: on the LEFT you
// act, on the RIGHT you see - and no file reaches the base without having
// been shown first (the historical load reviews under a vale, then loads in
// the chosen mode). Long operations run in the shared background task and
// are followed by polling /api/spp/tarea.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';
import { apiGet } from '../../../lib/api';
import {
  METRICAS, NOMBRE_METRICA, apiSend, apiUrl, fFecha, fmtMetrica, hoyLocal, nEnt,
} from '../../../lib/spp';
import SppTabs from '../../../components/SppTabs';

const fHora = (t) => {
  if (!t) return '—';
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString('es-PE',
    { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};

// Small key/value report table used by every section.
function Informe({ filas }) {
  return (
    <table className="spp-informe"><tbody>
      {filas.map(([a, b], i) => (
        <tr key={i}><td>{a}</td><td className="num">{b}</td></tr>
      ))}
    </tbody></table>
  );
}

// Preview of a reviewed file: last rows, most recent first.
function Muestra({ muestra, titulo }) {
  if (!muestra || !muestra.filas?.length) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <div className="panel-title">{titulo} · {nEnt(muestra.total)} fechas en total</div>
      <div className="table-wrap" style={{ maxHeight: 300, overflowY: 'auto' }}>
        <table>
          <thead><tr><th>Fecha</th>{muestra.columnas.map((c) => <th key={c} className="num">{c}</th>)}</tr></thead>
          <tbody>
            {muestra.filas.map((f) => (
              <tr key={f[0]}>
                <td>{fFecha(f[0])}</td>
                {f.slice(1).map((v, i) => (
                  <td key={i} className={`num ${v == null ? 'dim' : ''}`}>
                    {v == null ? '—' : Number(v).toLocaleString('es-PE',
                      { minimumFractionDigits: 2, maximumFractionDigits: 7 })}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function SppCargaPage() {
  const [cfg, setCfg] = useState(null);
  const [estado, setEstado] = useState(null);

  // ---- shared background task ----
  const [tarea, setTarea] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  const pollRef = useRef(null);

  const cargarEstado = () => apiGet('/api/spp/estado').then(setEstado).catch(() => {});

  const sondear = (alTerminar) => {
    clearInterval(pollRef.current);
    setOcupado(true);
    pollRef.current = setInterval(async () => {
      try {
        const t = await apiGet('/api/spp/tarea');
        setTarea(t);
        if (!t.activa) {
          clearInterval(pollRef.current);
          setOcupado(false);
          cargarEstado(); cargarProgramado();
          if (alTerminar) alTerminar(t);
        }
      } catch { clearInterval(pollRef.current); setOcupado(false); }
    }, 900);
  };

  // ---- extraccion + corrida automatica ----
  const [prog, setProg] = useState(null);
  const [ecoExtraer, setEcoExtraer] = useState('');

  const cargarProgramado = () =>
    apiGet('/api/spp/programado').then(setProg).catch(() => setProg(null));

  const extraer = async (refrescar) => {
    setEcoExtraer('');
    const r = await apiSend('/api/spp/extraer', 'POST', { refrescar });
    if (!r.ok) { setEcoExtraer(r.data.motivo || `Error ${r.status}`); return; }
    setTarea({ activa: true, accion: 'extraccion SBS', bitacora: [] });
    sondear();
  };

  // ---- registro manual ----
  const [rFecha, setRFecha] = useState('');
  const [rAfp, setRAfp] = useState('');
  const [rMetrica, setRMetrica] = useState('valor_cuota');
  const [rValores, setRValores] = useState({});
  const [rActual, setRActual] = useState('');
  const [rVecinos, setRVecinos] = useState({ fondos: [], fechas: [], series: {} });
  const [rMensaje, setRMensaje] = useState(null);
  const [rTick, setRTick] = useState(0);   // bumps to reload the preload after writing

  const nombres = (cfg?.afps || []).map((a) => a.nombre);
  const opera = (afp, f) => {
    const a = (cfg?.afps || []).find((x) => x.nombre === afp);
    return a ? a.fondos.includes(f) : true;
  };
  const fondosDe = (afp) => (cfg?.fondos || []).filter((f) => opera(afp, f));

  useEffect(() => {
    apiGet('/api/spp/config').then((c) => {
      setCfg(c);
      setRAfp(c.casa || c.afps[0]?.nombre || '');
    }).catch(() => {});
    setRFecha(hoyLocal());
    cargarEstado();
    cargarProgramado();
    return () => clearInterval(pollRef.current);
  }, []);

  // Preload the fund boxes with what the book already holds (±12 days for
  // the neighboring closes), like the monitor's verDato().
  useEffect(() => {
    if (!cfg || !rFecha || !rAfp) return;
    const desde = new Date(`${rFecha}T00:00:00`); desde.setDate(desde.getDate() - 12);
    const hasta = new Date(`${rFecha}T00:00:00`); hasta.setDate(hasta.getDate() + 12);
    const fondos = fondosDe(rAfp);
    Promise.all(fondos.map(async (fo) => {
      const q = new URLSearchParams({
        fondo: String(fo), afps: rAfp, metrica: rMetrica,
        desde: desde.toISOString().slice(0, 10), hasta: hasta.toISOString().slice(0, 10),
      });
      const d = await apiGet(`/api/spp/serie?${q}`);
      return [fo, d.series?.[0]?.puntos || []];
    })).then((pares) => {
      const series = Object.fromEntries(pares);
      const vals = {}; let cargados = 0;
      fondos.forEach((fo) => {
        const hit = series[fo].find((p) => p[0] === rFecha);
        vals[fo] = hit ? String(hit[1]) : '';
        if (hit) cargados++;
      });
      setRValores(vals);
      setRActual(cargados
        ? `${rAfp} · ${NOMBRE_METRICA[rMetrica]} · ${fFecha(rFecha)} — ${cargados} de ${fondos.length} fondos ya registrados.`
        : `${rAfp} · ${NOMBRE_METRICA[rMetrica]} · ${fFecha(rFecha)} — sin datos ese día.`);
      const fechas = [...new Set(fondos.flatMap((fo) => series[fo].map((p) => p[0])))]
        .sort().slice(-9).reverse();
      setRVecinos({ fondos, fechas, series });
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cfg, rFecha, rAfp, rMetrica, rTick]);

  const registrar = async (vaciarTodo) => {
    if (!vaciarTodo && !Object.values(rValores).some((v) => String(v).trim() !== '')) {
      setRMensaje({ ok: false, texto: 'No hay ningún valor escrito. Para borrar la fecha usa «Anular la fecha».' });
      return;
    }
    if (vaciarTodo && !window.confirm(
      `Anular ${rAfp} · ${NOMBRE_METRICA[rMetrica]} · ${fFecha(rFecha)}: borra los valores de todos sus fondos en esa fecha. ¿Continuar?`)) return;
    const valores = {};
    fondosDe(rAfp).forEach((fo) => {
      const v = String(rValores[fo] ?? '').trim();
      valores[fo] = vaciarTodo ? null : (v === '' ? null : Number(v));
    });
    const r = await apiSend('/api/spp/valor', 'POST', {
      fecha: rFecha, afp: rAfp, metrica: rMetrica, valores,
    });
    if (!r.ok) { setRMensaje({ ok: false, texto: r.data.motivo || `Error ${r.status}` }); return; }
    const x = r.data.resultado;
    const g = Object.keys(x.guardados).length; const b = x.borrados.length;
    setRMensaje({
      ok: true,
      texto: `${g} valor(es) guardados${b ? ` · ${b} borrados` : ''} · ${x.afp} · ${NOMBRE_METRICA[x.metrica]} · ${fFecha(x.fecha)}`
        + (x.fila_nueva ? ' · fila nueva en el libro' : '')
        + (x.fila_borrada ? ' · la fecha quedó sin datos y salió del libro' : ''),
    });
    setRTick((t) => t + 1);   // reload the boxes and neighbors with what was written
    cargarEstado();
  };

  // ---- carga historica ----
  const hRef = useRef(null);
  const [hNombre, setHNombre] = useState('Ningún archivo seleccionado');
  const [hInforme, setHInforme] = useState(null);
  const [hVale, setHVale] = useState(null);
  const [hEco, setHEco] = useState('');

  const revisarHistorico = async () => {
    const a = hRef.current?.files?.[0];
    if (!a) return;
    setHNombre(`${a.name} · revisando…`); setHInforme(null); setHVale(null); setHEco('');
    const fd = new FormData(); fd.append('archivo', a);
    const r = await apiSend('/api/spp/historico/revisar', 'POST', fd, true);
    if (!r.ok) {
      setHNombre(a.name);
      setHEco(r.data.motivo || `Error ${r.status}`);
      return;
    }
    setHNombre(`${a.name} · revisado, nada escrito todavía`);
    setHInforme(r.data.informe);
    setHVale(r.data.vale);
  };

  const cargarHistorico = async (modo) => {
    if (!hVale || !hInforme) return;
    const msg = modo === 'faltantes'
      ? 'Cargar lo que falta: agrega fechas nuevas y rellena celdas vacías. No modifica ningún valor que ya tenga dato. ¿Continuar?'
      : `Cargar y corregir: además de agregar lo que falta, REEMPLAZA ${nEnt(hInforme.celdas_distintas)} celda(s) que difieren del archivo. ¿Continuar?`;
    if (!window.confirm(msg)) return;
    const r = await apiSend('/api/spp/historico/cargar', 'POST', { vale: hVale, modo });
    if (!r.ok) { setHEco(r.data.motivo || `Error ${r.status}`); return; }
    setHEco('Guardando en la base…');
    sondear((t) => {
      if (t.error) {
        setHEco('La carga falló y no se guardó nada nuevo. Puedes reintentar sin volver a subir el archivo.');
      } else {
        setHEco(`Cargado en modo ${modo === 'faltantes' ? 'solo lo que falta' : 'corregir'}.`);
        setHVale(null);
      }
    });
  };

  const filasInformeH = (i) => {
    const f = [
      ['Archivo', `${i.archivo} · ${nEnt(Math.round(i.bytes / 1024))} KB`],
      ['Contenido', `${nEnt(i.filas)} fechas · ${i.series} series · ${nEnt(i.valores)} valores`],
      ['Rango', `${fFecha(i.desde)} a ${fFecha(i.hasta)}`],
      ['Fechas nuevas', `${nEnt(i.fechas_nuevas)}${i.celdas_nuevas ? ` · ${nEnt(i.celdas_nuevas)} valores` : ''}`],
      ['Ya en el libro', nEnt(i.fechas_conocidas)],
      ['Celdas vacías que se llenarían', nEnt(i.celdas_a_llenar)],
      ['Celdas que difieren del libro', nEnt(i.celdas_distintas)],
      ['Celdas idénticas', nEnt(i.celdas_iguales)],
    ];
    return f;
  };

  // ---- benchmark ----
  const [bFecha, setBFecha] = useState('');
  const [bValores, setBValores] = useState({});
  const [bEco, setBEco] = useState('');
  const [bEstado, setBEstado] = useState(null);
  const bRef = useRef(null);
  const [bNombre, setBNombre] = useState('Ningún archivo seleccionado');
  const [bInforme, setBInforme] = useState(null);
  const [bCargado, setBCargado] = useState(false);

  const fondosBench = cfg?.fondos_benchmark || [];

  const cargarBench = () =>
    apiGet('/api/spp/benchmark').then((j) => setBEstado(j.estado)).catch(() => {});

  const verBench = async (f) => {
    if (!f) return;
    try {
      const j = await apiGet(`/api/spp/benchmark/fecha?fecha=${f}`);
      const vals = {};
      fondosBench.forEach((fo) => { vals[fo] = j.valores?.[fo] == null ? '' : String(j.valores[fo]); });
      setBValores(vals);
      const n = Object.values(j.valores || {}).filter((v) => v != null).length;
      setBEco(j.existe
        ? `${n} de ${fondosBench.length} fondos ya registrados en ${fFecha(f)}.`
        : `${fFecha(f)} no está en la tabla de benchmark.`);
    } catch { /* ignore */ }
  };

  useEffect(() => { if (cfg) { setBFecha(hoyLocal()); cargarBench(); } }, [cfg]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (cfg && bFecha) verBench(bFecha); }, [cfg, bFecha]); // eslint-disable-line react-hooks/exhaustive-deps

  const registrarBench = async (vaciarTodo) => {
    if (!bFecha) { setBEco('Falta la fecha.'); return; }
    if (!vaciarTodo && !Object.values(bValores).some((v) => String(v).trim() !== '')) {
      setBEco('Todos los cuadros están vacíos. Para borrar la fecha usa «Anular la fecha».');
      return;
    }
    if (vaciarTodo && !window.confirm(
      `Anular el benchmark del ${fFecha(bFecha)} en todos los fondos. ¿Continuar?`)) return;
    const valores = {};
    fondosBench.forEach((fo) => {
      const v = String(bValores[fo] ?? '').trim();
      valores[fo] = vaciarTodo ? null : (v === '' ? null : Number(v));
    });
    const r = await apiSend('/api/spp/benchmark/valor', 'POST', { fecha: bFecha, valores });
    if (!r.ok) { setBEco(r.data.motivo || `Error ${r.status}`); return; }
    const x = r.data.resultado;
    const g = Object.keys(x.guardados).length; const b = x.borrados.length;
    let t = `${g} valor(es) guardados${b ? ` · ${b} borrados` : ''}`;
    if (x.fila_nueva) t += ' · fila nueva';
    if (x.fila_borrada) t += ' · la fecha salió de la tabla';
    await verBench(bFecha); cargarBench();
    setBEco(t);
  };

  const subirBench = async (revisar, refrescar) => {
    const a = bRef.current?.files?.[0];
    if (!a) { setBEco('Elige un archivo primero.'); return; }
    if (!revisar && refrescar && !window.confirm(
      'Cargar y corregir: además de agregar lo que falta, reemplaza los valores ya cargados con los del archivo. ¿Continuar?')) return;
    setBNombre(`${a.name} · ${revisar ? 'revisando…' : 'cargando…'}`);
    const fd = new FormData();
    fd.append('archivo', a);
    if (revisar) fd.append('revisar', '1');
    if (refrescar) fd.append('refrescar', '1');
    const r = await apiSend('/api/spp/benchmark/archivo', 'POST', fd, true);
    if (!r.ok) {
      setBNombre(a.name);
      setBInforme(null);
      setBEco(r.data.motivo || `Error ${r.status}`);
      return;
    }
    setBNombre(`${a.name} · ${revisar ? 'revisado, nada escrito todavía' : 'cargado'}`);
    setBInforme({ ...r.data.informe, cargado: !revisar });
    setBCargado(!revisar);
    if (!revisar) { cargarBench(); verBench(bFecha); }
  };

  const filasInformeB = (i) => {
    const lectura = i.origen === 'excel'
      ? `${i.formato} · hoja «${i.hoja || '—'}»`
      : `${i.formato} · CSV, separador «${i.separador}» · decimales con ${i.decimal}`;
    const f = [
      ['Archivo', i.archivo || '—'],
      ['Lectura', lectura],
      ['Contenido', `${nEnt(i.filas)} fechas · ${nEnt(i.celdas)} valores`],
      ['Rango', `${fFecha(i.desde)} a ${fFecha(i.hasta)}`],
      ['Columnas leídas', (i.columnas || []).join(', ') || '—'],
    ];
    if (i.cargado) {
      f.push(['Fechas nuevas', nEnt(i.nuevas)]);
      f.push(['Fechas actualizadas', nEnt(i.actualizadas)]);
      f.push(['Celdas escritas', nEnt(i.celdas_escritas != null ? i.celdas_escritas : i.celdas)]);
    }
    return f;
  };

  // ---- corrida automatica render ----
  const progFilas = () => {
    const t = prog?.tarea || {}; const u = prog?.ultima || {};
    const filas = [];
    if (!t.disponible) filas.push(['Programación', 'no se pudo consultar']);
    else if (!t.registrada) return null;   // handled with the aviso below
    else {
      const hora = (t.disparo || '').slice(11, 16);
      filas.push(['Frecuencia', hora ? `todos los días a las ${hora}` : 'diaria']);
      filas.push(['Estado', t.estado || '—']);
      filas.push(['Próxima', fHora(t.proxima)]);
      if (t.omitidas) filas.push(['Corridas omitidas', t.omitidas]);
    }
    if (u.inicio) {
      filas.push(['Última corrida', `${fHora(u.inicio)} · ${u.segundos || 0} s`]);
      filas.push(['Resultado', u.ok !== false
        ? `correcta · ${u.cargadas || 0} observación(es) nuevas en ${u.fechas || 0} fecha(s)`
        : `falló${u.error ? ` · ${u.error}` : ''}`]);
    } else filas.push(['Última corrida', 'todavía ninguna']);
    return filas;
  };

  const metricaPaso = rMetrica === 'valor_cuota' ? '0.0000001' : '0.01';

  return (
    <div>
      <h1 className="page-title">Valor Cuota SPP</h1>
      <p className="page-sub">Registro y carga · a la izquierda se actúa, a la derecha se ve.
        Ningún archivo llega a la base sin haberse mostrado antes.</p>
      <SppTabs />

      {/* ===== 1 · Registro manual de valor cuota ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Valor cuota · registro manual</div>
          <p className="page-sub">Una AFP y una fecha, sus fondos a la vez. Los cuadros se
            precargan con lo que ya hay: escribir uno lo reemplaza y <b>dejarlo vacío borra
            ese dato</b>. Si la fecha queda sin ningún valor, sale del libro.</p>
          <div className="controls spp-controls">
            <div className="field"><label>Fecha</label>
              <input className="date-input" type="date" value={rFecha}
                onChange={(e) => setRFecha(e.target.value)} /></div>
            <div className="field"><label>AFP</label>
              <select className="select" value={rAfp} onChange={(e) => setRAfp(e.target.value)}>
                {nombres.map((a) => <option key={a} value={a}>{a}</option>)}
              </select></div>
            <div className="field"><label>Métrica</label>
              <select className="select" value={rMetrica} onChange={(e) => setRMetrica(e.target.value)}>
                {METRICAS.map(([et, v]) => <option key={v} value={v}>{et}</option>)}
              </select></div>
          </div>
          <div className="controls spp-controls" style={{ marginTop: 10 }}>
            {fondosDe(rAfp).map((fo) => (
              <div className="field" key={fo}><label>Fondo {fo}</label>
                <input className="date-input" type="number" min="0" step={metricaPaso}
                  placeholder={rMetrica === 'valor_cuota' ? '0.0000000' : '0.00'}
                  value={rValores[fo] ?? ''}
                  onChange={(e) => setRValores({ ...rValores, [fo]: e.target.value })} /></div>
            ))}
          </div>
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => registrar(false)}>Registrar valores</button>
            <button className="btn" onClick={() => registrar(true)}>Anular la fecha</button>
          </div>
          {rMensaje && (
            <p className="page-sub" style={{ marginTop: 10 }}>
              <b className={rMensaje.ok ? 'pos' : 'neg'}>{rMensaje.ok ? '✓' : 'No se registró ·'}</b>{' '}
              {rMensaje.texto}
            </p>
          )}
        </div>

        <div className="panel">
          <div className="panel-title">En el libro</div>
          <p className="page-sub">{rActual || 'Elige fecha, AFP y métrica.'}</p>
          <div className="panel-title" style={{ marginTop: 12 }}>Cierres vecinos</div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Fecha</th>
                {rVecinos.fondos.map((fo) => <th key={fo} className="num">F{fo}</th>)}</tr></thead>
              <tbody>
                {rVecinos.fechas.length ? rVecinos.fechas.map((fx) => (
                  <tr key={fx} style={fx === rFecha ? { fontWeight: 700 } : undefined}>
                    <td>{fFecha(fx)}</td>
                    {rVecinos.fondos.map((fo) => {
                      const hit = (rVecinos.series[fo] || []).find((p) => p[0] === fx);
                      return <td key={fo} className={`num ${hit ? '' : 'dim'}`}>
                        {hit ? fmtMetrica(hit[1], rMetrica, rMetrica !== 'valor_cuota') : '—'}</td>;
                    })}
                  </tr>
                )) : <tr><td colSpan={rVecinos.fondos.length + 1} className="dim">Sin cierres cerca.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ===== 2 · Carga histórica por Excel ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Valor cuota · carga histórica por Excel</div>
          <p className="page-sub">El archivo de la SBS <b>tal como se descarga</b> («Valores
            cuota desde Agosto 1993», hoja «Valor cuota diario»). Trae solo valor cuota, y
            una celda vacía se deja como está: el Excel nunca borra.</p>
          <div className="controls">
            <input ref={hRef} type="file" accept=".xls,.xlsx" className="date-input"
              onChange={revisarHistorico} />
            <span className="page-sub" style={{ margin: 0 }}>{hNombre}</span>
          </div>
          {hInforme && (
            <>
              <Informe filas={filasInformeH(hInforme)} />
              {hInforme.celdas_distintas > 0 && (
                <div style={{ marginTop: 8 }}>
                  <p className="page-sub"><b>{nEnt(hInforme.celdas_distintas)}</b> celda(s)
                    tienen hoy un valor distinto al del archivo. Solo cambian con
                    «Cargar y corregir»:</p>
                  <Informe filas={hInforme.ejemplos.map((e) =>
                    [`${fFecha(e.fecha)} · ${e.serie}`, `${e.libro} → ${e.archivo}`])} />
                </div>
              )}
              {hInforme.total_futuras > 0 && (
                <p className="page-sub">Se descartaron <b>{hInforme.total_futuras}</b> fecha(s)
                  futuras: {hInforme.futuras.join(', ')}.</p>
              )}
              {hInforme.no_registradas?.length > 0 && (
                <p className="page-sub flag-warn">El archivo trae AFP que no están en el
                  registro: <b>{hInforme.no_registradas.join(', ')}</b>. Sus datos no se
                  cargarán hasta darlas de alta en config/afps.yaml.</p>
              )}
              {hVale && (
                <div className="controls" style={{ marginTop: 12 }}>
                  <button className="btn" disabled={ocupado}
                    onClick={() => cargarHistorico('faltantes')}>Cargar lo que falta</button>
                  <button className="btn" disabled={ocupado}
                    onClick={() => cargarHistorico('sobrescribir')}>Cargar y corregir</button>
                </div>
              )}
            </>
          )}
          {hEco && <p className="page-sub"><b>{hEco}</b></p>}
          <div className="controls" style={{ marginTop: 12 }}>
            <a className="btn" target="_blank" rel="noreferrer"
              href="https://www.sbs.gob.pe/app/stats/EstadisticaSistemaFinancieroResultadosHist.asp?c=FP-130706&Y=0">
              Abrir la página de la SBS</a>
            <a className="btn" href={apiUrl('/api/spp/exportar')}>↓ Bajar lo cargado</a>
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">Vista previa del archivo</div>
          <p className="page-sub">
            {hInforme
              ? `${hInforme.archivo} · ${nEnt(hInforme.filas)} fechas · ${fFecha(hInforme.desde)} a ${fFecha(hInforme.hasta)}. Nada se ha guardado.`
              : 'Elige un Excel y aquí verás lo que trae, antes de que nada toque la base.'}
          </p>
          <Muestra muestra={hInforme?.muestra} titulo="Últimas filas del archivo" />
        </div>
      </div>

      {/* ===== 3 · Extracción diaria ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Valor cuota · extracción diaria</div>
          <p className="page-sub">Lee la página de variables SPP (últimos 7 días hábiles) e
            inserta solo lo que falta, con las tres métricas. Es la única carga que corre
            sola. Toma unos 20–90 s.</p>
          <div className="controls">
            <button className="btn" disabled={ocupado} onClick={() => extraer(false)}>Correr extracción</button>
            <button className="btn" disabled={ocupado} onClick={() => extraer(true)}>Correr y sobrescribir</button>
          </div>
          <p className="page-sub flag-warn" style={{ marginTop: 10 }}>
            La SBS está detrás del WAF Imperva: <b>se abrirá una ventana de Chrome</b> en la
            máquina donde corre la API. No la cierres mientras corre.
          </p>
          {ecoExtraer && <p className="page-sub"><b className="neg">{ecoExtraer}</b></p>}

          <div className="panel-title" style={{ marginTop: 14 }}>Corrida automática</div>
          {prog && !prog.tarea?.registrada && prog.tarea?.disponible ? (
            <p className="page-sub">La extracción <b>no corre sola</b> todavía. Para activarla,
              en PowerShell dentro del repo:{' '}
              <span className="mono">.\scripts\&quot;Programar extraccion SPP.ps1&quot;</span> —
              queda diaria a las 18:00 (<span className="mono">-Hora 19:30</span> la cambia,{' '}
              <span className="mono">-Quitar</span> la elimina).</p>
          ) : progFilas() ? <Informe filas={progFilas()} /> : <p className="page-sub dim">—</p>}
        </div>

        <div className="panel">
          <div className="panel-title">Bitácora</div>
          <div className="spp-bitacora mono">
            {(tarea?.bitacora || []).length
              ? tarea.bitacora.map((l, i) => (
                <div key={i} className={String(l).startsWith('ERROR') ? 'neg' : ''}>{l}</div>))
              : <div className="dim">Sin operaciones en esta sesión.</div>}
            {tarea && !tarea.activa && (tarea.error
              ? <div className="neg">ERROR: {tarea.error}</div>
              : <div className="pos">Operación terminada.</div>)}
          </div>

          <div className="panel-title" style={{ marginTop: 14 }}>Tramos sin dato</div>
          <p className="page-sub">Días hábiles consecutivos sin valor cuota. Los tramos de 1–2
            días se omiten: son feriados peruanos, no información faltante.</p>
          {(estado?.huecos || []).length ? (
            <Informe filas={estado.huecos.map((h) =>
              [`${fFecha(h.desde)} a ${fFecha(h.hasta)}`, `${h.dias} d.h.`])} />
          ) : <p className="page-sub dim">Sin tramos abiertos.</p>}
        </div>
      </div>

      {/* ===== 4 · Benchmark: registro manual ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Benchmark · registro manual</div>
          <p className="page-sub">Un solo benchmark por tipo de fondo, común a todas las AFP
            (solo fondos {fondosBench.join(', ')}). Mismas reglas: los cuadros se precargan y
            <b> dejar uno vacío borra ese dato</b>.</p>
          <div className="controls spp-controls">
            <div className="field"><label>Fecha</label>
              <input className="date-input" type="date" value={bFecha}
                onChange={(e) => setBFecha(e.target.value)} /></div>
            {fondosBench.map((fo) => (
              <div className="field" key={fo}><label>Fondo {fo}</label>
                <input className="date-input" type="number" min="0" step="0.0000001"
                  placeholder="0.0000000" value={bValores[fo] ?? ''}
                  onChange={(e) => setBValores({ ...bValores, [fo]: e.target.value })} /></div>
            ))}
          </div>
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => registrarBench(false)}>Registrar benchmark</button>
            <button className="btn" onClick={() => registrarBench(true)}>Anular la fecha</button>
          </div>
          {bEco && <p className="page-sub"><b>{bEco}</b></p>}
        </div>

        <div className="panel">
          <div className="panel-title">En la tabla</div>
          <p className="page-sub">
            {bEstado?.filas
              ? `${nEnt(bEstado.filas)} fechas cargadas · ${fFecha(bEstado.desde)} a ${fFecha(bEstado.hasta)}`
              : 'Todavía no hay ningún benchmark cargado.'}
          </p>
          {bEstado?.series?.length > 0 && (
            <Informe filas={bEstado.series.map((x) => [
              `Fondo ${x.fondo}`,
              x.puntos ? `${nEnt(x.puntos)} fechas · último ${x.valor} el ${fFecha(x.fecha)}` : 'sin datos',
            ])} />
          )}
        </div>
      </div>

      {/* ===== 5 · Benchmark: carga por archivo ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Benchmark · carga por Excel</div>
          <p className="page-sub">Una fila por fecha y una columna por fondo (f1 / Fondo 1 /
            fondo_1 / benchmark 1, en cualquier orden), o el formato largo fecha·fondo·valor.
            También se acepta CSV. <b>Una celda vacía se deja como está</b>: el archivo nunca
            borra.</p>
          <div className="controls">
            <input ref={bRef} type="file" accept=".xlsx,.xls,.csv" className="date-input"
              onChange={() => subirBench(true, false)} />
            <span className="page-sub" style={{ margin: 0 }}>{bNombre}</span>
          </div>
          {bInforme && !bCargado && (
            <div className="controls" style={{ marginTop: 12 }}>
              <button className="btn" onClick={() => subirBench(false, false)}>Cargar lo que falta</button>
              <button className="btn" onClick={() => subirBench(false, true)}>Cargar y corregir</button>
            </div>
          )}
          <div className="controls" style={{ marginTop: 12 }}>
            <a className="btn" href={apiUrl('/api/spp/benchmark/plantilla')}>↓ Plantilla</a>
            <a className="btn" href={apiUrl('/api/spp/benchmark/exportar')}>↓ Bajar lo cargado</a>
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">Vista previa del archivo</div>
          {bInforme ? (
            <>
              <Informe filas={filasInformeB(bInforme)} />
              {(bInforme.avisos || []).map((a, i) => (
                <p key={i} className="page-sub">Aviso: {a}</p>
              ))}
              {bInforme.total_omitidas > 0 && (
                <p className="page-sub flag-warn">Se omitieron <b>{bInforme.total_omitidas}</b> fila(s):{' '}
                  {bInforme.omitidas.slice(0, 5).map((o) => `línea ${o.linea} (${o.motivo})`).join('; ')}
                  {bInforme.total_omitidas > 5 ? '; …' : ''}</p>
              )}
              <Muestra muestra={bInforme.muestra}
                titulo={bCargado ? 'Últimas filas cargadas' : 'Últimas filas del archivo'} />
            </>
          ) : (
            <p className="page-sub">Elige un archivo y aquí verás lo que trae, antes de que
              nada toque la base.</p>
          )}
        </div>
      </div>
    </div>
  );
}
