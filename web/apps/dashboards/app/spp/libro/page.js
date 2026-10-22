// web/apps/dashboards/app/spp/libro/page.js
// ---------------------------------------------------------------------------
// SPP tablero · Libro: the stored valor cuota, day by day, filtered by
// metric / fund / row count, with a CSV of exactly what is shown. The
// benchmark books live in the Benchmarks module.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import { apiGet } from '../../../lib/api';
import { apiUrl, fDate, fmtMetric, metricsOf, nInt, metricName } from '../../../lib/spp';
import SppSeg from '../../../components/SppSeg';
import { useModule } from '../../../components/ModuleContext';

// 0 asks the API for the whole book.
const LIMITS = [['60', 60], ['250', 250], ['1000', 1000], ['Todas', 0]];

export default function SppLibroPage() {
  const [cfg, setCfg] = useState(null);
  const [metric, setMetric] = useState('valor_cuota');
  // The fund type comes from the floating pill ('all' = every fund).
  const pill = useModule();
  const fund = pill?.fund == null ? 'all' : String(pill.fund);
  const [limit, setLimit] = useState(60);
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
    let current = true;
    apiGet(`/api/spp/table?${new URLSearchParams({ limit, metric, fund })}`)
      .then((d) => { if (current) setData(d); })
      .catch((e) => { if (current) setError(e.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [metric, fund, limit]);

  const columns = data?.columns || [];
  const rows = data?.rows || [];
  const downloadUrl = apiUrl(`/api/spp/export?${new URLSearchParams({ metric, fund, limit })}`);

  const header = (c) => {
    const base = `${c.afp} F${c.fund}`;
    return metric === 'all' ? `${base} · ${metricName(cfg, c.metric)}` : base;
  };

  return (
    <div className="spp-page">
      {/* The upstream masthead: brand name over the dashboard title, then
          the one-line subtitle, so every dashboard opens the same way. */}
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">Valor Cuota SPP</div>
      </div>
      <p className="page-sub">
        Libro de valores cuota · {rows.length ? `${nInt(rows.length)} filas en pantalla` : '—'}
      </p>
      <div className="panel">
        <div className="controls spp-controls">
          <div className="field"><label>Métrica</label>
            <SppSeg items={[...metricsOf(cfg), ['Todas', 'all']]}
              value={metric} onChange={setMetric} /></div>
          <div className="field"><label>Filas</label>
            <SppSeg items={LIMITS} value={limit} onChange={setLimit} /></div>
          <div className="field"><label aria-hidden="true">&nbsp;</label>
            <a className="btn" href={downloadUrl}>↓ Bajar lo que veo · CSV</a></div>
        </div>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      <div className="panel">
        {loading ? <div className="loading">Cargando…</div> : (
          <div className="table-wrap spp-windows">
            <table>
              <thead>
                <tr><th>Fecha</th>{columns.map((c) => <th key={c.col} className="num">{header(c)}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.date}>
                    <td>{fDate(r.date)}</td>
                    {r.values.map((v, i) => (
                      <td key={columns[i]?.col || i} className={`num ${v == null ? 'dim' : ''}`}>
                        {v == null ? '—' : fmtMetric(v, columns[i]?.metric || metric, true)}
                      </td>
                    ))}
                  </tr>
                ))}
                {!rows.length && (
                  <tr><td colSpan={columns.length + 1} className="dim">El libro está vacío.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
