
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
  apiSend, apiUrl, fFecha, fHora, fmtMetrica, fondosDe as fondosDeCfg, hoyLocal,
  metricasDe, nEnt, nombreFuente, nombreMetrica,
} from '../../../lib/spp';
import Bitacora from '../../../components/Bitacora';
import Eco from '../../../components/Eco';
import SppSeg from '../../../components/SppSeg';
import SppTabs from '../../../components/SppTabs';
import useSppTarea from '../../../components/useSppTarea';

// The three work areas, and the hash that makes each one linkable. Panel,
// Libro and Bloomberg are routes; these were pure state, so a reload (which
// the task hook itself sometimes advises) always dropped the operator back
// into Valor cuota.
const AREAS = [['Valor cuota', 'vc'], ['Series manuales', 'series'], ['Benchmark', 'benchmark']];
const CLAVES_AREA = AREAS.map(([, v]) => v);

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
  // Which of the three work areas is on screen: valor cuota, series
  // (component bases) or benchmark (weights/composition). Kept in the URL
  // hash - not the query string, which Sidebar propagates to every menu
  // link - so the area survives a reload and can be sent to someone.
  const [seccion, setSeccionEstado] = useState('vc');

  useEffect(() => {
    const inicial = window.location.hash.slice(1);
    if (CLAVES_AREA.includes(inicial)) setSeccionEstado(inicial);
  }, []);

  const setSeccion = (v) => {
    setSeccionEstado(v);
    try {
      window.history.replaceState(null, '', `${window.location.pathname}#${v}`);
    } catch { /* el área sigue cambiando aunque la URL no acompañe */ }
  };

  // ---- shared background task (hook shared with the Bloomberg tab) ----
  const { tarea, ocupado, iniciar } = useSppTarea();

  const cargarEstado = () => apiGet('/api/spp/estado').then(setEstado).catch(() => {});

  const alTerminarTarea = (despues) => (t) => {
    cargarEstado();
    cargarProgramado();
    if (despues) despues(t);
  };

  // ---- extraccion + corrida automatica ----
  const [prog, setProg] = useState(null);
  const [ecoExtraer, setEcoExtraer] = useState('');

  const cargarProgramado = () =>
    apiGet('/api/spp/programado').then(setProg).catch(() => setProg(null));

  const extraer = async (refrescar) => {
    // Overwriting confirms, like every other action that replaces stored
    // values (the historical load, the file load and the recalculation all
    // ask first). This one reaches further than it looks: it re-reads the
    // last 7 business days and replaces what is already in the book,
    // including hand corrections.
    if (refrescar && !window.confirm(
      'Correr y sobrescribir: vuelve a leer los últimos 7 días hábiles y '
      + 'REEMPLAZA lo que ya esté en el libro para esas fechas, incluidas '
      + 'las correcciones hechas a mano. ¿Continuar?')) return;
    setEcoExtraer('');
    const r = await apiSend('/api/spp/extraer', 'POST', { refrescar });
    if (!r.ok) { setEcoExtraer({ ok: false, texto: r.data.motivo || `Error ${r.status}` }); return; }
    iniciar('extraccion SBS', alTerminarTarea());
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
  // Gate for the write buttons: an empty box means DELETE server-side, so
  // registering must be impossible while the boxes are unfilled because the
  // preload is in flight or failed - not because the operator emptied them.
  const [rPrecarga, setRPrecarga] = useState('cargando');   // cargando | ok | error

  const nombres = (cfg?.afps || []).map((a) => a.nombre);
  const fondosDe = (afp) => fondosDeCfg(cfg, afp);

  useEffect(() => {
    apiGet('/api/spp/config').then((c) => {
      setCfg(c);
      setRAfp(c.casa || c.afps[0]?.nombre || '');
    }).catch(() => {});
    setRFecha(hoyLocal());
    cargarEstado();
    cargarProgramado();
  }, []);

  // Preload the fund boxes with what the book already holds (±12 days for
  // the neighboring closes), like the monitor's verDato().
  // The boxes are CLEARED synchronously on every selection change: stale
  // values from the previous AFP/date must never be submittable against the
  // new one, and a late response from an old selection must not land either.
  useEffect(() => {
    if (!cfg || !rFecha || !rAfp) return undefined;
    const fondos = fondosDe(rAfp);
    setRValores(Object.fromEntries(fondos.map((fo) => [fo, ''])));
    setRActual(`${rAfp} · ${nombreMetrica(cfg, rMetrica)} · ${fFecha(rFecha)} — cargando…`);
    setRVecinos({ fondos, fechas: [], series: {} });
    // The previous write's result does not describe the new selection: a
    // "✓ 3 valores guardados · Habitat · 01/09" left sitting under the
    // buttons reads as if it applied to whatever is on screen now.
    setRMensaje(null);
    setRPrecarga('cargando');
    let vigente = true;

    const desde = new Date(`${rFecha}T00:00:00`); desde.setDate(desde.getDate() - 12);
    const hasta = new Date(`${rFecha}T00:00:00`); hasta.setDate(hasta.getDate() + 12);
    Promise.all(fondos.map(async (fo) => {
      const q = new URLSearchParams({
        fondo: String(fo), afps: rAfp, metrica: rMetrica,
        desde: desde.toISOString().slice(0, 10), hasta: hasta.toISOString().slice(0, 10),
      });
      const d = await apiGet(`/api/spp/serie?${q}`);
      return [fo, d.series?.[0]?.puntos || []];
    })).then((pares) => {
      if (!vigente) return;
      const series = Object.fromEntries(pares);
      const vals = {}; let cargados = 0;
      fondos.forEach((fo) => {
        const hit = series[fo].find((p) => p[0] === rFecha);
        vals[fo] = hit ? String(hit[1]) : '';
        if (hit) cargados++;
      });
      setRValores(vals);
      setRActual(cargados
        ? `${rAfp} · ${nombreMetrica(cfg, rMetrica)} · ${fFecha(rFecha)} — ${cargados} de ${fondos.length} fondos ya registrados.`
        : `${rAfp} · ${nombreMetrica(cfg, rMetrica)} · ${fFecha(rFecha)} — sin datos ese día.`);
      const fechas = [...new Set(fondos.flatMap((fo) => series[fo].map((p) => p[0])))]
        .sort().slice(-9).reverse();
      setRVecinos({ fondos, fechas, series });
      setRPrecarga('ok');
    }).catch(() => {
      if (!vigente) return;
      setRPrecarga('error');
      setRActual('No se pudo leer el libro para precargar; el registro queda bloqueado hasta reconectar.');
    });
    return () => { vigente = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cfg, rFecha, rAfp, rMetrica, rTick]);

  // {fondo: null|Number}: an empty box is a DELETE, an absent fund is left
  // alone. (This used to be shared with the manual benchmark form, which no
  // longer exists - benchmark levels are calculated, never keyed in.)
  const construirValores = (fondos, valores, vaciarTodo) => Object.fromEntries(
    fondos.map((fo) => {
      const v = String(valores[fo] ?? '').trim();
      return [fo, vaciarTodo ? null : (v === '' ? null : Number(v))];
    }));

  const registrar = async (vaciarTodo) => {
    if (!vaciarTodo && !Object.values(rValores).some((v) => String(v).trim() !== '')) {
      setRMensaje({ ok: false, texto: 'No hay ningún valor escrito. Para borrar la fecha usa «Anular la fecha».' });
      return;
    }
    if (vaciarTodo && !window.confirm(
      `Anular ${rAfp} · ${nombreMetrica(cfg, rMetrica)} · ${fFecha(rFecha)}: borra los valores de todos sus fondos en esa fecha. ¿Continuar?`)) return;
    const valores = construirValores(fondosDe(rAfp), rValores, vaciarTodo);
    const r = await apiSend('/api/spp/valor', 'POST', {
      fecha: rFecha, afp: rAfp, metrica: rMetrica, valores,
    });
    if (!r.ok) { setRMensaje({ ok: false, texto: r.data.motivo || `Error ${r.status}` }); return; }
    const x = r.data.resultado;
    const guardados = Object.keys(x.guardados).length;
    setRMensaje({
      ok: true,
      texto: `${guardados} valor(es) guardados`
        + (x.borrados.length ? ` · ${x.borrados.length} borrados` : '')
        + ` · ${x.afp} · ${nombreMetrica(cfg, x.metrica)} · ${fFecha(x.fecha)}`
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
      setHEco({ ok: false, texto: r.data.motivo || `Error ${r.status}` });
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
    if (!r.ok) { setHEco({ ok: false, texto: r.data.motivo || `Error ${r.status}` }); return; }
    setHEco({ ok: true, texto: 'Guardando en la base…' });
    iniciar(`carga historica (${modo})`, alTerminarTarea((t) => {
      if (t.error) {
        setHEco({ ok: false, texto: 'La carga falló y no se guardó nada nuevo. Puedes reintentar sin volver a subir el archivo.' });
      } else {
        setHEco({ ok: true, texto: `Cargado en modo ${modo === 'faltantes' ? 'solo lo que falta' : 'corregir'}.` });
        setHVale(null);
      }
    }));
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

  // ---- benchmark: serie calculada (solo lectura) ----
  // The level series is CALCULATED from the composition since the
  // 2026-09 redesign; nothing loads benchmark levels by hand anymore.
  const [bEstado, setBEstado] = useState(null);

  const cargarBench = () =>
    apiGet('/api/spp/benchmark').then((j) => setBEstado(j.estado)).catch(() => {});

  // ---- series manuales (componentes fuera de Bloomberg) ----
  const [smSeries, setSmSeries] = useState([]);
  const [smSel, setSmSel] = useState(null);
  const [smNombre, setSmNombre] = useState('');
  const [smDesc, setSmDesc] = useState('');
  const [smMoneda, setSmMoneda] = useState('');
  const [smFecha, setSmFecha] = useState('');
  const [smValor, setSmValor] = useState('');
  const [smPuntos, setSmPuntos] = useState([]);
  const [smEco, setSmEco] = useState('');
  const smRef = useRef(null);
  const [smArchivo, setSmArchivo] = useState('Ningún archivo seleccionado');
  const [smInforme, setSmInforme] = useState(null);
  const [smCargado, setSmCargado] = useState(false);

  const smSerie = smSeries.find((s) => s.serie_id === smSel) || null;

  const cargarSeriesManuales = () =>
    apiGet('/api/spp/series-manuales').then((j) => {
      const lista = j.series || [];
      setSmSeries(lista);
      setSmSel((prev) => (lista.some((s) => s.serie_id === prev)
        ? prev : (lista[0]?.serie_id ?? null)));
    }).catch(() => {});

  const verPuntos = async (id) => {
    if (id == null) { setSmPuntos([]); return; }
    try {
      const j = await apiGet(`/api/spp/series-manuales/${id}/datos`);
      setSmPuntos(j.puntos || []);
    } catch { setSmPuntos([]); }
  };

  useEffect(() => { if (cfg) { setSmFecha(hoyLocal()); cargarSeriesManuales(); } }, [cfg]); // eslint-disable-line react-hooks/exhaustive-deps
  // Changing the selected series invalidates a review made against another
  // one: the file stays in the input, but its report and its load buttons
  // belong to the series it was reviewed for. Without this, reviewing
  // against A and then switching to B wrote A's file into B unreviewed.
  //
  // The echo is deliberately NOT cleared here: registering or deleting a
  // series changes the selection itself, so clearing it would erase the
  // confirmation of the very action that moved it. Each action clears the
  // echo when it starts.
  useEffect(() => {
    verPuntos(smSel);
    setSmInforme(null);
    setSmCargado(false);
    if (smRef.current) smRef.current.value = '';
    setSmArchivo('Ningún archivo seleccionado');
  }, [smSel]); // eslint-disable-line react-hooks/exhaustive-deps

  const crearSerie = async () => {
    setSmEco('');
    const r = await apiSend('/api/spp/series-manuales', 'POST',
      { nombre: smNombre, descripcion: smDesc, moneda: smMoneda });
    if (!r.ok) { setSmEco({ ok: false, texto: r.data.motivo || `Error ${r.status}` }); return; }
    setSmEco({ ok: true, texto: `Serie «${r.data.serie.nombre}» registrada. Ya puede recibir valores y entrar a la canasta.` });
    setSmNombre(''); setSmDesc(''); setSmMoneda('');
    await cargarSeriesManuales();
    setSmSel(r.data.serie.serie_id);
    cargarCatalogoFx();
  };

  const borrarSerieManual = async () => {
    if (!smSerie) return;
    setSmEco('');
    if (!window.confirm(
      `Borrar la serie «${smSerie.nombre}»${smSerie.puntos ? ` con sus ${smSerie.puntos} valor(es)` : ''}. ¿Continuar?`)) return;
    const r = await apiSend(`/api/spp/series-manuales/${smSerie.serie_id}?datos=1`, 'DELETE');
    setSmEco(r.ok
      ? { ok: true, texto: `Serie «${smSerie.nombre}» borrada.` }
      : { ok: false, texto: r.data.motivo || `Error ${r.status}` });
    cargarSeriesManuales();
    cargarCatalogoFx();
  };

  const registrarPunto = async (borrar) => {
    setSmEco('');
    if (!smSerie) { setSmEco({ ok: false, texto: 'Elige una serie primero.' }); return; }
    if (!smFecha) { setSmEco({ ok: false, texto: 'Falta la fecha.' }); return; }
    if (!borrar && String(smValor).trim() === '') {
      setSmEco({ ok: false, texto: 'Falta el valor. Para quitar un dato usa «Borrar la fecha».' }); return;
    }
    if (borrar && !window.confirm(
      `Borrar el valor del ${fFecha(smFecha)} en «${smSerie.nombre}». ¿Continuar?`)) return;
    const r = await apiSend(`/api/spp/series-manuales/${smSerie.serie_id}/valores`, 'POST',
      { valores: { [smFecha]: borrar ? null : Number(smValor) } });
    if (!r.ok) { setSmEco({ ok: false, texto: r.data.motivo || `Error ${r.status}` }); return; }
    const x = r.data.resultado;
    setSmEco({ ok: true, texto: `«${x.nombre}»: ${x.escritos} valor(es) escritos, ${x.borrados} borrados.` });
    setSmValor('');
    cargarSeriesManuales(); verPuntos(smSerie.serie_id);
  };

  const subirSerie = async (revisar, refrescar) => {
    const a = smRef.current?.files?.[0];
    if (!a) { setSmEco({ ok: false, texto: 'Elige un archivo primero.' }); return; }
    if (!smSerie) { setSmEco({ ok: false, texto: 'Elige una serie primero.' }); return; }
    if (!revisar && refrescar && !window.confirm(
      'Cargar y corregir: además de agregar lo que falta, reemplaza los valores ya cargados con los del archivo. ¿Continuar?')) return;
    setSmArchivo(`${a.name} · ${revisar ? 'revisando…' : 'cargando…'}`);
    const fd = new FormData();
    fd.append('archivo', a);
    if (revisar) fd.append('revisar', '1');
    if (refrescar) fd.append('refrescar', '1');
    const r = await apiSend(`/api/spp/series-manuales/${smSerie.serie_id}/archivo`, 'POST', fd, true);
    if (!r.ok) {
      setSmArchivo(a.name);
      setSmInforme(null);
      setSmEco({ ok: false, texto: r.data.motivo || `Error ${r.status}` });
      return;
    }
    setSmArchivo(`${a.name} · ${revisar ? 'revisado, nada escrito todavía' : 'cargado'}`);
    setSmInforme({ ...r.data.informe, cargado: !revisar, serie: smSerie.nombre });
    setSmCargado(!revisar);
    if (!revisar) { cargarSeriesManuales(); verPuntos(smSerie.serie_id); }
  };

  const filasInformeSm = (i) => {
    const lectura = i.origen === 'excel'
      ? `Excel · hoja «${i.hoja || '—'}»`
      : `CSV, separador «${i.separador}» · decimales con ${i.decimal}`;
    const f = [
      ['Archivo', i.archivo || '—'],
      ['Serie destino', i.serie || '—'],
      ['Lectura', lectura],
      ['Contenido', `${nEnt(i.filas)} fechas`],
      ['Rango', `${fFecha(i.desde)} a ${fFecha(i.hasta)}`],
    ];
    if (i.cargado) {
      f.push(['Fechas nuevas', nEnt(i.nuevas)]);
      f.push(['Fechas actualizadas', nEnt(i.actualizadas)]);
      f.push(['Sin cambio', nEnt(i.sin_cambio)]);
    }
    return f;
  };

  // ---- benchmark: composicion (canasta versionada) ----
  const [cFondo, setCFondo] = useState(1);
  const [cFecha, setCFecha] = useState('');
  const [cComponentes, setCComponentes] = useState([]);
  const [cBusqueda, setCBusqueda] = useState('');
  const [cResultados, setCResultados] = useState(null);
  const [cCatalogoFx, setCCatalogoFx] = useState(null);
  const [composiciones, setComposiciones] = useState([]);
  const [cEco, setCEco] = useState('');

  const cargarComposiciones = () =>
    apiGet('/api/spp/benchmark/composicion').then((j) => setComposiciones(j.composiciones || [])).catch(() => {});

  // Small always-loaded catalog for the optional FX leg selects; also
  // refreshed when a manual series is created or deleted.
  const cargarCatalogoFx = () =>
    apiGet('/api/spp/benchmark/series-disponibles').then(setCCatalogoFx).catch(() => {});

  useEffect(() => {
    if (!cfg) return;
    setCFecha(hoyLocal());
    cargarComposiciones();
    cargarCatalogoFx();
    cargarBench();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cfg]);

  const buscarSeries = async () => {
    try {
      setCResultados(await apiGet(`/api/spp/benchmark/series-disponibles?q=${encodeURIComponent(cBusqueda)}`));
    } catch { setCResultados(null); }
  };

  const agregarComponente = (fuente, s) => {
    if (cComponentes.some((c) => c.fuente === fuente && c.ref_id === s.ref_id)) return;
    setCComponentes([...cComponentes,
      { etiqueta: s.etiqueta, fuente, ref_id: s.ref_id, peso: '', fx: '' }]);
  };

  const sumaPesos = cComponentes.reduce((a, c) => a + (Number(c.peso) || 0), 0);
  const sumaOk = Math.abs(sumaPesos - 1) < 1e-6 || Math.abs(sumaPesos - 100) < 1e-4;

  const guardarComposicion = async () => {
    setCEco('');
    const componentes = cComponentes.map((c) => {
      const fx = c.fx ? JSON.parse(c.fx) : null;
      return {
        etiqueta: c.etiqueta, fuente: c.fuente, ref_id: c.ref_id,
        peso: Number(c.peso),
        ...(fx ? { fx_fuente: fx.fuente, fx_ref_id: fx.ref_id } : {}),
      };
    });
    const r = await apiSend('/api/spp/benchmark/composicion', 'POST',
      { fondo: cFondo, vigente_desde: cFecha, componentes });
    if (!r.ok) { setCEco({ ok: false, texto: r.data.motivo || `Error ${r.status}` }); return; }
    setCEco({ ok: true, texto: `Composición del Fondo ${cFondo} guardada, vigente desde ${fFecha(cFecha)}. Recalcula para regenerar la serie.` });
    cargarComposiciones();
  };

  const borrarComposicion = async (g) => {
    if (!window.confirm(
      `Borrar la composición del Fondo ${g.fondo} vigente desde ${fFecha(g.vigente_desde)}. El siguiente recálculo ya no la usará. ¿Continuar?`)) return;
    const r = await apiSend(
      `/api/spp/benchmark/composicion?fondo=${g.fondo}&vigente_desde=${g.vigente_desde}`, 'DELETE');
    setCEco(r.ok
      ? { ok: true, texto: 'Composición borrada.' }
      : { ok: false, texto: r.data.motivo || `Error ${r.status}` });
    cargarComposiciones();
  };

  const editarComposicion = (g) => {
    setCFondo(g.fondo);
    setCFecha(g.vigente_desde);
    setCComponentes(g.componentes.map((c) => ({
      etiqueta: c.etiqueta, fuente: c.fuente, ref_id: c.ref_id,
      peso: String(c.peso),
      fx: c.fx_ref_id ? JSON.stringify({ fuente: c.fx_fuente, ref_id: c.fx_ref_id }) : '',
    })));
    setCEco({ ok: true, texto: `Editando la composición vigente desde ${fFecha(g.vigente_desde)}; guardar la reemplaza en esa fecha.` });
  };

  const recalcularBench = async () => {
    if (!window.confirm(
      `Recalcular el benchmark del Fondo ${cFondo} desde sus composiciones REEMPLAZA la serie completa almacenada (base 100 en el primer rebalanceo). ¿Continuar?`)) return;
    const r = await apiSend('/api/spp/benchmark/recalcular', 'POST', { fondo: cFondo });
    if (!r.ok) { setCEco({ ok: false, texto: r.data.motivo || `Error ${r.status}` }); return; }
    // The task's own bitácora is rendered in this area too, but the result
    // has to be SAID here: before this, a failed recalculation looked
    // exactly like a successful one - the button dimmed and came back.
    setCEco({ ok: true, texto: `Recalculando el benchmark F${cFondo}…` });
    iniciar(`recalculo del benchmark F${cFondo}`, alTerminarTarea((t) => {
      cargarBench();
      setCEco(t.error
        ? { ok: false, texto: `El recálculo falló y la serie anterior sigue intacta: ${t.error}` }
        : { ok: true, texto: `Benchmark F${cFondo} recalculado desde sus composiciones.` });
    }));
  };

  // The benchmark builds from the TWO component bases: the Bloomberg
  // registry and the manual series (the backend still accepts 'fact'
  // for compositions saved before the redesign).
  const opcionesFx = ['bloomberg', 'manual'].flatMap((fu) =>
    (cCatalogoFx?.[fu] || []).map((s) => ({
      v: JSON.stringify({ fuente: fu, ref_id: s.ref_id }),
      t: `${s.etiqueta} (${nombreFuente(fu)})`,
    })));

  // ---- corrida automatica render ----
  // 267009 = la tarea sigue corriendo; 0 = terminó bien. Cualquier otro
  // código significa que el proceso murió antes de dejar su propio rastro,
  // que es justo el caso que este cuadro leía como «correcta».
  const EN_CURSO = 267009;
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
      if (t.ultima) filas.push(['Último lanzamiento (Windows)', fHora(t.ultima)]);
    }
    if (u.inicio) {
      filas.push(['Última corrida', `${fHora(u.inicio)} · ${u.segundos || 0} s`]);
      filas.push(['Resultado', u.ok !== false
        ? `correcta · ${u.cargadas || 0} observación(es) nuevas en ${u.fechas || 0} fecha(s)`
        : `falló${u.error ? ` · ${u.error}` : ''}`]);
    } else filas.push(['Última corrida', 'todavía ninguna']);
    return filas;
  };

  // Windows lanzó la tarea y el pipeline no alcanzó a escribir su rastro:
  // sin esto, el cuadro seguía mostrando la corrida buena anterior.
  const lanzamientoMudo = () => {
    const t = prog?.tarea || {}; const u = prog?.ultima || {};
    if (!t.registrada || !t.ultima) return null;
    if (t.resultado === EN_CURSO || t.resultado === 0 || t.resultado == null) return null;
    if (u.inicio && new Date(u.inicio) >= new Date(t.ultima)) return null;
    return `La última corrida lanzada por Windows (${fHora(t.ultima)}) terminó con `
      + `código ${t.resultado} sin dejar rastro propio.`;
  };

  // La tarea guarda la ruta absoluta del proyecto: con el zip es fácil
  // terminar con dos copias y que la automatización trabaje sobre la vieja.
  const otraCopia = () => (prog?.tarea?.registrada && prog.tarea.apunta_aqui === false
    ? `La tarea programada apunta a otra copia del proyecto (${prog.tarea.ejecutable}). `
      + 'Vuelve a registrarla desde esta carpeta.'
    : null);

  const metricaPaso = rMetrica === 'valor_cuota' ? '0.0000001' : '0.01';

  return (
    <div>
      <h1 className="page-title">Valor Cuota SPP</h1>
      <p className="page-sub">Registro y carga · a la izquierda se actúa, a la derecha se ve.
        Ningún archivo llega a la base sin haberse mostrado antes.</p>
      <SppTabs />

      {/* Three work areas, one visible at a time. All the state lives in
          this component, so switching areas loses nothing typed. */}
      <div className="controls spp-controls" style={{ margin: '12px 0 16px' }}>
        <div className="field"><label>Área</label>
          <SppSeg items={AREAS} value={seccion} onChange={setSeccion} /></div>
      </div>

      {seccion === 'vc' && (<>
      {/* ===== 1 · Registro manual de valor cuota ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Valor cuota · registro manual</div>
          <p className="page-sub">Una AFP y una fecha, sus fondos a la vez. Los cuadros se
            precargan con lo que ya hay: escribir uno lo reemplaza y <b>dejarlo vacío borra
            ese dato</b>. Si la fecha queda sin ningún valor, sale del libro.</p>
          <div className="controls spp-controls">
            <div className="field"><label htmlFor="r-fecha">Fecha</label>
              <input id="r-fecha" className="date-input" type="date" value={rFecha}
                onChange={(e) => setRFecha(e.target.value)} /></div>
            <div className="field"><label htmlFor="r-afp">AFP</label>
              <select id="r-afp" className="select" value={rAfp} onChange={(e) => setRAfp(e.target.value)}>
                {nombres.map((a) => <option key={a} value={a}>{a}</option>)}
              </select></div>
            <div className="field"><label htmlFor="r-metrica">Métrica</label>
              <select id="r-metrica" className="select" value={rMetrica}
                onChange={(e) => setRMetrica(e.target.value)}>
                {metricasDe(cfg).map(([et, v]) => <option key={v} value={v}>{et}</option>)}
              </select></div>
          </div>
          <div className="controls spp-controls" style={{ marginTop: 10 }}>
            {fondosDe(rAfp).map((fo) => (
              <div className="field" key={fo}><label htmlFor={`r-fondo-${fo}`}>Fondo {fo}</label>
                <input id={`r-fondo-${fo}`} className="date-input" type="number" min="0"
                  step={metricaPaso}
                  placeholder={rMetrica === 'valor_cuota' ? '0.0000000' : '0.00'}
                  value={rValores[fo] ?? ''}
                  onChange={(e) => setRValores({ ...rValores, [fo]: e.target.value })} /></div>
            ))}
          </div>
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn principal" disabled={rPrecarga !== 'ok' || ocupado}
              title={ocupado ? 'Espera a que termine la operación en curso' : undefined}
              onClick={() => registrar(false)}>Registrar valores</button>
            <button className="btn peligro" disabled={rPrecarga !== 'ok' || ocupado}
              title={ocupado ? 'Espera a que termine la operación en curso' : undefined}
              onClick={() => registrar(true)}>Anular la fecha</button>
          </div>
          <Eco eco={rMensaje} />
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

      {/* ===== 2 · Extracción diaria ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Valor cuota · extracción diaria</div>
          <p className="page-sub">Lee la página de variables SPP (últimos 7 días hábiles) e
            inserta solo lo que falta, con las tres métricas. Es la única carga que corre
            sola. Toma unos 20–90 s.</p>
          <div className="controls">
            <button className="btn principal" disabled={ocupado}
              onClick={() => extraer(false)}>Correr extracción</button>
            <button className="btn peligro" disabled={ocupado}
              onClick={() => extraer(true)}>Correr y sobrescribir</button>
          </div>
          <p className="page-sub flag-warn" style={{ marginTop: 10 }}>
            La SBS está detrás del WAF Imperva: <b>se abrirá una ventana de Chrome</b> en la
            máquina donde corre la API. No la cierres mientras corre.
          </p>
          <Eco eco={ecoExtraer} />

          <div className="panel-title" style={{ marginTop: 14 }}>Corrida automática</div>
          {prog && !prog.tarea?.registrada && prog.tarea?.disponible ? (
            <p className="page-sub">La extracción <b>no corre sola</b> todavía. Para activarla,
              doble clic en{' '}
              <span className="mono">scripts\Programar extraccion SPP.bat</span> — queda diaria
              a las 18:00 (<span className="mono">-Hora 19:30</span> la cambia,{' '}
              <span className="mono">-Quitar</span> la elimina).</p>
          ) : progFilas() ? <Informe filas={progFilas()} /> : <p className="page-sub dim">—</p>}
          {otraCopia() && <p className="page-sub flag-warn">{otraCopia()}</p>}
          {lanzamientoMudo() && <p className="page-sub flag-warn">{lanzamientoMudo()}</p>}
        </div>

        <div className="panel">
          <div className="panel-title">Bitácora</div>
          <Bitacora tarea={tarea} />

          <div className="panel-title" style={{ marginTop: 14 }}>Tramos sin dato</div>
          <p className="page-sub">Días hábiles consecutivos sin valor cuota. Los tramos de 1–2
            días se omiten: son feriados peruanos, no información faltante.</p>
          {(estado?.huecos || []).length ? (
            <Informe filas={estado.huecos.map((h) =>
              [`${fFecha(h.desde)} a ${fFecha(h.hasta)}`, `${h.dias} d.h.`])} />
          ) : <p className="page-sub dim">Sin tramos abiertos.</p>}
        </div>
      </div>

      {/* ===== 3 · Carga histórica por Excel ===== */}
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
                  <button className="btn principal" disabled={ocupado}
                    onClick={() => cargarHistorico('faltantes')}>Cargar lo que falta</button>
                  <button className="btn peligro" disabled={ocupado}
                    onClick={() => cargarHistorico('sobrescribir')}>Cargar y corregir</button>
                </div>
              )}
            </>
          )}
          <Eco eco={hEco} />
          <div className="controls" style={{ marginTop: 12 }}>
            <a className="btn" target="_blank" rel="noreferrer"
              href="https://www.sbs.gob.pe/app/stats/EstadisticaSistemaFinancieroResultadosHist.asp?c=FP-130706&Y=0">
              Abrir la página de la SBS</a>
            <a className="btn" href={apiUrl('/api/spp/exportar')}>↓ Bajar todo el libro · CSV</a>
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

      </>)}

      {seccion === 'series' && (<>
      {/* ===== 4 · Series manuales: componentes fuera de Bloomberg ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Series manuales · componentes fuera de Bloomberg</div>
          <p className="page-sub">La segunda base de componentes del benchmark: lo que Bloomberg
            no trae se registra aquí como serie y se le cargan precios a mano o por Excel
            (columnas <b>fecha</b> y <b>valor</b>). El archivo nunca borra; borrar es siempre
            un acto manual por fecha.</p>

          <div className="controls spp-controls">
            <div className="field"><label htmlFor="sm-nombre">Nueva serie</label>
              <input id="sm-nombre" className="date-input" placeholder="Nombre (p. ej. Índice X)"
                value={smNombre} onChange={(e) => setSmNombre(e.target.value)} /></div>
            <div className="field"><label htmlFor="sm-desc">Descripción</label>
              <input id="sm-desc" className="date-input" placeholder="opcional"
                value={smDesc} onChange={(e) => setSmDesc(e.target.value)} /></div>
            <div className="field"><label htmlFor="sm-moneda">Moneda</label>
              <input id="sm-moneda" className="date-input" placeholder="USD / PEN"
                style={{ width: 90 }}
                value={smMoneda} onChange={(e) => setSmMoneda(e.target.value)} /></div>
            <div className="field"><label aria-hidden="true">&nbsp;</label>
              <button className="btn principal" disabled={!smNombre.trim() || ocupado}
                onClick={crearSerie}>Registrar serie</button></div>
          </div>
          <p className="page-sub dim">Registrar una serie con un nombre que ya existe actualiza
            su descripción y moneda; no la duplica.</p>

          <div className="controls spp-controls" style={{ marginTop: 12 }}>
            <div className="field"><label htmlFor="sm-serie">Serie</label>
              <select id="sm-serie" className="select" value={smSel ?? ''}
                onChange={(e) => setSmSel(e.target.value ? Number(e.target.value) : null)}>
                {!smSeries.length && <option value="">— registra una serie primero —</option>}
                {smSeries.map((s) => (
                  <option key={s.serie_id} value={s.serie_id}>
                    {s.nombre}{s.moneda ? ` · ${s.moneda}` : ''}</option>
                ))}
              </select></div>
            <div className="field"><label htmlFor="sm-fecha">Fecha</label>
              <input id="sm-fecha" className="date-input" type="date" value={smFecha}
                onChange={(e) => setSmFecha(e.target.value)} /></div>
            <div className="field"><label htmlFor="sm-valor">Valor</label>
              <input id="sm-valor" className="date-input" type="number" min="0" step="0.0001"
                placeholder="0.0000" value={smValor}
                onChange={(e) => setSmValor(e.target.value)} /></div>
          </div>
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn principal" disabled={!smSerie || ocupado}
              onClick={() => registrarPunto(false)}>Registrar valor</button>
            <button className="btn peligro" disabled={!smSerie || ocupado}
              onClick={() => registrarPunto(true)}>Borrar la fecha</button>
            <button className="btn peligro" disabled={!smSerie || ocupado}
              onClick={borrarSerieManual}>Borrar la serie</button>
          </div>

          <div className="controls" style={{ marginTop: 12 }}>
            <input ref={smRef} type="file" accept=".xlsx,.xls,.csv" className="date-input"
              aria-label="Archivo de valores para la serie"
              onChange={() => subirSerie(true, false)} />
            <span className="page-sub" style={{ margin: 0 }}>{smArchivo}</span>
          </div>
          {smInforme && !smCargado && (
            <div className="controls" style={{ marginTop: 12 }}>
              <button className="btn principal" disabled={ocupado}
                onClick={() => subirSerie(false, false)}>Cargar lo que falta</button>
              <button className="btn peligro" disabled={ocupado}
                onClick={() => subirSerie(false, true)}>Cargar y corregir</button>
            </div>
          )}
          <div className="controls" style={{ marginTop: 12 }}>
            <a className="btn" href={apiUrl('/api/spp/series-manuales/plantilla')}>↓ Plantilla · XLSX</a>
            {smSerie && (
              <a className="btn" href={apiUrl(`/api/spp/series-manuales/${smSerie.serie_id}/exportar`)}>
                ↓ Bajar «{smSerie.nombre}» · XLSX</a>
            )}
          </div>
          <Eco eco={smEco} />
        </div>

        <div className="panel">
          <div className="panel-title">En la base</div>
          {smSeries.length ? (
            <Informe filas={smSeries.map((s) => [
              `${s.nombre}${s.moneda ? ` · ${s.moneda}` : ''}${s.usos ? ' · en la canasta' : ''}`,
              s.puntos
                ? `${nEnt(s.puntos)} fechas · ${fFecha(s.desde)} a ${fFecha(s.hasta)} · último ${s.ultimo}`
                : 'sin datos todavía',
            ])} />
          ) : (
            <p className="page-sub">Todavía no hay ninguna serie manual. Crea una a la
              izquierda y cárgale precios; después podrás sumarla a la canasta del benchmark.</p>
          )}

          {smInforme && (
            <div style={{ marginTop: 12 }}>
              <div className="panel-title">Vista previa del archivo</div>
              <Informe filas={filasInformeSm(smInforme)} />
              {(smInforme.avisos || []).map((a, i) => (
                <p key={i} className="page-sub">Aviso: {a}</p>
              ))}
              {smInforme.total_omitidas > 0 && (
                <p className="page-sub flag-warn">Se omitieron <b>{smInforme.total_omitidas}</b> fila(s):{' '}
                  {smInforme.omitidas.slice(0, 5).map((o) => `línea ${o.linea} (${o.motivo})`).join('; ')}
                  {smInforme.total_omitidas > 5 ? '; …' : ''}</p>
              )}
              <Muestra muestra={smInforme.muestra}
                titulo={smCargado ? 'Últimas filas cargadas' : 'Últimas filas del archivo'} />
            </div>
          )}

          {smSerie && smPuntos.length > 0 && !smInforme && (
            <div style={{ marginTop: 12 }}>
              <div className="panel-title">Últimos valores de «{smSerie.nombre}»</div>
              <div className="table-wrap" style={{ maxHeight: 260, overflowY: 'auto' }}>
                <table>
                  <thead><tr><th>Fecha</th><th className="num">Valor</th></tr></thead>
                  <tbody>
                    {smPuntos.slice(-15).reverse().map((p) => (
                      <tr key={p.fecha}>
                        <td>{fFecha(p.fecha)}</td>
                        <td className="num">{Number(p.valor).toLocaleString('es-PE',
                          { minimumFractionDigits: 2, maximumFractionDigits: 7 })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>

      </>)}

      {seccion === 'benchmark' && (<>
      {/* ===== 5 · Benchmark: composición de la canasta ===== */}
      <div className="spp-dos">
        <div className="panel">
          <div className="panel-title">Benchmark · composición de la canasta</div>
          <p className="page-sub">El benchmark de cada fondo se <b>construye</b> desde las dos
            bases de componentes (Bloomberg y series manuales): una canasta de series con pesos,
            <b> versionada por fecha</b>: cambiar tickers o pesos crea una composición nueva desde
            su fecha de vigencia, sin tocar la historia. Entre rebalanceos los pesos <b>derivan </b>
            con los precios (buy-and-hold). Recalcular regenera la serie completa (base 100 en el
            primer rebalanceo). Los niveles nunca se cargan a mano.</p>
          <p className="page-sub dim">Los componentes salen de las dos bases: los de Bloomberg se
            administran en la pestaña <b>Series Bloomberg</b>; los demás, en el área
            <b> Series manuales</b> de aquí al lado.</p>

          <div className="controls spp-controls">
            <div className="field"><label>Tipo de fondo</label>
              <SppSeg items={(cfg?.fondos_benchmark || []).map((f) => [`Fondo ${f}`, f])}
                value={cFondo} onChange={setCFondo} /></div>
            <div className="field"><label htmlFor="c-fecha">Vigente desde</label>
              <input id="c-fecha" className="date-input" type="date" value={cFecha}
                onChange={(e) => setCFecha(e.target.value)} /></div>
          </div>

          <div className="controls" style={{ marginTop: 10 }}>
            <input className="date-input" placeholder="Buscar serie (ticker, nombre)…"
              aria-label="Buscar serie en las dos bases"
              value={cBusqueda} onChange={(e) => setCBusqueda(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && buscarSeries()} />
            <button className="btn" onClick={buscarSeries}>Buscar</button>
          </div>
          {cResultados && (
            <div className="table-wrap" style={{ maxHeight: 180, overflowY: 'auto', marginTop: 8 }}>
              <table><tbody>
                {['bloomberg', 'manual'].flatMap((fu) => (cResultados[fu] || []).map((s) => (
                  <tr key={`${fu}-${s.ref_id}`}>
                    <td className="mono">{s.etiqueta}</td>
                    <td className="dim">{nombreFuente(fu)} · {s.detalle}</td>
                    <td><button className="btn" onClick={() => agregarComponente(fu, s)}>+ Agregar</button></td>
                  </tr>
                )))}
                {!(cResultados.bloomberg?.length || cResultados.manual?.length) && (
                  <tr><td className="dim">Sin resultados en las dos bases (Bloomberg y manuales).</td></tr>
                )}
              </tbody></table>
            </div>
          )}

          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead><tr><th>Componente</th><th>Fuente</th><th className="num">Peso</th>
                <th>FX (opcional)</th><th></th></tr></thead>
              <tbody>
                {cComponentes.length ? cComponentes.map((c, i) => (
                  <tr key={`${c.fuente}-${c.ref_id}`}>
                    <td className="mono">{c.etiqueta}</td>
                    <td className="dim">{nombreFuente(c.fuente)}</td>
                    <td className="num">
                      <input className="date-input" type="number" min="0" step="0.01"
                        style={{ width: 90 }} value={c.peso}
                        onChange={(e) => setCComponentes(
                          cComponentes.map((x, j) => (j === i ? { ...x, peso: e.target.value } : x)))} />
                    </td>
                    <td>
                      <select className="select" value={c.fx}
                        onChange={(e) => setCComponentes(
                          cComponentes.map((x, j) => (j === i ? { ...x, fx: e.target.value } : x)))}>
                        <option value="">— sin conversión —</option>
                        {opcionesFx.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
                      </select>
                    </td>
                    <td><button className="btn peligro"
                      onClick={() => setCComponentes(cComponentes.filter((_, j) => j !== i))}>Quitar</button></td>
                  </tr>
                )) : <tr><td colSpan={5} className="dim">Busca series y agrégalas a la canasta.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="page-sub">Suma de pesos: <b className={sumaOk ? 'pos' : 'neg'}>
            {sumaPesos.toLocaleString('es-PE', { maximumFractionDigits: 4 })}</b> (debe ser 1 o 100)</p>

          <div className="controls">
            <button className="btn principal" disabled={!cComponentes.length || !sumaOk || !cFecha || ocupado}
              onClick={guardarComposicion}>Guardar composición</button>
            <button className="btn" disabled={ocupado} onClick={recalcularBench}>
              Recalcular benchmark Fondo {cFondo}</button>
          </div>
          <Eco eco={cEco} />
          {/* La bitácora vive también aquí: el recálculo corre en la misma
              tarea de fondo, y su rastro estaba solo en el área de valor cuota. */}
          {tarea && <Bitacora tarea={tarea} />}
        </div>

        <div className="panel">
          <div className="panel-title">Serie calculada</div>
          <p className="page-sub">
            {bEstado?.filas
              ? `${nEnt(bEstado.filas)} fechas · ${fFecha(bEstado.desde)} a ${fFecha(bEstado.hasta)}`
              : 'Todavía no hay serie calculada: declara una composición y recalcula.'}
          </p>
          {bEstado?.series?.length > 0 && (
            <Informe filas={bEstado.series.map((x) => [
              `Fondo ${x.fondo}`,
              x.puntos ? `${nEnt(x.puntos)} fechas · último ${x.valor} el ${fFecha(x.fecha)}` : 'sin datos',
            ])} />
          )}
          {bEstado?.filas > 0 && (
            <div className="controls" style={{ marginBottom: 12 }}>
              <a className="btn" href={apiUrl('/api/spp/benchmark/exportar')}>↓ Bajar la serie · XLSX</a>
            </div>
          )}

          <div className="panel-title">Historial de composiciones</div>
          <p className="page-sub">Cada fila es un rebalanceo vigente desde su fecha. Editar una
            composición la carga en el editor; guardarla reemplaza <b>solo esa fecha</b>.</p>
          {composiciones.length ? composiciones.map((g) => (
            <div key={`${g.fondo}-${g.vigente_desde}`} style={{ marginBottom: 12 }}>
              <div className="panel-title" style={{ fontSize: 13 }}>
                Fondo {g.fondo} · desde {fFecha(g.vigente_desde)}</div>
              <Informe filas={g.componentes.map((c) => [
                `${c.etiqueta}${c.fx_ref_id ? ' (con FX)' : ''}`,
                `${(c.peso * 100).toLocaleString('es-PE', { maximumFractionDigits: 2 })} %`,
              ])} />
              <div className="controls" style={{ marginTop: 6 }}>
                <button className="btn" onClick={() => editarComposicion(g)}>Editar</button>
                <button className="btn peligro" onClick={() => borrarComposicion(g)}>Borrar</button>
              </div>
            </div>
          )) : <p className="page-sub dim">Ninguna composición declarada todavía.</p>}
        </div>
      </div>
      </>)}
    </div>
  );
}
