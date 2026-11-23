// web/apps/dashboards/app/status/page.js
// ---------------------------------------------------------------------------
// Status: is the warehouse being fed? Three tables off /api/status - the data
// feeds (newest date held vs. the date expected by now), the latest run of
// every scheduler job, and the scheduler heartbeat per machine. The verdicts
// and their colours come from the API (web/api/services/status.py); this page
// only draws them. Refreshes itself every 5 minutes so it can stay open.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';
import { apiGet, num } from '../../lib/api';

const REFRESH_MS = 5 * 60 * 1000;
const OVERALL = {
  green: 'All feeds current',
  amber: 'Something is pending',
  red: 'Something needs attention',
  grey: 'Nothing to judge',
};

const fmtTs = (iso) => (iso ? new Date(iso).toLocaleString('en-GB', {
  day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
}) : '—');
const Light = ({ level, label }) => (
  <span><span className={`st-dot ${level}`} aria-hidden="true" />{label}</span>
);

export default function StatusPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () => apiGet('/api/status')
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(e.message); });
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const { feeds = [], jobs = [], schedulers = [] } = data || {};

  return (
    <div>
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">Status</div>
      </div>
      <p className="page-sub">
        {data
          ? <><Light level={data.overall} label={OVERALL[data.overall]} /> · checked {fmtTs(data.as_of)}</>
          : (error ? '—' : 'Loading…')}
      </p>

      {/* A failing API or database is itself the finding: say so in red
          instead of leaving the last good reading on screen unmarked. */}
      {error && (
        <div className="panel error">
          <Light level="red" label={`The API or the database is not answering: ${error}`} />
        </div>
      )}

      <div className="panel">
        <div className="panel-title">Data feeds</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Feed</th><th>Status</th><th>Last date</th><th>Expected</th>
                <th>Days behind</th><th>Rows</th><th>Rows prev. date</th><th>Loaded at</th>
              </tr>
            </thead>
            <tbody>
              {feeds.map((f) => (
                <tr key={f.feed}>
                  <td>{f.feed}</td>
                  <td><Light level={f.level} label={f.status} /></td>
                  <td>{f.last_date || '—'}</td>
                  <td className="dim">{f.expected_date || '—'}</td>
                  <td>{f.lag_days ?? '—'}</td>
                  <td>{num(f.rows_last_date)}</td>
                  <td className="dim">{num(f.rows_prev_date)}</td>
                  <td className="dim">{fmtTs(f.last_loaded_at)}</td>
                </tr>
              ))}
              {data && !feeds.length && <tr><td colSpan={8} className="dim">No feeds found.</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="page-sub dim" style={{ marginTop: 10, marginBottom: 0 }}>
          Days behind counts SBS reporting days (NYSE or Lima open). <b>pending</b> is one
          day behind, which is normal until that day&apos;s run; <b>thin</b> means the newest
          date has under half the rows of the previous one; <b>unscheduled</b> feeds have
          no job and are not judged.
        </p>
      </div>

      <div className="panel">
        <div className="panel-title">Scheduler jobs · latest run, last 14 days</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Job</th><th>Status</th><th>Machine</th><th>Business date</th>
                <th>Started</th><th>Finished</th><th>Error</th></tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={`${j.job_id}|${j.machine_id}`}>
                  <td>{j.job_id}</td>
                  <td><Light level={j.level} label={j.status} /></td>
                  <td>{j.machine_id}</td>
                  <td>{j.run_date || '—'}</td>
                  <td className="dim">{fmtTs(j.started_at)}</td>
                  <td className="dim">{fmtTs(j.finished_at)}</td>
                  <td className="st-error" title={j.error || ''}>{j.error || '—'}</td>
                </tr>
              ))}
              {data && !jobs.length && <tr><td colSpan={7} className="dim">No job has run in the last 14 days.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">Schedulers</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Machine</th><th>Status</th><th>Last seen</th><th>Running since</th><th>Registered jobs</th></tr>
            </thead>
            <tbody>
              {schedulers.map((s) => (
                <tr key={s.machine_id}>
                  <td>{s.machine_id}</td>
                  <td><Light level={s.level} label={s.status} /></td>
                  <td>{fmtTs(s.last_seen)}</td>
                  <td className="dim">{fmtTs(s.started_at)}</td>
                  <td className="st-error" title={s.registered_jobs}>{s.registered_jobs || '—'}</td>
                </tr>
              ))}
              {data && !schedulers.length && <tr><td colSpan={5} className="dim">No scheduler has ever reported.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
