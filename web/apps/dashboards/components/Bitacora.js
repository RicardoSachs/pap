
// web/apps/dashboards/components/Bitacora.js
// ---------------------------------------------------------------------------
// The running log of the shared background task (SBS extraction, historical
// load, Bloomberg download, benchmark recalculation).
//
// One component because the two copies had already diverged in the state that
// matters most: while a task was running, the carga view still read "Sin
// operaciones en esta sesión" until the first poll came back, and showed no
// sign of progress afterwards. A task that is working must SAY it is working.
// ---------------------------------------------------------------------------
'use client';

export default function Bitacora({ tarea, vacio = 'Sin operaciones en esta sesión.' }) {
  const lineas = tarea?.bitacora || [];
  return (
    <div className="spp-bitacora mono">
      {!tarea && <div className="dim">{vacio}</div>}
      {tarea && !lineas.length && tarea.activa && (
        <div className="dim">Iniciando {tarea.accion || 'la operación'}…</div>
      )}
      {lineas.map((l, i) => (
        <div key={i} className={String(l).startsWith('ERROR') ? 'neg' : ''}>{l}</div>
      ))}
      {tarea?.activa && <div className="dim">… en curso</div>}
      {tarea && !tarea.activa && (tarea.error
        ? <div className="neg">ERROR: {tarea.error}</div>
        : <div className="pos">Operación terminada.</div>)}
    </div>
  );
}
