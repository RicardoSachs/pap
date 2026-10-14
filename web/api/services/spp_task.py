# web/api/services/spp_task.py
# ---------------------------------------------------------------------------
# The ONE background task slot of the SPP tablero (SBS scrape, history
# load, benchmark materialization) and the in-memory store of reviewed
# uploads.
#
# SINGLE-PROCESS ASSUMPTION. Both live in this process's memory: the slot
# is a module-level dict behind a lock, the upload store a dict of the last
# three reviewed files keyed by token. Run the API with ONE worker (the
# tablero does: `uvicorn web.api.main:app --port 8000`); with several, a
# second worker would neither see the running task nor find the token the
# first one issued. Moving the token to the database is the alternative;
# the single process is the one chosen because the API runs on one desk
# machine, next to the Chrome it drives, and a second worker would also
# mean a second Chrome.
#
# One thread + one lock: a second launch is refused with the name of the
# operation already running. The frontend polls status() until `active`
# goes false. The worker thread is NOT a daemon: an interpreter shutting
# down mid-load waits for the row-by-row load to finish instead of killing
# it halfway through a transaction.
#
# with_log() pipes the pipeline's `logging` records into the task log, so
# pipeline code needs no log= parameter. A reviewed upload is kept under a
# token so confirming the load writes exactly the bytes that were
# reviewed, without a second upload; an expired token means re-uploading
# (HTTP 410 at the route).
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import threading
from collections import deque

logger = logging.getLogger(__name__)

_task = {"active": False, "action": None, "log": deque(maxlen=200),
         "result": None, "error": None}
_lock = threading.Lock()


def launch(action: str, func, **kwargs) -> None:
    """
    Starts `func(log=..., **kwargs)` in a thread. Raises RuntimeError,
    naming the running operation, when the slot is taken.
    """
    with _lock:
        if _task["active"]:
            raise RuntimeError(f"Ya hay una operacion en curso: {_task['action']}")
        _task.update(active=True, action=action, result=None, error=None)
        _task["log"].clear()

    def record(message) -> None:
        _task["log"].append(str(message))

    def run() -> None:
        try:
            record(f"Iniciando {action}...")
            _task["result"] = func(log=record, **kwargs)
            record("Listo.")
        except Exception as exc:
            _task["error"] = str(exc)
            record(f"ERROR: {exc}")
            logger.exception(f"background task failed: {action}")
        finally:
            _task["active"] = False

    threading.Thread(target=run, name=f"spp-task:{action}", daemon=False).start()


def status() -> dict:
    return {"active": _task["active"], "action": _task["action"],
            "log": list(_task["log"]),
            "result": _task["result"], "error": _task["error"]}


def with_log(func, **kwargs):
    """
    Wraps a pipeline callable so its `logging` output lands in the task
    log. The pipeline logs through logging (project convention); the task
    expects a log() callback - this bridges the two without touching
    pipeline signatures.
    """
    def run(log):
        class _Bridge(logging.Handler):
            def emit(self, record):
                log(record.getMessage())

        bridge = _Bridge()
        root = logging.getLogger("src")
        root.addHandler(bridge)
        try:
            return func(**kwargs)
        finally:
            root.removeHandler(bridge)
    return run


# ---- Upload store (tokens) -------------------------------------------------

_UPLOADS: dict[str, dict] = {}
_MAX_UPLOADS = 3
_counter = 0


def store_upload(data: bytes, name: str) -> str:
    """Keeps a reviewed file in memory and returns its token."""
    global _counter
    with _lock:
        _counter += 1
        token = f"u{_counter}"
        _UPLOADS[token] = {"data": data, "name": name}
        for old in list(_UPLOADS)[:-_MAX_UPLOADS]:
            _UPLOADS.pop(old, None)
    return token


def read_upload(token: str) -> dict | None:
    """The stored file ({'data', 'name'}) or None when the token expired."""
    return _UPLOADS.get(token)
