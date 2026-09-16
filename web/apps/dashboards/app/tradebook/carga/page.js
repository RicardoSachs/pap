// web/apps/dashboards/app/tradebook/carga/page.js
// ---------------------------------------------------------------------------
// Tradebook · Registro y carga. Tres maneras de meter operaciones, en tres
// segmentos, más el libro de lo cargado para corregir o anular.
//
// El orden no es casual: primero el archivo, que es como entra el grueso;
// después la captura a mano, que es la excepción; y al final la derivación
// desde posiciones, que es la más delicada y por eso la que menos a la vista
// está. Ninguna de las tres guarda nada sin haber mostrado antes lo que va a
// guardar.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';

import Eco from '../../../components/Eco';
import SppSeg from '../../../components/SppSeg';
import TradebookTabs from '../../../components/TradebookTabs';
import useVerTodo from '../../../components/useVerTodo';
import { apiGet } from '../../../lib/api';
import { apiSend, apiUrl, fFecha, nEnt } from '../../../lib/spp';

const SECCIONES = [
  ['Carga por archivo', 'archivo'],
  ['Captura a mano', 'manual'],
  ['Derivar de posiciones', 'posiciones'],
];
const LADOS = [['Compra', 'compra'], ['Venta', 'venta']];
const VACIO = {
  fecha: '', fondo: '2', lado: 'compra', instrumento: '', cantidad: '',
  precio: '', monto: '', moneda: 'PEN', contraparte: '', fecha_liquidacion: '',
  referencia: '', nota: '',
};

export default function TradebookCarga() {
  const [seccion, setSeccion] = useState('archivo');
  const [estado, setEstado] = useState(null);
  const [error, setError] = useState(null);

  const cargarEstado = () => apiGet('/api/tradebook/estado')
    .then(setEstado).catch((e) => setError(e.message));
  useEffect(() => { cargarEstado(); }, []);

  return (
    <div>
      <h1 className="page-title">Tradebook</h1>
      <p className="page-sub">
        Registro y carga
        {estado?.filas
          ? ` · ${nEnt(estado.filas)} operaciones en el libro (${fFecha(estado.desde)} a ${fFecha(estado.hasta)})`
          : ' · el libro está vacío'}
      </p>
      <TradebookTabs />

      {error && <div className="panel error">Error: {error}</div>}

      <div className="panel">
        <div className="controls">
          <div className="field"><label>Cómo entran</label>
            <SppSeg items={SECCIONES} value={seccion} onChange={setSeccion} /></div>
        </div>
      </div>

      {seccion === 'archivo' && <PorArchivo alCargar={cargarEstado} />}
      {seccion === 'manual' && <AMano alCargar={cargarEstado} estado={estado} />}
      {seccion === 'posiciones' && <DesdePosiciones alCargar={cargarEstado} />}

      <Libro estado={estado} alCambiar={cargarEstado} />
    </div>
  );
}


// ---- 1. Carga por archivo --------------------------------------------------

function PorArchivo({ alCargar }) {
  const [archivo, setArchivo] = useState(null);
  const [hoja, setHoja] = useState('');
  const [informe, setInforme] = useState(null);
  const [eco, setEco] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const input = useRef(null);

  // Cambiar de archivo invalida la revisión anterior: confirmar una carga
  // con el informe de OTRO archivo delante es exactamente el error que el
  // paso de revisión existe para evitar.
  const elegir = (f) => { setArchivo(f); setInforme(null); setEco(''); };

  const enviar = async (soloRevisar) => {
    if (!archivo) return;
    setOcupado(true); setEco('');
    const fd = new FormData();
    fd.append('archivo', archivo);
    fd.append('revisar', soloRevisar ? '1' : '');
    fd.append('hoja', hoja);
    const r = await apiSend('/api/tradebook/archivo', 'POST', fd, true);
    setOcupado(false);
    if (!r.ok) { setEco({ ok: false, texto: r.data.motivo }); return; }
    setInforme(r.data.informe);
    if (soloRevisar) {
      setEco({ ok: true, texto: `Revisado: ${r.data.informe.leidas} operación(es) `
        + `legibles, ${r.data.informe.descartadas.length} descartada(s). `
        + 'Nada se ha guardado todavía.' });
    } else {
      const i = r.data.informe;
      setEco({ ok: true, texto: `Cargadas ${i.guardadas} operación(es): `
        + `${i.insertadas} nuevas y ${i.actualizadas} que ya estaban y se actualizaron.` });
      setArchivo(null);
      if (input.current) input.current.value = '';
      alCargar();
    }
  };

  const [descartadas, VerDescartadas] = useVerTodo(informe?.descartadas || [], 8);
  const [muestra, VerMuestra] = useVerTodo(informe?.muestra || [], 10);

  return (
    <div className="panel">
      <div className="panel-title">Carga por archivo</div>
      <p className="page-sub">
        Excel o CSV. Se reconoce por el contenido, no por la extensión, y las
        columnas por su nombre en varios idiomas. Obligatorias: fecha, fondo,
        lado, instrumento, cantidad, y monto o precio.
      </p>

      <div className="controls" style={{ marginTop: 10 }}>
        <a className="btn" href={apiUrl('/api/tradebook/plantilla')}>↓ Plantilla · XLSX</a>
        <input ref={input} type="file" accept=".xlsx,.xls,.csv,.txt"
          onChange={(e) => elegir(e.target.files?.[0] || null)} />
        <input className="text-input" placeholder="Hoja (opcional)"
          value={hoja} onChange={(e) => setHoja(e.target.value)} style={{ width: 160 }} />
      </div>
      <div className="controls" style={{ marginTop: 10 }}>
        <button className="btn" disabled={!archivo || ocupado}
          onClick={() => enviar(true)}>Revisar</button>
        <button className="btn principal" disabled={!archivo || ocupado || !informe?.leidas}
          onClick={() => enviar(false)}>Cargar lo revisado</button>
      </div>
      <Eco eco={eco} />

      {informe && (
        <>
          <table className="spp-informe">
            <tbody>
              <tr><td>Archivo</td><td className="num">{informe.archivo}</td></tr>
              <tr><td>Formato</td><td className="num">{informe.formato}{informe.hoja ? ` · hoja ${informe.hoja}` : ''}</td></tr>
              <tr><td>Operaciones legibles</td><td className="num">{nEnt(informe.leidas)}</td></tr>
              <tr><td>Descartadas</td><td className="num">{nEnt(informe.descartadas?.length || 0)}</td></tr>
              {informe.resumen?.desde && (
                <tr><td>Rango</td><td className="num">
                  {fFecha(informe.resumen.desde)} a {fFecha(informe.resumen.hasta)}</td></tr>
              )}
              {informe.resumen && (
                <>
                  <tr><td>Compras / ventas</td><td className="num">
                    {nEnt(informe.resumen.compras)} / {nEnt(informe.resumen.ventas)}</td></tr>
                  <tr><td>Fondos</td><td className="num">{informe.resumen.fondos.join(', ') || '—'}</td></tr>
                  <tr><td>Monedas</td><td className="num">{informe.resumen.monedas.join(', ') || '—'}</td></tr>
                  {/* Sin referencia no hay forma de distinguir una recarga del
                      mismo archivo de dos operaciones idénticas de verdad. */}
                  <tr><td>Con referencia propia</td><td className="num">
                    {nEnt(informe.resumen.con_referencia)} de {nEnt(informe.leidas)}</td></tr>
                </>
              )}
            </tbody>
          </table>

          {informe.resumen && informe.resumen.con_referencia < informe.leidas && (
            <p className="page-sub" style={{ marginTop: 10 }}>
              {nEnt(informe.leidas - informe.resumen.con_referencia)} fila(s) no
              traen una columna de referencia. Esas se insertan siempre: no hay
              manera de saber si repetir el archivo es una recarga o dos
              operaciones iguales de verdad.
            </p>
          )}

          {(informe.avisos || []).map((a) => (
            <p key={a} className="page-sub dim" style={{ marginTop: 6 }}>{a}</p>
          ))}

          {!!descartadas.length && (
            <details className="spp-desplegable" open>
              <summary>Filas descartadas · {nEnt(informe.descartadas.length)}</summary>
              <div className="table-wrap">
                <table>
                  <thead><tr><th className="num">Fila</th><th>Motivo</th><th>Contenido</th></tr></thead>
                  <tbody>{descartadas.map((d) => (
                    <tr key={d.fila}>
                      <td className="num">{d.fila}</td>
                      <td className="neg">{d.motivo}</td>
                      <td className="dim">{d.texto}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <VerDescartadas etiqueta="descartadas" />
            </details>
          )}

          {!!muestra.length && (
            <details className="spp-desplegable">
              <summary>Muestra de lo leído</summary>
              <div className="table-wrap">
                <table>
                  <thead><tr>
                    <th>Fecha</th><th className="num">Fondo</th><th>Lado</th>
                    <th>Instrumento</th><th className="num">Cantidad</th>
                    <th className="num">Monto</th><th>Moneda</th><th>Contraparte</th>
                  </tr></thead>
                  <tbody>{muestra.map((o, i) => (
                    <tr key={i}>
                      <td>{fFecha(o.fecha)}</td>
                      <td className="num">{o.fondo}</td>
                      <td><span className={`tb-lado ${o.lado}`}>{o.lado}</span></td>
                      <td>{o.instrumento}</td>
                      <td className="num">{nEnt(Math.round(o.cantidad))}</td>
                      <td className="num">{nEnt(Math.round(o.monto))}</td>
                      <td>{o.moneda}</td>
                      <td>{o.contraparte || '—'}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <VerMuestra etiqueta="filas" />
            </details>
          )}
        </>
      )}
    </div>
  );
}


// ---- 2. Captura a mano -----------------------------------------------------

function AMano({ alCargar, estado }) {
  const [form, setForm] = useState(VACIO);
  const [eco, setEco] = useState('');
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const registrar = async () => {
    setEco('');
    const r = await apiSend('/api/tradebook/operaciones', 'POST', form);
    if (r.ok) {
      const o = r.data.operacion;
      setEco({ ok: true, texto: `Registrada: ${o.lado} de ${nEnt(Math.round(o.cantidad))} `
        + `${o.instrumento} el ${fFecha(o.fecha)}.` });
      // La fecha, el fondo y la moneda se conservan: quien captura a mano
      // suele cargar varias del mismo día y la misma cartera.
      setForm((f) => ({ ...VACIO, fecha: f.fecha, fondo: f.fondo, moneda: f.moneda,
                        contraparte: f.contraparte }));
      alCargar();
    } else setEco({ ok: false, texto: r.data.motivo });
  };

  const listo = form.fecha && form.instrumento && form.cantidad
    && (form.monto || form.precio);

  return (
    <div className="panel">
      <div className="panel-title">Captura a mano</div>
      <p className="page-sub">
        Para la operación suelta que no viene en el archivo. El monto se
        calcula de cantidad × precio si no lo escribes.
      </p>
      <div className="controls spp-controls" style={{ marginTop: 10 }}>
        <div className="field"><label>Fecha</label>
          <input className="date-input" type="date" value={form.fecha} onChange={set('fecha')} /></div>
        <div className="field"><label>Fondo</label>
          <input className="text-input" style={{ width: 70 }} value={form.fondo} onChange={set('fondo')} /></div>
        <div className="field"><label>Lado</label>
          <SppSeg items={LADOS} value={form.lado}
            onChange={(v) => setForm((f) => ({ ...f, lado: v }))} /></div>
        <div className="field"><label>Instrumento</label>
          <input className="text-input" style={{ width: 230 }} placeholder="PERU 3.55 03/31"
            value={form.instrumento} onChange={set('instrumento')} /></div>
      </div>
      <div className="controls spp-controls" style={{ marginTop: 10 }}>
        <div className="field"><label>Cantidad</label>
          <input className="text-input" style={{ width: 130 }} value={form.cantidad} onChange={set('cantidad')} /></div>
        <div className="field"><label>Precio</label>
          <input className="text-input" style={{ width: 110 }} value={form.precio} onChange={set('precio')} /></div>
        <div className="field"><label>Monto</label>
          <input className="text-input" style={{ width: 140 }} placeholder="se calcula"
            value={form.monto} onChange={set('monto')} /></div>
        <div className="field"><label>Moneda</label>
          <input className="text-input" style={{ width: 80 }} value={form.moneda} onChange={set('moneda')} /></div>
      </div>
      <div className="controls spp-controls" style={{ marginTop: 10 }}>
        <div className="field"><label>Contraparte</label>
          <input className="text-input" style={{ width: 160 }} value={form.contraparte} onChange={set('contraparte')} /></div>
        <div className="field"><label>Liquidación</label>
          <input className="date-input" type="date" value={form.fecha_liquidacion}
            onChange={set('fecha_liquidacion')} /></div>
        <div className="field"><label>Referencia</label>
          <input className="text-input" style={{ width: 140 }} placeholder="id del sistema"
            value={form.referencia} onChange={set('referencia')} /></div>
        <div className="field"><label>Nota</label>
          <input className="text-input" style={{ width: 200 }} value={form.nota} onChange={set('nota')} /></div>
      </div>
      <div className="controls" style={{ marginTop: 12 }}>
        <button className="btn principal" disabled={!listo} onClick={registrar}>
          Registrar operación</button>
        <button className="btn" onClick={() => { setForm(VACIO); setEco(''); }}>Limpiar</button>
      </div>
      <Eco eco={eco} />
    </div>
  );
}


// ---- 3. Derivadas de posiciones -------------------------------------------

function DesdePosiciones({ alCargar }) {
  const [desde, setDesde] = useState('');
  const [hasta, setHasta] = useState('');
  const [fondo, setFondo] = useState('');
  const [prop, setProp] = useState(null);
  const [elegidas, setElegidas] = useState({});
  const [eco, setEco] = useState('');
  const [ocupado, setOcupado] = useState(false);

  const buscar = async () => {
    setOcupado(true); setEco(''); setElegidas({});
    const q = new URLSearchParams();
    if (desde) q.set('desde', desde);
    if (hasta) q.set('hasta', hasta);
    if (fondo) q.set('fondo', fondo);
    try {
      const d = await apiGet(`/api/tradebook/derivadas?${q}`);
      setProp(d);
      // Las sospechosas arrancan SIN marcar. Marcarlas por defecto sería
      // convertir la advertencia en un trámite que se acepta sin leer.
      setElegidas(Object.fromEntries(
        d.propuestas.map((p, i) => [i, !p.sospechosa])));
      setEco({ ok: true, texto: `${d.total} movimiento(s) encontrados, `
        + `${d.sospechosas} con un flujo el mismo día. Nada se ha guardado.` });
    } catch (e) {
      setEco({ ok: false, texto: e.message });
    }
    setOcupado(false);
  };

  const guardar = async () => {
    const lista = (prop?.propuestas || []).filter((_, i) => elegidas[i]);
    if (!lista.length) return;
    if (!window.confirm(`Se guardarán ${lista.length} operación(es) derivadas de `
      + 'posiciones. Quedan marcadas como derivadas, no como observadas. ¿Continuar?')) return;
    setOcupado(true);
    const r = await apiSend('/api/tradebook/derivadas', 'POST', { propuestas: lista });
    setOcupado(false);
    if (r.ok) {
      const res = r.data.resultado;
      setEco({ ok: true, texto: `Guardadas ${res.guardadas}. `
        + (res.rechazadas.length ? `${res.rechazadas.length} rechazadas.` : '') });
      setProp(null); alCargar();
    } else setEco({ ok: false, texto: r.data.motivo });
  };

  const [filas, VerFilas] = useVerTodo(prop?.propuestas || [], 15);
  const marcadas = Object.values(elegidas).filter(Boolean).length;

  return (
    <div className="panel">
      <div className="panel-title">Derivar de posiciones</div>
      {/* Esto va arriba y no en una nota al pie: es la diferencia entre un
          dato observado y uno inferido, y quien lo use tiene que saberlo
          antes de pulsar, no después. */}
      <p className="page-sub">
        Propone operaciones a partir de la <b>variación diaria de tenencias</b> que
        ya carga el pipeline de posiciones. Una variación de cantidad no es una
        operación: un split, un vencimiento, un rescate o una acción liberada
        producen la misma diferencia. Las filas donde ese día hubo uno de esos
        flujos vienen marcadas y <b>sin seleccionar</b>. El precio es el de
        valorización del día, no el negociado.
      </p>

      <div className="controls spp-controls" style={{ marginTop: 10 }}>
        <div className="field"><label>Desde</label>
          <input className="date-input" type="date" value={desde}
            onChange={(e) => setDesde(e.target.value)} /></div>
        <div className="field"><label>Hasta</label>
          <input className="date-input" type="date" value={hasta}
            onChange={(e) => setHasta(e.target.value)} /></div>
        <div className="field"><label>Fondo</label>
          <input className="text-input" style={{ width: 70 }} placeholder="todos"
            value={fondo} onChange={(e) => setFondo(e.target.value)} /></div>
        <button className="btn" disabled={ocupado} onClick={buscar}>Buscar movimientos</button>
      </div>
      <Eco eco={eco} />

      {prop && (
        <>
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn principal" disabled={!marcadas || ocupado} onClick={guardar}>
              Guardar {marcadas} seleccionada(s)</button>
            <button className="btn" onClick={() => setElegidas(
              Object.fromEntries(prop.propuestas.map((_, i) => [i, true])))}>
              Marcar todas</button>
            <button className="btn" onClick={() => setElegidas({})}>Desmarcar todas</button>
          </div>
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead><tr>
                <th></th><th>Fecha</th><th>Cartera</th><th>Lado</th>
                <th>Instrumento</th><th className="num">Cantidad</th>
                <th className="num">Monto</th><th>Aviso</th>
              </tr></thead>
              <tbody>
                {filas.map((p, i) => (
                  <tr key={`${p.fecha}-${p.instrumento}-${i}`}>
                    <td><input type="checkbox" checked={!!elegidas[i]}
                      onChange={(e) => setElegidas((s) => ({ ...s, [i]: e.target.checked }))} /></td>
                    <td>{fFecha(p.fecha)}</td>
                    <td>{p.cartera}</td>
                    <td><span className={`tb-lado ${p.lado}`}>{p.lado}</span></td>
                    <td>{p.instrumento}</td>
                    <td className="num">{nEnt(Math.round(p.cantidad))}</td>
                    <td className="num">{p.monto == null ? '—' : nEnt(Math.round(p.monto))}</td>
                    <td className={p.sospechosa ? 'neg' : 'dim'}>
                      {p.motivos?.join(', ') || '—'}</td>
                  </tr>
                ))}
                {!filas.length && (
                  <tr><td colSpan={8} className="dim">
                    No hay variaciones de tenencia en ese rango. Si el pipeline de
                    posiciones no ha corrido en esta base, no hay de dónde derivar.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
          <VerFilas etiqueta="movimientos" />
        </>
      )}
    </div>
  );
}


// ---- El libro cargado ------------------------------------------------------

function Libro({ estado, alCambiar }) {
  const [ops, setOps] = useState(null);
  const [filtro, setFiltro] = useState({ instrumento: '', contraparte: '' });
  const [eco, setEco] = useState('');

  const cargar = () => {
    const q = new URLSearchParams({ limite: '300' });
    if (filtro.instrumento) q.set('instrumento', filtro.instrumento);
    if (filtro.contraparte) q.set('contraparte', filtro.contraparte);
    apiGet(`/api/tradebook/operaciones?${q}`).then((d) => setOps(d.operaciones))
      .catch(() => setOps([]));
  };
  useEffect(cargar, [filtro.instrumento, filtro.contraparte, estado?.filas]);

  const borrar = async (o) => {
    if (!window.confirm(`¿Anular la ${o.lado} de ${o.instrumento} del ${fFecha(o.fecha)}?`)) return;
    const r = await apiSend(`/api/tradebook/operaciones/${o.operacion_id}`, 'DELETE');
    setEco(r.ok
      ? { ok: true, texto: `Operación anulada: ${o.lado} de ${o.instrumento}.` }
      : { ok: false, texto: r.data.motivo });
    alCambiar(); cargar();
  };

  const [filas, VerFilas] = useVerTodo(ops || [], 20);

  return (
    <div className="panel">
      <div className="panel-title">Lo cargado</div>
      <div className="controls" style={{ marginBottom: 10 }}>
        <div className="field"><label>Instrumento</label>
          <input className="text-input" value={filtro.instrumento}
            onChange={(e) => setFiltro((f) => ({ ...f, instrumento: e.target.value }))} /></div>
        <div className="field"><label>Contraparte</label>
          <input className="text-input" value={filtro.contraparte}
            onChange={(e) => setFiltro((f) => ({ ...f, contraparte: e.target.value }))} /></div>
        <a className="btn" href={apiUrl('/api/tradebook/exportar')}>↓ Exportar · XLSX</a>
      </div>
      <Eco eco={eco} />
      <div className="table-wrap">
        <table>
          <thead><tr>
            <th>Fecha</th><th className="num">Fondo</th><th>Lado</th><th>Instrumento</th>
            <th className="num">Cantidad</th><th className="num">Precio</th>
            <th className="num">Monto</th><th>Moneda</th><th>Contraparte</th>
            <th>Origen</th><th></th>
          </tr></thead>
          <tbody>
            {filas.length ? filas.map((o) => (
              <tr key={o.operacion_id}>
                <td>{fFecha(o.fecha)}</td>
                <td className="num">{o.fondo}</td>
                <td><span className={`tb-lado ${o.lado}`}>{o.lado}</span></td>
                <td>{o.instrumento}</td>
                <td className="num">{nEnt(Math.round(o.cantidad))}</td>
                <td className="num">{o.precio == null ? '—' : o.precio.toLocaleString('es-PE',
                  { minimumFractionDigits: 4, maximumFractionDigits: 4 })}</td>
                <td className="num">{nEnt(Math.round(o.monto))}</td>
                <td>{o.moneda}</td>
                <td>{o.contraparte || '—'}</td>
                <td><span className={`tb-origen ${o.origen}`}>{o.origen}</span></td>
                <td><button className="btn peligro" onClick={() => borrar(o)}>Anular</button></td>
              </tr>
            )) : (
              <tr><td colSpan={11} className="dim">
                {ops == null ? 'Cargando…' : 'Sin operaciones.'}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <VerFilas etiqueta="operaciones" />
    </div>
  );
}
