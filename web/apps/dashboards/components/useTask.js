// web/apps/dashboards/components/useTask.js
// ---------------------------------------------------------------------------
// The one polling loop over /api/tasks/current, the background task slot
// the dashboards share (SBS scrape, history load, benchmark
// materialization follow the same contract). It used to be written per
// page and had already diverged in interval and error handling.
//
//   start(action, onDone)  kick off UI state and start polling
//   follow(onDone)         poll a task another call already launched
//   busy                   derived from task.active
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useRef, useState } from 'react';
import { apiGet } from '../lib/api';

const INTERVAL_MS = 1000;
const MAX_FAILURES = 5;

export default function useTask() {
  const [task, setTask] = useState(null);
  const pollRef = useRef(null);

  // Adopt a task that is ALREADY running when this view mounts. The task
  // slot is one per API process, shared by every tab: without this, moving
  // to another tab (or reloading) while a scrape runs left the new view
  // believing nothing was happening - its write buttons enabled, its log
  // empty - until the operator hit a 409 they could not explain.
  useEffect(() => {
    apiGet('/api/tasks/current')
      .then((t) => { if (t?.active) { setTask(t); follow(); } })
      .catch(() => {});
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const follow = (onDone) => {
    clearInterval(pollRef.current);
    // A single failed poll must NOT read as success: the task may still be
    // running server-side. Tolerate a few consecutive blips; only after
    // giving up mark the state as lost - with an error, never as a clean
    // finish.
    let failures = 0;
    pollRef.current = setInterval(async () => {
      try {
        const t = await apiGet('/api/tasks/current');
        failures = 0;
        setTask(t);
        if (!t.active) {
          clearInterval(pollRef.current);
          if (onDone) onDone(t);
        }
      } catch {
        failures += 1;
        if (failures >= MAX_FAILURES) {
          clearInterval(pollRef.current);
          setTask((t) => ({
            ...(t || {}),
            active: false,
            error: 'Lost track of the task (no connection with the API); it may still be running on the server. Reload the page to reconnect.',
          }));
        }
      }
    }, INTERVAL_MS);
  };

  const start = (action, onDone) => {
    setTask({ active: true, action, log: [] });
    follow(onDone);
  };

  return { task, busy: !!task?.active, start, follow };
}
