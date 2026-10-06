"""Background queue. One company at a time so a laptop demo stays predictable."""

from __future__ import annotations

import threading

from app import db
from app.pipeline import process_company

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None


def ensure_worker() -> None:
    global _thread, _stop
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop = threading.Event()
        _thread = threading.Thread(target=_loop, args=(_stop,), name="ohio-desk-worker", daemon=True)
        _thread.start()


def stop_worker() -> None:
    global _thread
    with _lock:
        _stop.set()
        thread = _thread
        _thread = None
    if thread and thread.is_alive():
        thread.join(timeout=2)


def _loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            company_id = db.claim_next()
        except Exception:
            stop.wait(0.5)
            continue
        if company_id is None:
            stop.wait(0.3)
            continue
        process_company(company_id)
