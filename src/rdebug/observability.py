"""Opt-in JSONL telemetry for transports.

Enabled only when the RDEBUG_TELEMETRY environment variable points to a file.
Best-effort by design: recording must never break a query. Stable Core never
calls this; transports (MCP/IDE/CI) use it to answer real-workload questions
(what is slow, what holds resources, what fails) before any concurrency or
scheduling work is considered."""

import json
import os
import threading
import time

_LOCK = threading.Lock()


def _path():
    return os.environ.get("RDEBUG_TELEMETRY") or None


def record(event, **fields):
    path = _path()
    if not path:
        return False
    entry = {"ts": round(time.time(), 3), "event": event}
    entry.update(fields)
    try:
        with _LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        return True
    except Exception:
        return False


def timed(event, **fields):
    """Context manager: record event with latencyMs on exit."""

    class _Timer:
        def __enter__(self):
            self._t0 = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            latency = round((time.perf_counter() - self._t0) * 1000.0, 2)
            record(event, latencyMs=latency,
                   error=None if exc_type is None else str(exc_val), **fields)
            return False

    return _Timer()
