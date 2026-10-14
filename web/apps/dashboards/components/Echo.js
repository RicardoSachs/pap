// web/apps/dashboards/components/Echo.js
// ---------------------------------------------------------------------------
// The one-line result of an action, in the write views.
//
// Every form had its own echo and they all looked the same whatever had
// happened: "Cargado" and "La carga falló y no se guardó nada" rendered as
// identical bold gray text. Success and failure must be distinguishable at
// a glance - that is the whole job of this line.
//
// Accepts either a plain string (treated as success, for the callers that
// only ever say good news) or {ok, text}.
// ---------------------------------------------------------------------------
'use client';

export default function Echo({ echo, style }) {
  if (!echo) return null;
  const { ok, text } = typeof echo === 'string' ? { ok: true, text: echo } : echo;
  if (!text) return null;
  return (
    <p className="page-sub" style={{ marginTop: 10, ...style }}>
      <b className={ok ? 'pos' : 'neg'}>{ok ? '✓' : '✕'}</b>{' '}
      <b>{text}</b>
    </p>
  );
}
