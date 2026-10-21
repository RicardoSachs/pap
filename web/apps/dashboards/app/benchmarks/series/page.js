// web/apps/dashboards/app/benchmarks/series/page.js
// ---------------------------------------------------------------------------
// Benchmarks · Series: the priced series a basket can draw from - every
// source the pipelines load into fact_prices (Bloomberg, the SBS vector,
// the SPP valor cuota...) with its coverage - and the one write this view
// owns: registering a Bloomberg ticker the pipelines do not carry yet.
//
// The registration writes the registry only (entity, identifier, series as
// 'backfill-pending'), through the same loaders the seed files use. Nothing
// here calls Bloomberg: the machine with the terminal fetches the history on
// its next backfill run and flips the series to 'active'; the daily job
// keeps it current from then on. Until then the series has no prices and a
// basket that holds it cannot be materialized.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import { apiGet, apiSend } from '../../../lib/api';
import { fDate, nInt, todayLocal } from '../../../lib/spp';
import BenchmarkTabs from '../../../components/BenchmarkTabs';
import Echo from '../../../components/Echo';
import SppSeg from '../../../components/SppSeg';
import useShowAll from '../../../components/useShowAll';

const STATUS = {
  active: 'activa', 'backfill-pending': 'pendiente de histórico', suspended: 'suspendida',
  inactive: 'inactiva', 'error-hold': 'en error',
};
const ENTITY_TYPES = [['Valor (acción, ETF, bono)', 'security'], ['Índice', 'index'], ['Fondo', 'fund']];
// Where each source's prices come from, for the operator reading the table.
const SOURCE_NOTES = {
  bloomberg: 'Terminal Bloomberg · job prices_bloomberg (17:30 Nueva York) en la máquina con terminal.',
  sbs: 'Vector de precios SBS · job ingest_sbs (09:15) en el servidor.',
  sbs_spp: 'Valor cuota del SPP · job acquire_spp (16:00) con Chrome.',
};
// The catalog answers at most this many rows; past it the search must narrow.
const MAX_ROWS = 200;
// A ten-year history is the usual starting point for a new ticker.
const defaultStart = () => `${Number(todayLocal().slice(0, 4)) - 10}-01-01`;

export default function BenchmarksSeriesPage() {
  const [sources, setSources] = useState(null);
  const [error, setError] = useState(null);
  const loadSources = () => apiGet('/api/benchmarks/series/sources')
    .then((j) => setSources(j.sources || [])).catch((e) => setError(e.message));
  useEffect(() => { loadSources(); }, []);

  // ---- search ----
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('');
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [visible, ShowAll] = useShowAll(results || [], 15);

  const search = async (q = query, src = source) => {
    setSearching(true);
    try {
      const params = new URLSearchParams({ q, limit: MAX_ROWS });
      if (src) params.set('source', src);
      const j = await apiGet(`/api/benchmarks/series?${params}`);
      setResults(j.series || []);
    } catch (e) { setResults([]); setError(e.message); } finally { setSearching(false); }
  };
  // The source filter re-runs the search right away.
  const pickSource = (src) => { setSource(src); search(query, src); };

  // ---- register a Bloomberg ticker ----
  const [procode, setProcode] = useState('');
  const [name, setName] = useState('');
  const [ticker, setTicker] = useState('');
  const [entityType, setEntityType] = useState('security');
  const [securityType, setSecurityType] = useState('');
  const [isin, setIsin] = useState('');
  const [start, setStart] = useState('');
  const [busy, setBusy] = useState(false);
  const [echo, setEcho] = useState('');
  useEffect(() => { setStart(defaultStart()); }, []);

  const canRegister = procode.trim() && name.trim() && ticker.trim() && start && !busy;

  const register = async () => {
    setEcho(''); setBusy(true);
    const r = await apiSend('/api/benchmarks/series', 'POST', {
      procode: procode.trim().toUpperCase(), name: name.trim(), parsekyable: ticker.trim(),
      default_start_date: start, entity_type: entityType,
      security_type: securityType.trim() || null, isin: isin.trim() || null,
    });
    setBusy(false);
    if (!r.ok) { setEcho({ ok: false, text: r.data.detail }); return; }
    const s = r.data;
    setEcho({
      ok: true,
      text: s.created
        ? `${s.procode} registrada (serie ${s.series_id}, ${s.ticker}) como pendiente de histórico: `
          + 'la máquina Bloomberg la traerá en su próxima corrida de backfill.'
        : `${s.procode} ya estaba registrada (serie ${s.series_id}, ${STATUS[s.status] || s.status}); nada cambió.`,
    });
    if (s.created) { setProcode(''); setName(''); setTicker(''); setSecurityType(''); setIsin(''); }
    loadSources();
    setQuery(s.procode); setSource('');
    search(s.procode, '');
  };

  return (
    <div className="bm-page">
      <h1 className="page-title">Benchmarks</h1>
      <p className="page-sub">Series · las series de precios con las que se arma una canasta, por fuente,
        y el registro de tickers de Bloomberg que los pipelines todavía no traen.</p>
      <BenchmarkTabs />

      {error && <div className="panel error">Error: {error}</div>}

      {/* ===== a · the sources ===== */}
      <div className="panel">
        <div className="panel-title">Fuentes de precios</div>
        <p className="page-sub">Todo lo que los pipelines cargan en la base es candidato a componente:
          el tablero solo lee. Una serie <b>pendiente de histórico</b> ya está registrada pero su
          fuente no la ha traído todavía.</p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Fuente</th><th className="num">Series</th><th className="num">Con precios</th>
              <th className="num">Pendientes</th><th className="num">Precios</th><th>Desde</th><th>Hasta</th>
              <th>Cómo llegan</th></tr></thead>
            <tbody>
              {sources === null && <tr><td colSpan={8} className="dim">Cargando…</td></tr>}
              {sources && !sources.length && (
                <tr><td colSpan={8} className="dim">Ninguna serie de precios registrada.</td></tr>
              )}
              {(sources || []).map((s) => (
                <tr key={s.source}>
                  <td className="mono">{s.source}</td>
                  <td className="num">{nInt(s.series)}</td>
                  <td className="num">{nInt(s.priced)}</td>
                  <td className={`num ${s.pending ? 'neg' : 'dim'}`}>{nInt(s.pending)}</td>
                  <td className="num">{nInt(s.points)}</td>
                  <td>{fDate(s.from)}</td>
                  <td>{fDate(s.to)}</td>
                  <td className="dim">{SOURCE_NOTES[s.source] || 'Pipeline de la fuente.'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ===== b · search ===== */}
      <div className="panel">
        <div className="panel-title">Buscar series</div>
        <div className="controls spp-controls">
          <div className="field" style={{ flex: '1 1 320px' }}>
            <label htmlFor="s-q">Código, ticker, nombre o ISIN</label>
            <input id="s-q" className="date-input" placeholder="p. ej. SPY, Habitat, US78462F1030"
              value={query} onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && search()} /></div>
          {sources && sources.length > 0 && (
            <div className="field"><label>Fuente</label>
              <SppSeg items={[['Todas', ''], ...sources.map((s) => [s.source, s.source])]}
                value={source} onChange={pickSource} /></div>
          )}
          <div className="field"><label aria-hidden="true">&nbsp;</label>
            <button className="btn primary" disabled={searching} onClick={() => search()}>Buscar</button></div>
        </div>
        {results && (
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead><tr><th>Código</th><th>Ticker</th><th>Nombre</th><th>Campo</th><th>Fuente</th>
                <th>Estado</th><th>Cobertura</th><th className="num">Precios</th></tr></thead>
              <tbody>
                {visible.map((s) => (
                  <tr key={s.series_id}>
                    <td className="mono">{s.procode}</td>
                    <td className="mono">{s.ticker || '—'}</td>
                    <td>{s.name || '—'}{s.currency ? <span className="dim"> · {s.currency}</span> : null}</td>
                    <td className="dim">{s.field}</td>
                    <td className="mono">{s.source}</td>
                    <td className={s.status === 'active' ? '' : 'neg'}>{STATUS[s.status] || s.status}</td>
                    <td className={s.points ? '' : 'dim'}>{s.points ? `${fDate(s.from)} – ${fDate(s.to)}` : '—'}</td>
                    <td className={`num ${s.points ? '' : 'dim'}`}>{s.points ? nInt(s.points) : 'sin precios'}</td>
                  </tr>
                ))}
                {!results.length && <tr><td colSpan={8} className="dim">Sin resultados.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        {results && <ShowAll label="series" />}
        {results && results.length >= MAX_ROWS && (
          <p className="page-sub dim">Se muestran las primeras {MAX_ROWS}: afina la búsqueda.</p>
        )}
      </div>

      {/* ===== c · register a Bloomberg ticker ===== */}
      <div className="panel">
        <div className="panel-title">Registrar un ticker de Bloomberg</div>
        <p className="page-sub">Da de alta la serie en el registro de la base, igual que lo haría el
          archivo de semillas: entidad, identificador Bloomberg y serie <b>PX_LAST</b> diaria, en estado
          pendiente de histórico. Este tablero <b>no</b> habla con Bloomberg: la máquina con terminal
          trae el histórico desde la fecha de inicio en su próxima corrida de backfill
          (<span className="mono">run_prices.py --source bloomberg --backfill</span>) y la deja activa;
          desde entonces el job diario la mantiene al día.</p>
        <div className="controls spp-controls">
          <div className="field" style={{ flex: '0 1 200px' }}>
            <label htmlFor="r-procode">Código (procode)</label>
            <input id="r-procode" className="date-input mono" placeholder="p. ej. SPY_US"
              value={procode} onChange={(e) => setProcode(e.target.value)} /></div>
          <div className="field" style={{ flex: '1 1 260px' }}>
            <label htmlFor="r-name">Nombre</label>
            <input id="r-name" className="date-input" placeholder="p. ej. SPDR S&P 500 ETF"
              value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="field" style={{ flex: '0 1 220px' }}>
            <label htmlFor="r-ticker">Ticker Bloomberg</label>
            <input id="r-ticker" className="date-input mono" placeholder="p. ej. SPY US Equity"
              value={ticker} onChange={(e) => setTicker(e.target.value)} /></div>
        </div>
        <div className="controls spp-controls" style={{ marginTop: 8 }}>
          <div className="field"><label>Tipo</label>
            <SppSeg items={ENTITY_TYPES} value={entityType} onChange={setEntityType} /></div>
          <div className="field" style={{ flex: '0 1 160px' }}>
            <label htmlFor="r-sectype">Instrumento (opcional)</label>
            <input id="r-sectype" className="date-input" placeholder="p. ej. ETF"
              value={securityType} onChange={(e) => setSecurityType(e.target.value)} /></div>
          <div className="field" style={{ flex: '0 1 180px' }}>
            <label htmlFor="r-isin">ISIN (opcional)</label>
            <input id="r-isin" className="date-input mono" placeholder="US78462F1030"
              value={isin} onChange={(e) => setIsin(e.target.value)} /></div>
          <div className="field"><label htmlFor="r-start">Histórico desde</label>
            <input id="r-start" className="date-input" type="date" value={start}
              onChange={(e) => setStart(e.target.value)} /></div>
          <div className="field"><label aria-hidden="true">&nbsp;</label>
            <button className="btn primary" disabled={!canRegister} onClick={register}>Registrar serie</button></div>
        </div>
        <Echo echo={echo} />
      </div>
    </div>
  );
}
