// web/apps/dashboards/app/tradebook/carga/page.js
// ---------------------------------------------------------------------------
// Tradebook · Registro y carga.
//
// El libro se llena por DOS vías, y la pantalla las separa porque no son el
// mismo dato:
//
//   - el registro de los traders, a mano o por Excel, que trae el detalle y
//     sobre todo trae quién operó;
//   - FMS, la operación tal como sale del sistema: general, y sin dueño.
//
// Ninguna de las dos guarda nada sin haber mostrado antes lo que va a
// guardar. Debajo, el libro de lo cargado, para mirarlo y anular.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';

import Eco from '../../../components/Eco';
import FormatoArchivo from '../../../components/FormatoArchivo';
import SppSeg from '../../../components/SppSeg';
import TradebookTabs from '../../../components/TradebookTabs';
import useVerTodo from '../../../components/useVerTodo';
import { apiGet } from '../../../lib/api';
import { apiSend, apiUrl, fFecha, nEnt } from '../../../lib/spp';

const VIAS = [
  ['Registro de traders', 'traders'],
  ['Desde FMS', 'fms'],
];
const LADOS = [['Compra', 'compra'], ['Venta', 'venta']];
// Sin `referencia`: es el id del sistema ORIGEN, y quien captura a mano no
// viene de ningun sistema. El campo sigue existiendo en la carga por archivo,
// que es donde ese id existe y donde sirve para no duplicar al recargar.
const VACIO = {
  fecha: '', fondo: '2', lado: 'compra', instrumento: '', cantidad: '',
  precio: '', monto: '', moneda: 'PEN', contraparte: '', fecha_liquidacion: '',
  trader: '', nota: '',
};

export default function TradebookCarga() {
  const [via, setVia] = useState('traders');
  const [estado, setEstado] = useState(null);
  const [error, setError] = useState(null);

  const cargarEstado = () => apiGet('/api/tradebook/estado')
    .then(setEstado).catch((e) => setError(e.message));
  useEffect(() => { cargarEstado(); }, []);

  const deTraders = (estado?.origenes?.excel || 0) + (estado?.origenes?.manual || 0);
  const deFms = estado?.origenes?.fms || 0;

  return (
    <div>
      <h1 className="page-title">Tradebook</h1>
      <p className="page-sub">
        Registro y carga
        {estado?.filas
          ? ` · ${nEnt(estado.filas)} operaciones (${nEnt(deTraders)} de traders, ${nEnt(deFms)} de FMS)`
          : ' · el libro está vacío'}
      </p>
      <TradebookTabs />

      {error && <div className="panel error">Error: {error}</div>}

      <div className="panel">
        <div className="controls">
          <div className="field"><label>Vía</label>
            <SppSeg items={VIAS} value={via} onChange={setVia} /></div>
        </div>
        {/* La diferencia entre las dos vías no es de dónde sale el archivo
            sino cuánto dice cada fila. Decirlo aquí evita que alguien cargue
            el reporte de FMS por la vía del trader y le invente un dueño. */}
        <p className="page-sub dim" style={{ marginTop: 4 }}>
          {via === 'traders'
            ? 'El registro propio: lleva siempre quién operó, y es el que permite mirar el libro por trader.'
            : 'La operación tal como sale de FMS: general, y sin nombre de trader. FMS no dice quién operó.'}
        </p>
      </div>

      {via === 'traders' ? (
        <>
          <AMano alCargar={cargarEstado} traders={estado?.traders || []} />
          <PorArchivo alCargar={cargarEstado} origen="excel"
            traders={estado?.traders || []} />
        </>
      ) : (
        <PorArchivo alCargar={cargarEstado} origen="fms" traders={[]} />
      )}

      <Libro estado={estado} alCambiar={cargarEstado} />
    </div>
  );
}


// ---- Carga por archivo (sirve a las dos vías) ------------------------------

function PorArchivo({ alCargar, origen, traders }) {
  const deTraders = origen !== 'fms';
  const [archivo, setArchivo] = useState(null);
  const [hoja, setHoja] = useState('');
  const [trader, setTrader] = useState('');
  const [informe, setInforme] = useState(null);
  const [eco, setEco] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const input = useRef(null);

  // Cambiar de archivo o de trader invalida la revisión anterior: confirmar
  // una carga con el informe de OTRO archivo delante es exactamente el error
  // que el paso de revisión existe para evitar.
  const invalidar = () => { setInforme(null); setEco(''); };

  const enviar = async (soloRevisar) => {
    if (!archivo) return;
    setOcupado(true); setEco('');
    const fd = new FormData();
    fd.append('archivo', archivo);
    fd.append('revisar', soloRevisar ? '1' : '');
    fd.append('hoja', hoja);
    fd.append('origen', origen);
    fd.append('trader', deTraders ? trader : '');
    const r = await apiSend('/api/tradebook/archivo', 'POST', fd, true);
    setOcupado(false);
    if (!r.ok) { setEco({ ok: false, texto: r.data.motivo }); return; }
    setInforme(r.data.informe);
    if (soloRevisar) {
      const i = r.data.informe;
      setEco({ ok: true, texto: `Revisado: ${i.leidas} operación(es) legibles, `
        + `${i.descartadas.length} descartada(s). Nada se ha guardado todavía.` });
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
      <div className="panel-title">
        {deTraders ? 'Carga por archivo · registro del trader' : 'Carga del reporte de FMS'}
      </div>
      <p className="page-sub">
        Excel o CSV. Se reconoce por el contenido, no por la extensión, y las
        columnas por su nombre en varios idiomas. Obligatorias: fecha, fondo,
        lado, instrumento, cantidad, y monto o precio
        {deTraders ? ', más el trader de cada fila.' : '.'}
      </p>

      <div className="controls" style={{ marginTop: 10 }}>
        <FormatoArchivo clave={deTraders ? 'tradebook_traders' : 'tradebook_fms'} />
        <a className="btn" href={apiUrl(`/api/tradebook/plantilla?origen=${origen}`)}>
          ↓ Plantilla · XLSX</a>
        <input ref={input} type="file" accept=".xlsx,.xls,.csv,.txt"
          onChange={(e) => { setArchivo(e.target.files?.[0] || null); invalidar(); }} />
        <input className="text-input" placeholder="Hoja (opcional)"
          value={hoja} onChange={(e) => setHoja(e.target.value)} style={{ width: 150 }} />
      </div>

      {deTraders && (
        <div className="controls" style={{ marginTop: 10 }}>
          <div className="field"><label>Trader del archivo</label>
            <input className="text-input" list="traders-conocidos" style={{ width: 220 }}
              placeholder="si el archivo no lo trae por fila"
              value={trader} onChange={(e) => { setTrader(e.target.value); invalidar(); }} />
            <datalist id="traders-conocidos">
              {traders.map((t) => <option key={t} value={t} />)}
            </datalist>
          </div>
          {/* Es un valor POR DEFECTO, no una sobreescritura: un archivo que sí
              nombra a cada trader sigue diciendo lo que dice. */}
          <p className="page-sub dim" style={{ alignSelf: 'end', marginBottom: 6 }}>
            Solo rellena las filas que no traigan columna de trader.
          </p>
        </div>
      )}

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
              <tr><td>Va al libro de</td><td className="num">
                {informe.origen === 'fms' ? 'FMS' : 'los traders'}</td></tr>
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
                  {deTraders && (
                    <tr><td>Traders</td><td className="num">
                      {informe.resumen.traders?.join(', ') || '—'}</td></tr>
                  )}
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
                    <th className="num">Monto</th><th>Moneda</th>
                    {deTraders && <th>Trader</th>}<th>Contraparte</th>
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
                      {deTraders && <td>{o.trader || '—'}</td>}
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


// ---- Captura a mano (solo la vía de traders) -------------------------------

function AMano({ alCargar, traders }) {
  const [form, setForm] = useState(VACIO);
  const [eco, setEco] = useState('');
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const registrar = async () => {
    setEco('');
    const r = await apiSend('/api/tradebook/operaciones', 'POST', form);
    if (r.ok) {
      const o = r.data.operacion;
      setEco({ ok: true, texto: `Registrada: ${o.lado} de ${nEnt(Math.round(o.cantidad))} `
        + `${o.instrumento} el ${fFecha(o.fecha)}, por ${o.trader}.` });
      // La fecha, el fondo, la moneda, la contraparte y el TRADER se
      // conservan: quien captura a mano suele cargar varias seguidas suyas
      // del mismo día.
      setForm((f) => ({ ...VACIO, fecha: f.fecha, fondo: f.fondo, moneda: f.moneda,
                        contraparte: f.contraparte, trader: f.trader }));
      alCargar();
    } else setEco({ ok: false, texto: r.data.motivo });
  };

  const listo = form.fecha && form.instrumento && form.cantidad
    && (form.monto || form.precio) && form.trader.trim();

  return (
    <div className="panel">
      <div className="panel-title">Captura a mano</div>
      <p className="page-sub">
        Para la operación suelta que no viene en el archivo. El monto se
        calcula de cantidad × precio si no lo escribes.
      </p>
      <div className="controls spp-controls" style={{ marginTop: 10 }}>
        <div className="field"><label>Trader</label>
          <input className="text-input" list="traders-conocidos" style={{ width: 170 }}
            value={form.trader} onChange={set('trader')} />
          <datalist id="traders-conocidos">
            {traders.map((t) => <option key={t} value={t} />)}
          </datalist></div>
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


// ---- El libro cargado ------------------------------------------------------

function Libro({ estado, alCambiar }) {
  const [ops, setOps] = useState(null);
  const [filtro, setFiltro] = useState({ instrumento: '', contraparte: '', trader: '', origen: '' });
  const [eco, setEco] = useState('');

  const cargar = () => {
    const q = new URLSearchParams({ limite: '300' });
    Object.entries(filtro).forEach(([k, v]) => { if (v) q.set(k, v); });
    apiGet(`/api/tradebook/operaciones?${q}`).then((d) => setOps(d.operaciones))
      .catch(() => setOps([]));
  };
  useEffect(cargar, [filtro.instrumento, filtro.contraparte, filtro.trader,
                     filtro.origen, estado?.filas]);

  const borrar = async (o) => {
    if (!window.confirm(`¿Anular la ${o.lado} de ${o.instrumento} del ${fFecha(o.fecha)}?`)) return;
    const r = await apiSend(`/api/tradebook/operaciones/${o.operacion_id}`, 'DELETE');
    setEco(r.ok
      ? { ok: true, texto: `Operación anulada: ${o.lado} de ${o.instrumento}.` }
      : { ok: false, texto: r.data.motivo });
    alCambiar(); cargar();
  };

  const [filas, VerFilas] = useVerTodo(ops || [], 20);
  const exportar = new URLSearchParams();
  Object.entries(filtro).forEach(([k, v]) => { if (v) exportar.set(k, v); });

  return (
    <div className="panel">
      <div className="panel-title">Lo cargado</div>
      <div className="controls spp-controls" style={{ marginBottom: 10 }}>
        <div className="field"><label>Libro</label>
          <SppSeg items={[['Ambos', ''], ['De traders', 'traders'], ['De FMS', 'fms']]}
            value={filtro.origen}
            onChange={(v) => setFiltro((f) => ({ ...f, origen: v }))} /></div>
        <div className="field"><label>Trader</label>
          <input className="text-input" style={{ width: 150 }} value={filtro.trader}
            onChange={(e) => setFiltro((f) => ({ ...f, trader: e.target.value }))} /></div>
        <div className="field"><label>Instrumento</label>
          <input className="text-input" value={filtro.instrumento}
            onChange={(e) => setFiltro((f) => ({ ...f, instrumento: e.target.value }))} /></div>
        <div className="field"><label>Contraparte</label>
          <input className="text-input" value={filtro.contraparte}
            onChange={(e) => setFiltro((f) => ({ ...f, contraparte: e.target.value }))} /></div>
        <a className="btn" style={{ alignSelf: 'end' }}
          href={apiUrl(`/api/tradebook/exportar?${exportar}`)}>↓ Exportar · XLSX</a>
      </div>
      <Eco eco={eco} />
      <div className="table-wrap">
        <table>
          <thead><tr>
            <th>Fecha</th><th className="num">Fondo</th><th>Lado</th><th>Instrumento</th>
            <th className="num">Cantidad</th><th className="num">Precio</th>
            <th className="num">Monto</th><th>Moneda</th><th>Contraparte</th>
            <th>Trader</th><th>Origen</th><th></th>
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
                <td>{o.trader || <span className="dim">—</span>}</td>
                <td><span className={`tb-origen ${o.origen}`}>{o.origen}</span></td>
                <td><button className="btn peligro" onClick={() => borrar(o)}>Anular</button></td>
              </tr>
            )) : (
              <tr><td colSpan={12} className="dim">
                {ops == null ? 'Cargando…' : 'Sin operaciones.'}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <VerFilas etiqueta="operaciones" />
    </div>
  );
}
