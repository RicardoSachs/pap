// web/apps/dashboards/app/benchmarks/registro/page.js
// ---------------------------------------------------------------------------
// Benchmarks · Registry: declaring a benchmark, appending versions of its
// basket and materializing the levels. The editor owns the forms; this page
// gives it the shared background task (one slot for every dashboard) and
// the module frame.
// ---------------------------------------------------------------------------
'use client';

import useTask from '../../../components/useTask';
import BenchmarkEditor from './BenchmarkEditor';

export default function BenchmarksRegistroPage() {
  const { task, busy, start } = useTask();
  const onTaskDone = (then) => (t) => { if (then) then(t); };

  return (
    <div className="bm-page">
      {/* The upstream masthead: brand name over the dashboard title, then
          the one-line subtitle, so every dashboard opens the same way. */}
      <div className="page-brand-block">
        <div className="page-brand-name">Profuturo Analytics</div>
        <div className="page-dashboard-title">Benchmarks</div>
      </div>
      <p className="page-sub">Registry · definitions are append-only: every change is a new version
        with its effective date and its reason, and the levels are rebuilt from the first one.</p>
      <BenchmarkEditor busy={busy} task={task} start={start} onTaskDone={onTaskDone} />
    </div>
  );
}
