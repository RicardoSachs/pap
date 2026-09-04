
// web/apps/dashboards/components/useSppTarea.js
// ---------------------------------------------------------------------------
// The one polling loop over /api/spp/tarea (SBS extraction, historical load,
// Bloomberg download follow the same background-task contract). It used to be
// written per page and had already diverged in interval and error handling.
//
//   iniciar(accion, alTerminar)  kick off UI state and start polling
//   seguir(alTerminar)           poll a task another call already launched
//   ocupado                      derived from tarea.activa
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';
import { apiGet } from '../lib/api';

const INTERVALO_MS = 1000;

export default function useSppTarea() {
  const [tarea, setTarea] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => () => clearInterval(pollRef.current), []);

  const seguir = (alTerminar) => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const t = await apiGet('/api/spp/tarea');
        setTarea(t);
        if (!t.activa) {
          clearInterval(pollRef.current);
          if (alTerminar) alTerminar(t);
        }
      } catch {
        clearInterval(pollRef.current);
        setTarea((t) => (t ? { ...t, activa: false } : t));
      }
    }, INTERVALO_MS);
  };

  const iniciar = (accion, alTerminar) => {
    setTarea({ activa: true, accion, bitacora: [] });
    seguir(alTerminar);
  };

  return { tarea, ocupado: !!tarea?.activa, iniciar, seguir };
}
