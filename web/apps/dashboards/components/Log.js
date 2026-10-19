// web/apps/dashboards/components/Log.js
// ---------------------------------------------------------------------------
// The running log of the shared background task (SBS scrape, history load,
// benchmark materialization).
//
// One component because the two copies had already diverged in the state
// that matters most: while a task was running, the upload view still read
// "Sin operaciones en esta sesión" until the first poll came back, and
// showed no sign of progress afterwards. A task that is working must SAY it
// is working.
// ---------------------------------------------------------------------------
'use client';

import useShowAll from './useShowAll';

// The LAST lines are the ones that matter while something runs, so the cut
// leaves out the old ones, not the recent ones.
const CAP = 14;

export default function Log({ task, empty = 'Sin operaciones en esta sesión.' }) {
  const lines = task?.log || [];
  const recent = [...lines].reverse();
  const [visible, ShowAll] = useShowAll(recent, CAP);
  return (
    <>
      <div className="spp-log mono">
        {!task && <div className="dim">{empty}</div>}
        {task && !lines.length && task.active && (
          <div className="dim">Iniciando {task.action || 'la operación'}…</div>
        )}
        {[...visible].reverse().map((l, i) => (
          <div key={i} className={String(l).startsWith('ERROR') ? 'neg' : ''}>{l}</div>
        ))}
        {task?.active && <div className="dim">… en curso</div>}
        {task && !task.active && (task.error
          ? <div className="neg">ERROR: {task.error}</div>
          : <div className="pos">Operación terminada.</div>)}
      </div>
      <ShowAll label="líneas" />
    </>
  );
}
