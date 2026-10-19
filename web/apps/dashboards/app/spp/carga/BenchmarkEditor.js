// web/apps/dashboards/app/spp/carga/BenchmarkEditor.js
// ---------------------------------------------------------------------------
// The composite indices (benchmarks, targets) in Registro y carga: which
// exist, and the editor of their VERSIONED definition.
//
// A benchmark is a portfolio row with a level series; what it is made of
// lives in append-only versions (dim_benchmark_version). This editor never
// edits or deletes a version: every change - new weights, a swapped ticker,
// a correction - is a NEW version with its effective date, a change type
// and a reason that cannot be blank. The history on the right is the
// changelog view, read back from the database, not something kept here.
//
// Saving a version also materializes the benchmark (levels, valuation and
// holdings) in the shared background task; the component is handed the
// task hook by the page that mounts it. Constituents come from ONE catalog:
// the pipeline's priced series (series_registry / fact_prices), minus the
// model series themselves.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';

import Echo from '../../../components/Echo';
import Log from '../../../components/Log';
import SppSeg from '../../../components/SppSeg';
import useShowAll from '../../../components/useShowAll';
import { apiGet, apiSend } from '../../../lib/api';
import { apiUrl, fDate, fTime, nInt, todayLocal } from '../../../lib/spp';

const METHODS = [['Buy and hold (deriva)', 'buy_and_hold'], ['Pesos fijos', 'fixed_weights']];
const FREQUENCIES = [['Mensual', 'monthly'], ['Trimestral', 'quarterly'], ['Anual', 'annual']];
const CHANGE_TYPES = {
  initial: 'Versión inicial', rebalance: 'Rebalanceo', methodology: 'Cambio de metodología',
  constituent_change: 'Cambio de componentes', correction: 'Corrección',
};
const CHANGE_MARK = { added: '+ nuevo', dropped: '− sale', reweighted: '≠ peso', unchanged: '' };

// Small key/value report table, the same one the rest of the view uses.
function Report({ rows }) {
  return (
    <table className="spp-report"><tbody>
      {rows.map(([a, b], i) => (
        <tr key={i}><td>{a}</td><td className="num">{b}</td></tr>
      ))}
    </tbody></table>
  );
}

const pctOf = (w) => `${(w * 100).toLocaleString('es-PE', { maximumFractionDigits: 2 })} %`;

export default function BenchmarkEditor({ refreshCfg, busy, task, start, onTaskDone }) {
  // ---- which benchmarks exist ----
  const [list, setList] = useState(null);
  const [selected, setSelected] = useState('');
  const loadList = () => apiGet('/api/benchmarks')
    .then((j) => {
      const items = j.benchmarks || [];
      setList(items);
      setSelected((s) => (s && items.some((b) => b.procode === s)) ? s : (items[0]?.procode || ''));
    })
    .catch(() => setList([]));
  const current = (list || []).find((b) => b.procode === selected) || null;

  // ---- create / rename ----
  const [newProcode, setNewProcode] = useState('');
  const [newName, setNewName] = useState('');
  const [createEcho, setCreateEcho] = useState('');

  const createBenchmark = async () => {
    setCreateEcho('');
    const r = await apiSend('/api/benchmarks', 'POST',
      { procode: newProcode.trim().toUpperCase(), display_name: newName.trim() });
    if (!r.ok) { setCreateEcho({ ok: false, text: r.data.detail }); return; }
    setCreateEcho({ ok: true, text: `${r.data.procode}: «${r.data.display_name}».` });
    setNewProcode(''); setNewName('');
    await loadList();
    setSelected(r.data.procode);
    // A new benchmark changes the list the Libro offers.
    refreshCfg();
  };

  // ---- versions of the selected benchmark ----
  const [versions, setVersions] = useState([]);
  const [changelog, setChangelog] = useState([]);
  const loadVersions = (procode) => {
    if (!procode) { setVersions([]); setChangelog([]); return; }
    const p = encodeURIComponent(procode);
    apiGet(`/api/benchmarks/${p}/versions`).then((j) => setVersions(j.versions || [])).catch(() => setVersions([]));
    apiGet(`/api/benchmarks/${p}/changelog`).then((j) => setChangelog(j.changelog || [])).catch(() => setChangelog([]));
  };
  const latest = versions.length ? versions[versions.length - 1] : null;

  // ---- the new version form ----
  const [effectiveFrom, setEffectiveFrom] = useState('');
  const [method, setMethod] = useState('buy_and_hold');
  const [frequency, setFrequency] = useState('monthly');
  const [changeType, setChangeType] = useState('rebalance');
  const [reason, setReason] = useState('');
  const [supportDoc, setSupportDoc] = useState('');
  const [recordedBy, setRecordedBy] = useState('');
  const [constituents, setConstituents] = useState([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [fxCatalog, setFxCatalog] = useState([]);
  const [saveEcho, setSaveEcho] = useState('');

  useEffect(() => {
    setEffectiveFrom(todayLocal());
    loadList();
    // A small catalog, always loaded, for the FX selectors.
    apiGet('/api/benchmarks/series?limit=200').then((j) => setFxCatalog(j.series || [])).catch(() => {});
  }, []);

  useEffect(() => { loadVersions(selected); setSaveEcho(''); }, [selected]);

  // The first version of a benchmark is 'initial'; afterwards the operator
  // says what kind of change it is.
  useEffect(() => {
    setChangeType(versions.length ? 'rebalance' : 'initial');
  }, [versions.length]);

  const [visibleResults, ShowMoreResults] = useShowAll(results || [], 8);

  const searchSeries = async () => {
    try {
      const j = await apiGet(`/api/benchmarks/series?q=${encodeURIComponent(query)}`);
      setResults(j.series || []);
    } catch { setResults([]); }
  };

  const addConstituent = (s) => {
    if (constituents.some((c) => c.series_id === s.series_id)) return;
    setConstituents([...constituents, {
      label: s.label, series_id: s.series_id, detail: s.detail, weight: '', fx_series_id: '',
    }]);
  };

  const weightSum = constituents.reduce((a, c) => a + (Number(c.weight) || 0), 0);
  const sumOk = Math.abs(weightSum - 1) < 1e-6 || Math.abs(weightSum - 100) < 1e-4;
  const canSave = !!current && constituents.length > 0 && sumOk && !!effectiveFrom
    && reason.trim().length > 0 && !busy;

  // Loads the latest version's basket into the form, to adjust and save as
  // a new version - the only way to "edit" an append-only definition.
  const loadLatest = () => {
    if (!latest) return;
    setMethod(latest.method);
    setFrequency(latest.rebalance_frequency || 'monthly');
    setConstituents(latest.constituents.map((c) => ({
      label: c.label, series_id: c.series_id,
      detail: `${c.field} · ${c.source} · ${c.procode}`,
      weight: String(+(c.weight * 100).toFixed(4)),
      fx_series_id: c.fx_series_id ? String(c.fx_series_id) : '',
    })));
    setSaveEcho({ ok: true, text: `Canasta de la versión ${latest.version_id} cargada en el editor; guardar crea una versión nueva.` });
  };

  const materialize = async (procode, label) => {
    const r = await apiSend(`/api/benchmarks/${encodeURIComponent(procode)}/materialize`, 'POST');
    if (!r.ok) { setSaveEcho({ ok: false, text: r.data.detail }); return; }
    setSaveEcho({ ok: true, text: `Recalculando ${label}…` });
    start(r.data.action, onTaskDone((t) => {
      loadList();
      setSaveEcho(t.error
        ? { ok: false, text: `El recálculo falló y la serie anterior sigue intacta: ${t.error}` }
        : { ok: true, text: `${label} recalculado desde sus versiones.` });
    }));
  };

  const saveVersion = async () => {
    if (!current) return;
    setSaveEcho('');
    const body = {
      effective_from: effectiveFrom,
      method,
      rebalance_frequency: method === 'fixed_weights' ? frequency : null,
      change_type: changeType,
      reason: reason.trim(),
      support_doc: supportDoc.trim() || null,
      recorded_by: recordedBy.trim() || null,
      supersedes_version_id: latest ? latest.version_id : null,
      constituents: constituents.map((c) => ({
        label: c.label, series_id: c.series_id, weight: Number(c.weight),
        fx_series_id: c.fx_series_id ? Number(c.fx_series_id) : null,
      })),
    };
    const r = await apiSend(`/api/benchmarks/${encodeURIComponent(current.procode)}/versions`, 'POST', body);
    if (!r.ok) { setSaveEcho({ ok: false, text: r.data.detail }); return; }
    setReason(''); setSupportDoc('');
    loadVersions(current.procode);
    setSaveEcho({ ok: true, text: `Versión ${r.data.version_id} guardada, vigente desde ${fDate(effectiveFrom)}.` });
    await materialize(current.procode, current.display_name);
  };

  // Changelog rows of one version, by series, for the marks in the history.
  const changesOf = (versionId) => {
    const out = {};
    changelog.filter((r) => r.version_id === versionId).forEach((r) => { out[r.series_id] = r; });
    return out;
  };

  return (
    <>
      {/* ===== a · which exist ===== */}
      <div className="panel">
        <div className="panel-title">Benchmarks declarados</div>
        <p className="page-sub">Cada índice compuesto es un portafolio con su serie de niveles.
          Declararlo le pone nombre y registra su serie; su canasta se define por <b>versiones</b>,
          en el editor de abajo.</p>

        <div className="table-wrap">
          <table>
            <thead><tr><th>Código</th><th>Nombre</th><th className="num">Versiones</th>
              <th className="num">Días calculados</th><th>Desde</th><th>Hasta</th><th className="num">Último nivel</th></tr></thead>
            <tbody>
              {list === null && <tr><td colSpan={7} className="dim">Cargando…</td></tr>}
              {list && !list.length && <tr><td colSpan={7} className="dim">Ningún benchmark declarado todavía.</td></tr>}
              {(list || []).map((b) => (
                <tr key={b.procode} style={b.procode === selected ? { fontWeight: 700 } : undefined}>
                  <td className="mono">{b.procode}</td>
                  <td>{b.display_name}</td>
                  <td className="num">{nInt(b.versions)}</td>
                  <td className={`num ${b.points ? '' : 'dim'}`}>{b.points ? nInt(b.points) : 'sin calcular'}</td>
                  <td>{fDate(b.from)}</td>
                  <td>{fDate(b.to)}</td>
                  <td className="num">{b.last_level == null ? '—'
                    : b.last_level.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="controls spp-controls" style={{ marginTop: 12 }}>
          <div className="field" style={{ flex: '0 1 220px' }}>
            <label htmlFor="b-procode">Código (procode)</label>
            <input id="b-procode" className="date-input mono" placeholder="p. ej. SPP_BENCH_F2"
              value={newProcode} onChange={(e) => setNewProcode(e.target.value)} /></div>
          <div className="field" style={{ flex: '1 1 260px' }}>
            <label htmlFor="b-name">Nombre</label>
            <input id="b-name" className="date-input" placeholder="p. ej. Renta mixta global 60/40"
              value={newName} onChange={(e) => setNewName(e.target.value)} /></div>
          <div className="field"><label aria-hidden="true">&nbsp;</label>
            <button className="btn primary" disabled={!newProcode.trim() || !newName.trim() || busy}
              onClick={createBenchmark}>
              {(list || []).some((b) => b.procode === newProcode.trim().toUpperCase()) ? 'Renombrar' : 'Declarar benchmark'}</button></div>
        </div>
        <Echo echo={createEcho} />
      </div>

      {/* ===== b · the versioned definition ===== */}
      <div className="spp-two-up">
        <div className="panel">
          <div className="panel-title">Nueva versión de «{current?.display_name || '—'}»</div>
          <p className="page-sub">La canasta es <b>append-only</b>: cambiar pesos o componentes no edita
            nada, crea una versión nueva desde su fecha de vigencia, con un motivo. Con
            <b> buy and hold</b> los pesos derivan con los precios entre versiones; con
            <b> pesos fijos</b> se restablecen cada periodo. Los niveles se recalculan desde la
            primera versión (base 100) y nunca se cargan a mano.</p>

          <div className="controls spp-controls">
            <div className="field"><label>Benchmark</label>
              <SppSeg items={(list || []).map((b) => [b.display_name, b.procode])}
                value={selected} onChange={setSelected} /></div>
          </div>
          <div className="controls spp-controls" style={{ marginTop: 8 }}>
            <div className="field"><label htmlFor="v-from">Vigente desde</label>
              <input id="v-from" className="date-input" type="date" value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)} /></div>
            <div className="field"><label>Método</label>
              <SppSeg items={METHODS} value={method} onChange={setMethod} /></div>
            {method === 'fixed_weights' && (
              <div className="field"><label>Rebalanceo</label>
                <SppSeg items={FREQUENCIES} value={frequency} onChange={setFrequency} /></div>
            )}
            <div className="field"><label htmlFor="v-type">Tipo de cambio</label>
              <select id="v-type" className="select" value={changeType}
                disabled={!versions.length}
                onChange={(e) => setChangeType(e.target.value)}>
                {Object.entries(CHANGE_TYPES)
                  .filter(([k]) => (versions.length ? k !== 'initial' : k === 'initial'))
                  .map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select></div>
          </div>
          <div className="controls spp-controls" style={{ marginTop: 8 }}>
            <div className="field" style={{ flex: '1 1 320px' }}>
              <label htmlFor="v-reason">Motivo (obligatorio)</label>
              <input id="v-reason" className="date-input" placeholder="p. ej. Comité trimestral: sobreponderar renta variable"
                value={reason} onChange={(e) => setReason(e.target.value)} /></div>
            <div className="field" style={{ flex: '1 1 200px' }}>
              <label htmlFor="v-doc">Documento de respaldo</label>
              <input id="v-doc" className="date-input" placeholder="ruta en la red (opcional)"
                value={supportDoc} onChange={(e) => setSupportDoc(e.target.value)} /></div>
            <div className="field" style={{ flex: '0 1 160px' }}>
              <label htmlFor="v-by">Registrado por</label>
              <input id="v-by" className="date-input" placeholder="iniciales"
                value={recordedBy} onChange={(e) => setRecordedBy(e.target.value)} /></div>
          </div>
          {latest && (
            <p className="page-sub dim" style={{ marginTop: 6 }}>
              Reemplaza a la versión {latest.version_id} (vigente desde {fDate(latest.effective_from)}).
              {' '}<button type="button" className="btn" style={{ marginLeft: 6 }} onClick={loadLatest}>
                Cargar su canasta en el editor</button>
            </p>
          )}

          <div className="controls" style={{ marginTop: 10 }}>
            <input className="date-input" placeholder="Buscar serie (ticker, nombre)…"
              aria-label="Buscar serie"
              value={query} onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && searchSeries()} />
            <button className="btn" onClick={searchSeries}>Buscar</button>
          </div>
          {results && (
            <div className="table-wrap" style={{ marginTop: 8 }}>
              <table><tbody>
                {visibleResults.map((s) => (
                  <tr key={s.series_id}>
                    <td className="mono">{s.label}</td>
                    <td className="dim">{s.detail}</td>
                    <td><button className="btn" onClick={() => addConstituent(s)}>+ Agregar</button></td>
                  </tr>
                ))}
                {!results.length && <tr><td className="dim">Sin resultados.</td></tr>}
              </tbody></table>
            </div>
          )}
          {results && <ShowMoreResults label="series encontradas" />}

          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead><tr><th>Componente</th><th>Serie</th><th className="num">Peso</th>
                <th>FX (opcional)</th><th></th></tr></thead>
              <tbody>
                {constituents.length ? constituents.map((c, i) => (
                  <tr key={c.series_id}>
                    <td className="mono">{c.label}</td>
                    <td className="dim">{c.detail}</td>
                    <td className="num">
                      <input className="date-input" type="number" min="0" step="0.01"
                        style={{ width: 90 }} value={c.weight} aria-label={`Peso de ${c.label}`}
                        onChange={(e) => setConstituents(
                          constituents.map((x, j) => (j === i ? { ...x, weight: e.target.value } : x)))} />
                    </td>
                    <td>
                      <select className="select" value={c.fx_series_id} aria-label={`FX de ${c.label}`}
                        onChange={(e) => setConstituents(
                          constituents.map((x, j) => (j === i ? { ...x, fx_series_id: e.target.value } : x)))}>
                        <option value="">— sin conversión —</option>
                        {fxCatalog.map((s) => (
                          <option key={s.series_id} value={String(s.series_id)}>{s.label} · {s.field} · {s.source}</option>
                        ))}
                      </select>
                    </td>
                    <td><button className="btn danger"
                      onClick={() => setConstituents(constituents.filter((_, j) => j !== i))}>Quitar</button></td>
                  </tr>
                )) : <tr><td colSpan={5} className="dim">Busca series y agrégalas a la canasta.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="page-sub">Suma de pesos: <b className={sumOk ? 'pos' : 'neg'}>
            {weightSum.toLocaleString('es-PE', { maximumFractionDigits: 4 })}</b> (debe ser 1 o 100)</p>

          <div className="controls">
            <button className="btn primary" disabled={!canSave} onClick={saveVersion}
              title={reason.trim() ? undefined : 'Escribe el motivo de la versión'}>
              Guardar versión y recalcular</button>
            <button className="btn" disabled={!current || !versions.length || busy}
              onClick={() => materialize(current.procode, current.display_name)}>
              Recalcular «{current?.display_name || '—'}»</button>
          </div>
          <Echo echo={saveEcho} />
          {/* The materialization runs in the shared task; its trail shows here. */}
          {task && <Log task={task} />}
        </div>

        <div className="panel">
          <div className="panel-title">Serie calculada</div>
          <p className="page-sub">
            {current?.points
              ? `${nInt(current.points)} fechas · ${fDate(current.from)} a ${fDate(current.to)} · último nivel ${
                current.last_level.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
              : 'Todavía no hay serie calculada: guarda una versión y recalcula.'}
          </p>
          {current?.points > 0 && (
            <div className="controls" style={{ marginBottom: 12 }}>
              <a className="btn" href={apiUrl(`/api/benchmarks/${encodeURIComponent(current.procode)}/export`)}>
                ↓ Bajar la serie · XLSX</a>
            </div>
          )}

          <div className="panel-title">Historial de versiones</div>
          <p className="page-sub">Cada versión rige desde su fecha hasta la siguiente. Nada se borra:
            una corrección es otra versión que dice a cuál reemplaza y por qué.</p>
          {versions.length ? [...versions].reverse().map((v) => {
            const changes = changesOf(v.version_id);
            const dropped = Object.values(changes).filter((r) => r.change === 'dropped');
            return (
              <div key={v.version_id} style={{ marginBottom: 14 }}>
                <div className="panel-title" style={{ fontSize: 13 }}>
                  Versión {v.version_id} · desde {fDate(v.effective_from)} · {CHANGE_TYPES[v.change_type] || v.change_type}
                </div>
                <p className="page-sub" style={{ margin: '2px 0 6px' }}>
                  <b>{v.reason}</b>
                  {' · '}{METHODS.find(([, k]) => k === v.method)?.[0] || v.method}
                  {v.rebalance_frequency ? ` (${FREQUENCIES.find(([, k]) => k === v.rebalance_frequency)?.[0] || v.rebalance_frequency})` : ''}
                  {v.supersedes_version_id ? ` · reemplaza a la ${v.supersedes_version_id}` : ''}
                  {' · registrada el '}{fTime(v.created_at)}{v.recorded_by ? ` por ${v.recorded_by}` : ''}
                  {v.support_doc ? <> · <span className="mono">{v.support_doc}</span></> : null}
                </p>
                <Report rows={[
                  ...v.constituents.map((c) => {
                    const ch = changes[c.series_id];
                    const mark = ch ? CHANGE_MARK[ch.change] : '';
                    const before = ch && ch.change === 'reweighted' ? ` (antes ${pctOf(ch.weight_before)})` : '';
                    return [`${c.label}${c.fx_series_id ? ' (con FX)' : ''}${mark ? ` · ${mark}` : ''}`,
                      `${pctOf(c.weight)}${before}`];
                  }),
                  ...dropped.map((r) => [`${r.label} · ${CHANGE_MARK.dropped}`, `antes ${pctOf(r.weight_before)}`]),
                ]} />
              </div>
            );
          }) : <p className="page-sub dim">Ninguna versión todavía.</p>}
        </div>
      </div>
    </>
  );
}
