// web/apps/dashboards/app/spp/carga/page.js
// ---------------------------------------------------------------------------
// SPP tablero · Register & load: everything that writes.
//
// One grammar for the whole view, ported from the monitor: on the LEFT you
// act, on the RIGHT you see - and no file reaches the database without
// having been shown first (the historical load reviews under a token, then
// loads in the chosen mode). Long operations run in the shared background
// task and are followed by polling /api/tasks/current.
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
import useTask from '../../../components/useTask';

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
      <div className="panel-title">{title} · {nInt(sample.total)} dates in total</div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Date</th>{sample.columns.map((c) => <th key={c} className="num">{c}</th>)}</tr></thead>
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
      <ShowAll label="file rows" />
    </div>
  );
}

export default function SppCargaPage() {
  const [cfg, setCfg] = useState(null);
  const [status, setStatus] = useState(null);
  // The last unattended scrape, as the scheduler recorded it in job_runs.
  const [lastScrape, setLastScrape] = useState(undefined);
  // ---- shared background task (one hook for the whole page) ----
  const { task, busy, start } = useTask();

  const loadStatus = () => apiGet('/api/spp/status').then(setStatus).catch(() => {});
  const loadLastScrape = () => apiGet('/api/spp/scrape/last').then((j) => setLastScrape(j.run)).catch(() => {});

  const onTaskDone = (then) => (t) => {
    loadStatus();
    loadLastScrape();
    if (then) then(t);
  };

  // ---- scrape ----
  // The unattended run (scheduler job at 16:00, with retries) has no box on
  // screen: it leaves its trail in job_runs and in the task log. Only the
  // hand launch lives here.
  const [scrapeEcho, setScrapeEcho] = useState('');

  const scrape = async (force) => {
    // Overwriting confirms, like every other action that replaces stored
    // values. This one reaches further than it looks: it re-reads the last
    // 7 business days and replaces what is already in the book, including
    // hand corrections.
    if (force && !window.confirm(
      'Run and overwrite: re-reads the last 7 business days and REPLACES what '
      + 'the book already holds for those dates, hand corrections included. '
      + 'Continue?')) return;
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
    setRCurrent(`${rAfp} · ${metricName(cfg, rMetric)} · ${fDate(rDate)} — loading…`);
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
        ? `${rAfp} · ${metricName(cfg, rMetric)} · ${fDate(rDate)} — ${loaded} of ${funds.length} funds already registered.`
        : `${rAfp} · ${metricName(cfg, rMetric)} · ${fDate(rDate)} — no data on that day.`);
      const dates = [...new Set(funds.flatMap((f) => series[f].map((p) => p[0])))]
        .sort().slice(-9).reverse();
      setRNeighbors({ funds, dates, series });
      setRPreload('ok');
    }).catch(() => {
      if (!current) return;
      setRPreload('error');
      setRCurrent('The book could not be read to preload the boxes; registering stays blocked until the API is back.');
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
      setRMessage({ ok: false, text: 'No value typed. To clear the date use "Clear the date".' });
      return;
    }
    if (clearAll && !window.confirm(
      `Clear ${rAfp} · ${metricName(cfg, rMetric)} · ${fDate(rDate)}: deletes the values of all its funds on that date. Continue?`)) return;
    const values = buildValues(fundsOf(rAfp), rValues, clearAll);
    const r = await apiSend('/api/spp/values', 'POST', {
      date: rDate, afp: rAfp, metric: rMetric, values,
    });
    if (!r.ok) { setRMessage({ ok: false, text: r.data.detail }); return; }
    const x = r.data.result;
    const saved = Object.keys(x.saved).length;
    setRMessage({
      ok: true,
      text: `${saved} value(s) saved`
        + (x.deleted.length ? ` · ${x.deleted.length} deleted` : '')
        + ` · ${x.afp} · ${metricName(cfg, x.metric)} · ${fDate(x.date)}`
        + (x.new_row ? ' · new row in the book' : '')
        + (x.row_deleted ? ' · the date was left without data and dropped from the book' : ''),
    });
    setRTick((t) => t + 1);   // reload the boxes and neighbors with what was written
    loadStatus();
  };

  // ---- historical load ----
  const hRef = useRef(null);
  const [hName, setHName] = useState('No file selected');
  const [hReport, setHReport] = useState(null);
  const [hToken, setHToken] = useState(null);
  const [hEcho, setHEcho] = useState('');

  const reviewHistory = async () => {
    const f = hRef.current?.files?.[0];
    if (!f) return;
    setHName(`${f.name} · reviewing…`); setHReport(null); setHToken(null); setHEcho('');
    const fd = new FormData(); fd.append('file', f);
    const r = await apiSend('/api/spp/history/review', 'POST', fd, true);
    if (!r.ok) {
      setHName(f.name);
      setHEcho({ ok: false, text: r.data.detail });
      return;
    }
    setHName(`${f.name} · reviewed, nothing written yet`);
    setHReport(r.data.report);
    setHToken(r.data.token);
  };

  const loadHistory = async (mode) => {
    if (!hToken || !hReport) return;
    const msg = mode === 'missing'
      ? 'Load what is missing: adds new dates and fills empty cells. Changes no value that already has data. Continue?'
      : `Load and correct: besides adding what is missing, REPLACES ${nInt(hReport.changed_cells)} cell(s) that differ from the file. Continue?`;
    if (!window.confirm(msg)) return;
    const r = await apiSend('/api/spp/history/load', 'POST', { token: hToken, mode });
    if (!r.ok) { setHEcho({ ok: false, text: r.data.detail }); return; }
    setHEcho({ ok: true, text: 'Saving to the database…' });
    start(r.data.action, onTaskDone((t) => {
      if (t.error) {
        setHEcho({ ok: false, text: 'The load failed and nothing new was saved. You can retry without uploading the file again.' });
      } else {
        setHEcho({ ok: true, text: `Loaded in ${mode === 'missing' ? 'missing-only' : 'correct'} mode.` });
        setHToken(null);
      }
    }));
  };

  const historyRows = (i) => [
    ['File', `${i.file} · ${nInt(Math.round(i.bytes / 1024))} KB`],
    ['Content', `${nInt(i.dates)} dates · ${i.series} series · ${nInt(i.values)} values`],
    ['Range', `${fDate(i.from)} to ${fDate(i.to)}`],
    ['New dates', `${nInt(i.new_dates)}${i.new_cells ? ` · ${nInt(i.new_cells)} values` : ''}`],
    ['Already in the book', nInt(i.known_dates)],
    ['Empty cells that would be filled', nInt(i.fill_cells)],
    ['Cells that differ from the book', nInt(i.changed_cells)],
    ['Identical cells', nInt(i.unchanged_cells)],
  ];

  const metricStep = rMetric === 'valor_cuota' ? '0.0000001' : '0.01';

  return (
    <div className="spp-page">
      {/* The upstream masthead: brand name over the dashboard title, then
          the one-line subtitle, so every dashboard opens the same way. */}
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">SPP Unit Value</div>
      </div>
      <p className="page-sub">Register & load · act on the left, see on the right.
        No file reaches the database without having been shown first.</p>

      {/* ===== 1 · Manual registration of valor cuota ===== */}
      <div className="spp-two-up">
        <div className="panel">
          <div className="panel-title">Unit value · manual registration</div>
          <p className="page-sub">One AFP and one date, all its funds at once. The boxes are
            preloaded with what is already there: typing one replaces it and <b>leaving it
            empty deletes that value</b>. If the date is left with no value, it drops from the book.</p>
          <div className="controls spp-controls">
            <div className="field"><label htmlFor="r-date">Date</label>
              <input id="r-date" className="date-input" type="date" value={rDate}
                onChange={(e) => setRDate(e.target.value)} /></div>
            <div className="field"><label htmlFor="r-afp">AFP</label>
              <select id="r-afp" className="select" value={rAfp} onChange={(e) => setRAfp(e.target.value)}>
                {names.map((a) => <option key={a} value={a}>{a}</option>)}
              </select></div>
            <div className="field"><label htmlFor="r-metric">Metric</label>
              <select id="r-metric" className="select" value={rMetric}
                onChange={(e) => setRMetric(e.target.value)}>
                {metricsOf(cfg).map(([label, v]) => <option key={v} value={v}>{label}</option>)}
              </select></div>
          </div>
          <div className="controls spp-controls" style={{ marginTop: 10 }}>
            {fundsOf(rAfp).map((f) => (
              <div className="field" key={f}><label htmlFor={`r-fund-${f}`}>Fund {f}</label>
                <input id={`r-fund-${f}`} className="date-input" type="number" min="0"
                  step={metricStep}
                  placeholder={rMetric === 'valor_cuota' ? '0.0000000' : '0.00'}
                  value={rValues[f] ?? ''}
                  onChange={(e) => setRValues({ ...rValues, [f]: e.target.value })} /></div>
            ))}
          </div>
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn primary" disabled={rPreload !== 'ok' || busy}
              title={busy ? 'Wait for the running operation to finish' : undefined}
              onClick={() => register(false)}>Register values</button>
            <button className="btn danger" disabled={rPreload !== 'ok' || busy}
              title={busy ? 'Wait for the running operation to finish' : undefined}
              onClick={() => register(true)}>Clear the date</button>
          </div>
          <Echo echo={rMessage} />
        </div>

        <div className="panel">
          <div className="panel-title">In the book</div>
          <p className="page-sub">{rCurrent || 'Choose a date, an AFP and a metric.'}</p>
          <div className="panel-title" style={{ marginTop: 12 }}>Neighboring closes</div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Date</th>
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
                )) : <tr><td colSpan={rNeighbors.funds.length + 1} className="dim">No closes nearby.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ===== 2 · Daily scrape ===== */}
      <div className="spp-two-up">
        <div className="panel">
          <div className="panel-title">Unit value · daily scrape</div>
          <p className="page-sub">Reads the SPP variables page (last 7 business days) and
            inserts only what is missing, with the three metrics. It runs on its own every day
            at 16:00 (and retries at 16:30 and 17:00 if the SBS has not published yet); here it
            is launched by hand. It takes about 20–90 s.</p>
          <div className="controls">
            <button className="btn primary" disabled={busy}
              onClick={() => scrape(false)}>Run scrape</button>
            <button className="btn danger" disabled={busy}
              onClick={() => scrape(true)}>Run and overwrite</button>
          </div>
          <p className="page-sub flag-warn" style={{ marginTop: 10 }}>
            The SBS sits behind the Imperva WAF: <b>a Chrome window will open</b> on the
            machine running the API. Do not close it while it runs.
          </p>
          <Echo echo={scrapeEcho} />
        </div>

        <div className="panel">
          <div className="panel-title">Last unattended run</div>
          {lastScrape === undefined ? <p className="page-sub dim">Loading…</p>
            : lastScrape === null
              ? <p className="page-sub dim">The scheduler has not run the scrape yet.</p>
              : (
                <p className="page-sub">
                  {fTime(lastScrape.started_at)} on {lastScrape.machine_id} ·{' '}
                  <b className={lastScrape.status === 'success' ? 'pos' : lastScrape.status === 'error' ? 'neg' : ''}>
                    {lastScrape.status === 'success' ? 'succeeded' : lastScrape.status === 'error' ? 'failed' : lastScrape.status}
                  </b>
                  {lastScrape.run_date ? ` · expected day ${fDate(lastScrape.run_date)}` : ''}
                  {lastScrape.error ? <><br /><span className="neg">{lastScrape.error}</span></> : null}
                </p>
              )}

          <div className="panel-title" style={{ marginTop: 14 }}>Log</div>
          <Log task={task} />

          <div className="panel-title" style={{ marginTop: 14 }}>Gaps</div>
          <p className="page-sub">Consecutive business days without unit value. Runs of 1–2
            days are left out: they are Peruvian holidays, not missing information.</p>
          {(status?.gaps || []).length ? (
            <Report rows={status.gaps.map((g) =>
              [`${fDate(g.from)} to ${fDate(g.to)}`, `${g.days} bd`])} />
          ) : <p className="page-sub dim">No open gaps.</p>}
        </div>
      </div>

      {/* ===== 3 · Historical load from Excel ===== */}
      <FileUpload
        ref={hRef}
        title="Unit value · historical load from Excel"
        description={<>The SBS file <b>as downloaded</b> ("Valores cuota desde Agosto 1993",
          sheet "Valor cuota diario"). It brings the unit value only, and an empty cell is
          left as it is: the Excel never deletes.</>}
        format="valor_cuota_history"
        accept=".xls,.xlsx"
        onChange={reviewHistory}
        fileName={hName}
        actions={hToken && (<>
          <button className="btn primary" disabled={busy}
            onClick={() => loadHistory('missing')}>Load what is missing</button>
          <button className="btn danger" disabled={busy}
            onClick={() => loadHistory('replace')}>Load and correct</button>
        </>)}
        echo={hEcho}
        footer={<>
          <a className="btn" target="_blank" rel="noreferrer"
            href="https://www.sbs.gob.pe/app/stats/EstadisticaSistemaFinancieroResultadosHist.asp?c=FP-130706&Y=0">
            Open the SBS page</a>
          <a className="btn" href={apiUrl('/api/spp/export')}>↓ Download the whole book · CSV</a>
        </>}
        previewStatus={hReport && `${hReport.file} · ${nInt(hReport.dates)} dates · ${fDate(hReport.from)} to ${fDate(hReport.to)}. Nothing has been saved.`}
        preview={hReport && (<>
          <Report rows={historyRows(hReport)} />
          {hReport.changed_cells > 0 && (
            <div style={{ marginTop: 8 }}>
              <p className="page-sub"><b>{nInt(hReport.changed_cells)}</b> cell(s)
                hold a value today that differs from the file. They only change with
                "Load and correct":</p>
              <Report rows={hReport.examples.map((e) =>
                [`${fDate(e.date)} · ${e.series}`, `${e.book} → ${e.file}`])} />
            </div>
          )}
          {hReport.total_future > 0 && (
            <p className="page-sub"><b>{hReport.total_future}</b> future date(s) were
              discarded: {hReport.future_dates.join(', ')}.</p>
          )}
          {hReport.unknown_afps?.length > 0 && (
            <p className="page-sub flag-warn">The file carries AFPs that are not in the
              registry: <b>{hReport.unknown_afps.join(', ')}</b>. Their data will not load
              until they are declared in config/afps.yaml.</p>
          )}
          <Sample sample={hReport.sample} title="Last rows of the file" />
        </>)}
        previewEmpty="Choose the SBS Excel and you will see what it brings here, before anything touches the database."
      />

    </div>
  );
}
