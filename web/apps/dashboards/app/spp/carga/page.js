// web/apps/dashboards/app/spp/carga/page.js
// ---------------------------------------------------------------------------
// SPP tablero · Registro y carga: everything that writes.
//
// One grammar for the whole view, ported from the monitor: on the LEFT you
// act, on the RIGHT you see - and no file reaches the database without
// having been shown first (the historical load reviews under a token, then
// loads in the chosen mode). Long operations run in the shared background
// task and are followed by polling /api/spp/task.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';
import { apiGet, apiSend } from '../../../lib/api';
import {
  apiUrl, fDate, fTime, fmtMetric, fundsOf as fundsOfCfg, todayLocal, metricsOf, nInt, metricName,
} from '../../../lib/spp';
import Log from '../../../components/Log';
import Echo from '../../../components/Echo';
import FileUpload from '../../../components/FileUpload';
import useShowAll from '../../../components/useShowAll';
import SppSeg from '../../../components/SppSeg';
import SppTabs from '../../../components/SppTabs';
import useSppTask from '../../../components/useSppTask';
import BenchmarkEditor from './BenchmarkEditor';

// The work areas, and the hash that makes each one linkable. Panel and
// Libro are routes; these were pure state, so a reload (which the task hook
// itself sometimes advises) always dropped the operator back into Valor
// cuota.
const AREAS = [['Valor cuota', 'vc'], ['Benchmarks', 'benchmarks']];
const AREA_KEYS = AREAS.map(([, v]) => v);

// Small key/value report table used by every section.
function Report({ rows }) {
  return (
    <table className="spp-report"><tbody>
      {rows.map(([a, b], i) => (
        <tr key={i}><td>{a}</td><td className="num">{b}</td></tr>
      ))}
    </tbody></table>
  );
}

// Preview of a reviewed file: last rows, most recent first.
function Sample({ sample, title }) {
  const [visible, ShowAll] = useShowAll(sample?.rows, 10);
  if (!sample || !sample.rows?.length) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <div className="panel-title">{title} · {nInt(sample.total)} fechas en total</div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Fecha</th>{sample.columns.map((c) => <th key={c} className="num">{c}</th>)}</tr></thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r[0]}>
                <td>{fDate(r[0])}</td>
                {r.slice(1).map((v, i) => (
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
      <ShowAll label="filas del archivo" />
    </div>
  );
}

export default function SppCargaPage() {
  const [cfg, setCfg] = useState(null);
  const [status, setStatus] = useState(null);
  // The last unattended scrape, as the scheduler recorded it in job_runs.
  const [lastScrape, setLastScrape] = useState(undefined);
  // Which work area is on screen. Kept in the URL hash - not the query
  // string, which Sidebar propagates to every menu link - so the area
  // survives a reload and can be sent to someone.
  const [area, setAreaState] = useState('vc');

  useEffect(() => {
    const initial = window.location.hash.slice(1);
    if (AREA_KEYS.includes(initial)) setAreaState(initial);
  }, []);

  const setArea = (v) => {
    setAreaState(v);
    try {
      window.history.replaceState(null, '', `${window.location.pathname}#${v}`);
    } catch { /* the area still changes even if the URL does not follow */ }
  };

  // ---- shared background task (one hook for the whole page) ----
  const { task, busy, start } = useSppTask();

  const loadStatus = () => apiGet('/api/spp/status').then(setStatus).catch(() => {});
  const loadLastScrape = () => apiGet('/api/spp/scrape/last').then((j) => setLastScrape(j.run)).catch(() => {});
  const refreshCfg = () => apiGet('/api/spp/config').then(setCfg).catch(() => {});

  const onTaskDone = (then) => (t) => {
    loadStatus();
    loadLastScrape();
    if (then) then(t);
  };

  // ---- scrape ----
  // The unattended run (Windows task at 16:00, with retries) has no box on
  // screen: it leaves its trail in data/spp/scrape.log and in the task log.
  // Only the hand launch lives here.
  const [scrapeEcho, setScrapeEcho] = useState('');

  const scrape = async (force) => {
    // Overwriting confirms, like every other action that replaces stored
    // values. This one reaches further than it looks: it re-reads the last
    // 7 business days and replaces what is already in the book, including
    // hand corrections.
    if (force && !window.confirm(
      'Correr y sobrescribir: vuelve a leer los últimos 7 días hábiles y '
      + 'REEMPLAZA lo que ya esté en el libro para esas fechas, incluidas '
      + 'las correcciones hechas a mano. ¿Continuar?')) return;
    setScrapeEcho('');
    const r = await apiSend('/api/spp/scrape', 'POST', { force });
    if (!r.ok) { setScrapeEcho({ ok: false, text: r.data.detail }); return; }
    start(r.data.action, onTaskDone());
  };

  // ---- manual registration ----
  const [rDate, setRDate] = useState('');
  const [rAfp, setRAfp] = useState('');
  const [rMetric, setRMetric] = useState('valor_cuota');
  const [rValues, setRValues] = useState({});
  const [rCurrent, setRCurrent] = useState('');
  const [rNeighbors, setRNeighbors] = useState({ funds: [], dates: [], series: {} });
  const [rMessage, setRMessage] = useState(null);
  const [rTick, setRTick] = useState(0);   // bumps to reload the preload after writing
  // Gate for the write buttons: an empty box means DELETE server-side, so
  // registering must be impossible while the boxes are unfilled because the
  // preload is in flight or failed - not because the operator emptied them.
  const [rPreload, setRPreload] = useState('loading');   // loading | ok | error

  const names = (cfg?.afps || []).map((a) => a.name);
  const fundsOf = (afp) => fundsOfCfg(cfg, afp);

  useEffect(() => {
    apiGet('/api/spp/config').then((c) => {
      setCfg(c);
      setRAfp(c.house || c.afps[0]?.name || '');
    }).catch(() => {});
    setRDate(todayLocal());
    loadStatus();
    loadLastScrape();
  }, []);

  // Preload the fund boxes with what the book already holds (±12 days for
  // the neighboring closes), like the monitor's verDato().
  // The boxes are CLEARED synchronously on every selection change: stale
  // values from the previous AFP/date must never be submittable against the
  // new one, and a late response from an old selection must not land either.
  useEffect(() => {
    if (!cfg || !rDate || !rAfp) return undefined;
    const funds = fundsOf(rAfp);
    setRValues(Object.fromEntries(funds.map((f) => [f, ''])));
    setRCurrent(`${rAfp} · ${metricName(cfg, rMetric)} · ${fDate(rDate)} — cargando…`);
    setRNeighbors({ funds, dates: [], series: {} });
    // The previous write's result does not describe the new selection.
    setRMessage(null);
    setRPreload('loading');
    let current = true;

    const from = new Date(`${rDate}T00:00:00`); from.setDate(from.getDate() - 12);
    const to = new Date(`${rDate}T00:00:00`); to.setDate(to.getDate() + 12);
    Promise.all(funds.map(async (f) => {
      const q = new URLSearchParams({
        fund: String(f), afps: rAfp, metric: rMetric,
        from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10),
      });
      const d = await apiGet(`/api/spp/series?${q}`);
      return [f, d.series?.[0]?.points || []];
    })).then((pairs) => {
      if (!current) return;
      const series = Object.fromEntries(pairs);
      const vals = {}; let loaded = 0;
      funds.forEach((f) => {
        const hit = series[f].find((p) => p[0] === rDate);
        vals[f] = hit ? String(hit[1]) : '';
        if (hit) loaded++;
      });
      setRValues(vals);
      setRCurrent(loaded
        ? `${rAfp} · ${metricName(cfg, rMetric)} · ${fDate(rDate)} — ${loaded} de ${funds.length} fondos ya registrados.`
        : `${rAfp} · ${metricName(cfg, rMetric)} · ${fDate(rDate)} — sin datos ese día.`);
      const dates = [...new Set(funds.flatMap((f) => series[f].map((p) => p[0])))]
        .sort().slice(-9).reverse();
      setRNeighbors({ funds, dates, series });
      setRPreload('ok');
    }).catch(() => {
      if (!current) return;
      setRPreload('error');
      setRCurrent('No se pudo leer el libro para precargar; el registro queda bloqueado hasta reconectar.');
    });
    return () => { current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cfg, rDate, rAfp, rMetric, rTick]);

  // {fund: null|Number}: an empty box is a DELETE, an absent fund is left
  // alone.
  const buildValues = (funds, values, clearAll) => Object.fromEntries(
    funds.map((f) => {
      const v = String(values[f] ?? '').trim();
      return [f, clearAll ? null : (v === '' ? null : Number(v))];
    }));

  const register = async (clearAll) => {
    if (!clearAll && !Object.values(rValues).some((v) => String(v).trim() !== '')) {
      setRMessage({ ok: false, text: 'No hay ningún valor escrito. Para borrar la fecha usa «Anular la fecha».' });
      return;
    }
    if (clearAll && !window.confirm(
      `Anular ${rAfp} · ${metricName(cfg, rMetric)} · ${fDate(rDate)}: borra los valores de todos sus fondos en esa fecha. ¿Continuar?`)) return;
    const values = buildValues(fundsOf(rAfp), rValues, clearAll);
    const r = await apiSend('/api/spp/values', 'POST', {
      date: rDate, afp: rAfp, metric: rMetric, values,
    });
    if (!r.ok) { setRMessage({ ok: false, text: r.data.detail }); return; }
    const x = r.data.result;
    const saved = Object.keys(x.saved).length;
    setRMessage({
      ok: true,
      text: `${saved} valor(es) guardados`
        + (x.deleted.length ? ` · ${x.deleted.length} borrados` : '')
        + ` · ${x.afp} · ${metricName(cfg, x.metric)} · ${fDate(x.date)}`
        + (x.new_row ? ' · fila nueva en el libro' : '')
        + (x.row_deleted ? ' · la fecha quedó sin datos y salió del libro' : ''),
    });
    setRTick((t) => t + 1);   // reload the boxes and neighbors with what was written
    loadStatus();
  };

  // ---- historical load ----
  const hRef = useRef(null);
  const [hName, setHName] = useState('Ningún archivo seleccionado');
  const [hReport, setHReport] = useState(null);
  const [hToken, setHToken] = useState(null);
  const [hEcho, setHEcho] = useState('');

  const reviewHistory = async () => {
    const f = hRef.current?.files?.[0];
    if (!f) return;
    setHName(`${f.name} · revisando…`); setHReport(null); setHToken(null); setHEcho('');
    const fd = new FormData(); fd.append('file', f);
    const r = await apiSend('/api/spp/history/review', 'POST', fd, true);
    if (!r.ok) {
      setHName(f.name);
      setHEcho({ ok: false, text: r.data.detail });
      return;
    }
    setHName(`${f.name} · revisado, nada escrito todavía`);
    setHReport(r.data.report);
    setHToken(r.data.token);
  };

  const loadHistory = async (mode) => {
    if (!hToken || !hReport) return;
    const msg = mode === 'missing'
      ? 'Cargar lo que falta: agrega fechas nuevas y rellena celdas vacías. No modifica ningún valor que ya tenga dato. ¿Continuar?'
      : `Cargar y corregir: además de agregar lo que falta, REEMPLAZA ${nInt(hReport.changed_cells)} celda(s) que difieren del archivo. ¿Continuar?`;
    if (!window.confirm(msg)) return;
    const r = await apiSend('/api/spp/history/load', 'POST', { token: hToken, mode });
    if (!r.ok) { setHEcho({ ok: false, text: r.data.detail }); return; }
    setHEcho({ ok: true, text: 'Guardando en la base…' });
    start(r.data.action, onTaskDone((t) => {
      if (t.error) {
        setHEcho({ ok: false, text: 'La carga falló y no se guardó nada nuevo. Puedes reintentar sin volver a subir el archivo.' });
      } else {
        setHEcho({ ok: true, text: `Cargado en modo ${mode === 'missing' ? 'solo lo que falta' : 'corregir'}.` });
        setHToken(null);
      }
    }));
  };

  const historyRows = (i) => [
    ['Archivo', `${i.file} · ${nInt(Math.round(i.bytes / 1024))} KB`],
    ['Contenido', `${nInt(i.dates)} fechas · ${i.series} series · ${nInt(i.values)} valores`],
    ['Rango', `${fDate(i.from)} a ${fDate(i.to)}`],
    ['Fechas nuevas', `${nInt(i.new_dates)}${i.new_cells ? ` · ${nInt(i.new_cells)} valores` : ''}`],
    ['Ya en el libro', nInt(i.known_dates)],
    ['Celdas vacías que se llenarían', nInt(i.fill_cells)],
    ['Celdas que difieren del libro', nInt(i.changed_cells)],
    ['Celdas idénticas', nInt(i.unchanged_cells)],
  ];

  const metricStep = rMetric === 'valor_cuota' ? '0.0000001' : '0.01';

  return (
    <div className="spp-page">
      <h1 className="page-title">Valor Cuota SPP</h1>
      <p className="page-sub">Registro y carga · a la izquierda se actúa, a la derecha se ve.
        Ningún archivo llega a la base sin haberse mostrado antes.</p>
      <SppTabs />

      {/* Two work areas, one visible at a time. All the state lives in this
          component, so switching areas loses nothing typed. */}
      <div className="controls spp-controls" style={{ margin: '12px 0 16px' }}>
        <div className="field"><label>Área</label>
          <SppSeg items={AREAS} value={area} onChange={setArea} /></div>
      </div>

      {area === 'vc' && (<>
      {/* ===== 1 · Manual registration of valor cuota ===== */}
      <div className="spp-two-up">
        <div className="panel">
          <div className="panel-title">Valor cuota · registro manual</div>
          <p className="page-sub">Una AFP y una fecha, sus fondos a la vez. Los cuadros se
            precargan con lo que ya hay: escribir uno lo reemplaza y <b>dejarlo vacío borra
            ese dato</b>. Si la fecha queda sin ningún valor, sale del libro.</p>
          <div className="controls spp-controls">
            <div className="field"><label htmlFor="r-date">Fecha</label>
              <input id="r-date" className="date-input" type="date" value={rDate}
                onChange={(e) => setRDate(e.target.value)} /></div>
            <div className="field"><label htmlFor="r-afp">AFP</label>
              <select id="r-afp" className="select" value={rAfp} onChange={(e) => setRAfp(e.target.value)}>
                {names.map((a) => <option key={a} value={a}>{a}</option>)}
              </select></div>
            <div className="field"><label htmlFor="r-metric">Métrica</label>
              <select id="r-metric" className="select" value={rMetric}
                onChange={(e) => setRMetric(e.target.value)}>
                {metricsOf(cfg).map(([label, v]) => <option key={v} value={v}>{label}</option>)}
              </select></div>
          </div>
          <div className="controls spp-controls" style={{ marginTop: 10 }}>
            {fundsOf(rAfp).map((f) => (
              <div className="field" key={f}><label htmlFor={`r-fund-${f}`}>Fondo {f}</label>
                <input id={`r-fund-${f}`} className="date-input" type="number" min="0"
                  step={metricStep}
                  placeholder={rMetric === 'valor_cuota' ? '0.0000000' : '0.00'}
                  value={rValues[f] ?? ''}
                  onChange={(e) => setRValues({ ...rValues, [f]: e.target.value })} /></div>
            ))}
          </div>
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn primary" disabled={rPreload !== 'ok' || busy}
              title={busy ? 'Espera a que termine la operación en curso' : undefined}
              onClick={() => register(false)}>Registrar valores</button>
            <button className="btn danger" disabled={rPreload !== 'ok' || busy}
              title={busy ? 'Espera a que termine la operación en curso' : undefined}
              onClick={() => register(true)}>Anular la fecha</button>
          </div>
          <Echo echo={rMessage} />
        </div>

        <div className="panel">
          <div className="panel-title">En el libro</div>
          <p className="page-sub">{rCurrent || 'Elige fecha, AFP y métrica.'}</p>
          <div className="panel-title" style={{ marginTop: 12 }}>Cierres vecinos</div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Fecha</th>
                {rNeighbors.funds.map((f) => <th key={f} className="num">F{f}</th>)}</tr></thead>
              <tbody>
                {rNeighbors.dates.length ? rNeighbors.dates.map((d) => (
                  <tr key={d} style={d === rDate ? { fontWeight: 700 } : undefined}>
                    <td>{fDate(d)}</td>
                    {rNeighbors.funds.map((f) => {
                      const hit = (rNeighbors.series[f] || []).find((p) => p[0] === d);
                      return <td key={f} className={`num ${hit ? '' : 'dim'}`}>
                        {hit ? fmtMetric(hit[1], rMetric, rMetric !== 'valor_cuota') : '—'}</td>;
                    })}
                  </tr>
                )) : <tr><td colSpan={rNeighbors.funds.length + 1} className="dim">Sin cierres cerca.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ===== 2 · Daily scrape ===== */}
      <div className="spp-two-up">
        <div className="panel">
          <div className="panel-title">Valor cuota · extracción diaria</div>
          <p className="page-sub">Lee la página de variables SPP (últimos 7 días hábiles) e
            inserta solo lo que falta, con las tres métricas. Corre sola cada día a las
            16:00 (y reintenta a las 16:30 y 17:00 si la SBS aún no publicó); aquí se lanza
            a mano. Toma unos 20–90 s.</p>
          <div className="controls">
            <button className="btn primary" disabled={busy}
              onClick={() => scrape(false)}>Correr extracción</button>
            <button className="btn danger" disabled={busy}
              onClick={() => scrape(true)}>Correr y sobrescribir</button>
          </div>
          <p className="page-sub flag-warn" style={{ marginTop: 10 }}>
            La SBS está detrás del WAF Imperva: <b>se abrirá una ventana de Chrome</b> en la
            máquina donde corre la API. No la cierres mientras corre.
          </p>
          <Echo echo={scrapeEcho} />
        </div>

        <div className="panel">
          <div className="panel-title">Última corrida automática</div>
          {lastScrape === undefined ? <p className="page-sub dim">Cargando…</p>
            : lastScrape === null
              ? <p className="page-sub dim">El scheduler no ha corrido la extracción todavía.</p>
              : (
                <p className="page-sub">
                  {fTime(lastScrape.started_at)} en {lastScrape.machine_id} ·{' '}
                  <b className={lastScrape.status === 'success' ? 'pos' : lastScrape.status === 'error' ? 'neg' : ''}>
                    {lastScrape.status === 'success' ? 'correcta' : lastScrape.status === 'error' ? 'con error' : lastScrape.status}
                  </b>
                  {lastScrape.run_date ? ` · día esperado ${fDate(lastScrape.run_date)}` : ''}
                  {lastScrape.error ? <><br /><span className="neg">{lastScrape.error}</span></> : null}
                </p>
              )}

          <div className="panel-title" style={{ marginTop: 14 }}>Bitácora</div>
          <Log task={task} />

          <div className="panel-title" style={{ marginTop: 14 }}>Tramos sin dato</div>
          <p className="page-sub">Días hábiles consecutivos sin valor cuota. Los tramos de 1–2
            días se omiten: son feriados peruanos, no información faltante.</p>
          {(status?.gaps || []).length ? (
            <Report rows={status.gaps.map((g) =>
              [`${fDate(g.from)} a ${fDate(g.to)}`, `${g.days} d.h.`])} />
          ) : <p className="page-sub dim">Sin tramos abiertos.</p>}
        </div>
      </div>

      {/* ===== 3 · Historical load from Excel ===== */}
      <FileUpload
        ref={hRef}
        title="Valor cuota · carga histórica por Excel"
        description={<>El archivo de la SBS <b>tal como se descarga</b> («Valores cuota desde
          Agosto 1993», hoja «Valor cuota diario»). Trae solo valor cuota, y una celda vacía
          se deja como está: el Excel nunca borra.</>}
        format="valor_cuota_history"
        accept=".xls,.xlsx"
        onChange={reviewHistory}
        fileName={hName}
        actions={hToken && (<>
          <button className="btn primary" disabled={busy}
            onClick={() => loadHistory('missing')}>Cargar lo que falta</button>
          <button className="btn danger" disabled={busy}
            onClick={() => loadHistory('replace')}>Cargar y corregir</button>
        </>)}
        echo={hEcho}
        footer={<>
          <a className="btn" target="_blank" rel="noreferrer"
            href="https://www.sbs.gob.pe/app/stats/EstadisticaSistemaFinancieroResultadosHist.asp?c=FP-130706&Y=0">
            Abrir la página de la SBS</a>
          <a className="btn" href={apiUrl('/api/spp/export')}>↓ Bajar todo el libro · CSV</a>
        </>}
        previewStatus={hReport && `${hReport.file} · ${nInt(hReport.dates)} fechas · ${fDate(hReport.from)} a ${fDate(hReport.to)}. Nada se ha guardado.`}
        preview={hReport && (<>
          <Report rows={historyRows(hReport)} />
          {hReport.changed_cells > 0 && (
            <div style={{ marginTop: 8 }}>
              <p className="page-sub"><b>{nInt(hReport.changed_cells)}</b> celda(s)
                tienen hoy un valor distinto al del archivo. Solo cambian con
                «Cargar y corregir»:</p>
              <Report rows={hReport.examples.map((e) =>
                [`${fDate(e.date)} · ${e.series}`, `${e.book} → ${e.file}`])} />
            </div>
          )}
          {hReport.total_future > 0 && (
            <p className="page-sub">Se descartaron <b>{hReport.total_future}</b> fecha(s)
              futuras: {hReport.future_dates.join(', ')}.</p>
          )}
          {hReport.unknown_afps?.length > 0 && (
            <p className="page-sub flag-warn">El archivo trae AFP que no están en el
              registro: <b>{hReport.unknown_afps.join(', ')}</b>. Sus datos no se
              cargarán hasta darlas de alta en config/afps.yaml.</p>
          )}
          <Sample sample={hReport.sample} title="Últimas filas del archivo" />
        </>)}
        previewEmpty="Elige el Excel de la SBS y aquí verás lo que trae, antes de que nada toque la base."
      />

      </>)}

      {area === 'benchmarks' && (
        <BenchmarkEditor
          refreshCfg={refreshCfg}
          busy={busy} task={task} start={start}
          onTaskDone={onTaskDone}
        />
      )}
    </div>
  );
}
