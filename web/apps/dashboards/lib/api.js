// web/apps/dashboards/lib/api.js
// ---------------------------------------------------------------------------
// Tiny fetch helper. BASE is empty in production (relative /api, same origin as
// FastAPI) and the uvicorn URL in dev (via NEXT_PUBLIC_API_BASE).
// ---------------------------------------------------------------------------
// Exported: lib/spp.js builds download URLs on the same origin - the API base
// must have exactly one owner.
export const BASE = process.env.NEXT_PUBLIC_API_BASE || '';

export async function apiGet(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`API ${path} -> ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// What each status code means IN THIS APP, used only when the API sent no
// `detail` of its own - when it did, that one is more concrete than this.
const STATUS_HINTS = {
  400: 'Los datos enviados no son validos.',
  404: 'Esa operacion no existe en la API. Suele ser que la pagina quedo '
    + 'de una version mas nueva que la API: cierra y vuelve a abrir el tablero.',
  409: 'La operacion choca con el estado actual: o hay otra corriendo, o lo '
    + 'que intentas cambiar esta en uso.',
  410: 'Lo revisado ya no esta en memoria; vuelve a subir el archivo.',
  413: 'El archivo es demasiado grande.',
  503: 'Esta maquina no puede hacer eso (falta el permiso en el .env).',
};
const explainStatus = (status) => STATUS_HINTS[status]
  || `La API respondio ${status}. El detalle esta en la ventana de la API.`;

// Mutating counterpart of apiGet (JSON body or FormData), used by the write
// views. Returns {ok, status, data} instead of throwing so callers can show
// the backend's `detail` (an HTTPException's reason) verbatim.
//
// That contract has to hold for a DEAD API too, not just for an error
// response: every caller is an async onClick, so a rejected fetch used to
// surface as an unhandled rejection - the form simply went quiet and the
// operator could not tell whether the write had landed.
export async function apiSend(path, method, body, isForm = false) {
  const opts = { method };
  if (body !== undefined) {
    if (isForm) { opts.body = body; } else {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
  }
  try {
    const res = await fetch(`${BASE}${path}`, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // A validation error (422) arrives as a list of {loc, msg}; flatten it
      // so every caller can print data.detail as text.
      if (Array.isArray(data.detail)) {
        data.detail = data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
      }
      if (!data.detail) data.detail = explainStatus(res.status);
    }
    return { ok: res.ok, status: res.status, data };
  } catch {
    return {
      ok: false,
      status: 0,
      data: { detail: 'No se pudo hablar con la API (¿se cerró la ventana de la API?). No se guardó nada.' },
    };
  }
}

// Format a 0..1 fraction as a percentage string.
export function pct(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return '-';
  return `${(x * 100).toFixed(digits)}%`;
}

// Format a number with thousands separators.
export function num(x, digits = 0) {
  if (x === null || x === undefined || Number.isNaN(x)) return '-';
  return x.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
