// web/apps/dashboards/app/spp/libro/page.js
// ---------------------------------------------------------------------------
// SPP tablero · Libro: the stored series, day by day.
//
// Several books, one on screen at a time: the AFPs' valor cuota (filtered
// by metric / fund / row count, with a CSV of exactly what is shown), and
// one per benchmark declared in the database. They are separate tables on
// purpose: side by side they would be one wide grid where nothing reads
// well.
//
// A benchmark table is laid over the SAME date grid as the book, because
// the question it answers is "which days is the index missing": listing
// only the days it has would hide exactly what one is looking for.
//
// The benchmark books are not written here: the list comes from the config
// (cfg.benchmarks), so declaring another benchmark does not touch this file.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import { apiGet } from '../../../lib/api';
import { apiUrl, fDate, fmtMetric, metricsOf, nInt, metricName } from '../../../lib/spp';
import SppSeg from '../../../components/SppSeg';
import SppTabs from '../../../components/SppTabs';

// 0 asks the API for the whole book.
const LIMITS = [['60', 60], ['250', 250], ['1000', 1000], ['Todas', 0]];

export default function SppLibroPage() {
  const [cfg, setCfg] = useState(null);
  const [book, setBook] = useState('vc');
  const [metric, setMetric] = useState('valor_cuota');
  const [fund, setFund] = useState('all');
  const [limit, setLimit] = useState(60);
  const [data, setData] = useState(null);
  const [index, setIndex] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet('/api/spp/config').then(setCfg).catch((e) => setError(e.message));
  }, []);

  const benchmarks = (cfg?.benchmarks || []).map((b) => [b.display_name, b.procode]);
  const BOOKS = [['Valor cuota', 'vc'], ...benchmarks];
  const isIndex = book !== 'vc';
  const indexLabel = (benchmarks.find(([, v]) => v === book) || [book])[0];

  useEffect(() => {
    setLoading(true); setError(null);
    // Stale-response guard: "Todas" over the whole book takes seconds while
    // "60" comes back instantly, so a late reply for a previous selection
    // could land on top of the current one - thousands of rows under a
    // segment that says 60, with nothing to signal the mismatch.
    let current = true;
    const path = isIndex
      ? `/api/benchmarks/${encodeURIComponent(book)}/table?${new URLSearchParams({ limit })}`
      : `/api/spp/table?${new URLSearchParams({ limit, metric, fund })}`;
    apiGet(path)
      .then((d) => { if (current) (isIndex ? setIndex : setData)(d); })
      .catch((e) => { if (current) setError(e.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book, metric, fund, limit]);

  const shown = isIndex ? index : data;
  const columns = shown?.columns || [];
  const rows = shown?.rows || [];

  const downloadUrl = isIndex
    ? apiUrl(`/api/benchmarks/${encodeURIComponent(book)}/export`)
    : apiUrl(`/api/spp/export?${new URLSearchParams({ metric, fund, limit })}`);

  const header = (c) => {
    if (isIndex) return c.label;
    const base = `${c.afp} F${c.fund}`;
    return metric === 'all' ? `${base} · ${metricName(cfg, c.metric)}` : base;
  };

  const summary = () => {
    if (!rows.length) return '—';
    if (!isIndex) return `${nInt(rows.length)} filas en pantalla`;
    const missing = index?.missing || 0;
    return missing
      ? `${nInt(rows.length)} fechas · ${nInt(missing)} sin ${indexLabel}`
      : `${nInt(rows.length)} fechas · sin huecos`;
  };

  return (
    <div className="spp-page">
      <h1 className="page-title">Valor Cuota SPP</h1>
      <p className="page-sub">
        Libro {isIndex ? `de ${indexLabel}` : 'de valores cuota'} · {summary()}
      </p>
      <SppTabs />

      <div className="panel">
        <div className="controls spp-controls">
          <div className="field"><label>Libro</label>
            <SppSeg items={BOOKS} value={book} onChange={setBook} /></div>
          {!isIndex && (
            <>
              <div className="field"><label>Métrica</label>
                <SppSeg items={[...metricsOf(cfg), ['Todas', 'all']]}
                  value={metric} onChange={setMetric} /></div>
              <div className="field"><label>Tipo de fondo</label>
                <SppSeg items={[...(cfg?.funds || []).map((f) => [`Fondo ${f}`, String(f)]),
                  ['Todos', 'all']]}
                  value={fund} onChange={setFund} /></div>
            </>
          )}
          <div className="field"><label>Filas</label>
            <SppSeg items={LIMITS} value={limit} onChange={setLimit} /></div>
          <div className="field"><label aria-hidden="true">&nbsp;</label>
            <a className="btn" href={downloadUrl}>
              {isIndex ? `↓ Bajar ${indexLabel} · XLSX` : '↓ Bajar lo que veo · CSV'}</a></div>
        </div>
        {isIndex && (
          <p className="page-sub dim" style={{ marginTop: 10, marginBottom: 0 }}>
            Las fechas son las del libro de valor cuota: así un día sin nivel se ve como
            un hueco en vez de desaparecer de la lista. El nivel lo produce el recálculo
            de la canasta, en <b>Registro y carga → Benchmarks</b>.
          </p>
        )}
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
                        {v == null ? '—'
                          : isIndex
                            // Index levels: never abbreviated. fmtMetric in
                            // compact mode would turn 1,500 points into "1,50 M".
                            ? Number(v).toLocaleString('es-PE',
                              { minimumFractionDigits: 2, maximumFractionDigits: 4 })
                            : fmtMetric(v, columns[i]?.metric || metric, true)}
                      </td>
                    ))}
                  </tr>
                ))}
                {!rows.length && (
                  <tr><td colSpan={columns.length + 1} className="dim">
                    {isIndex ? 'No hay fechas en el libro todavía.' : 'El libro está vacío.'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
