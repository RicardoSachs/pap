// web/apps/dashboards/app/benchmarks/registro/page.js
// ---------------------------------------------------------------------------
// Benchmarks · Registro: declaring a benchmark, appending versions of its
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
      <h1 className="page-title">Benchmarks</h1>
      <p className="page-sub">Registro · las definiciones son append-only: cada cambio es una versión
        nueva con su fecha de vigencia y su motivo, y los niveles se recalculan desde la primera.</p>
      <BenchmarkEditor busy={busy} task={task} start={start} onTaskDone={onTaskDone} />
    </div>
  );
}
