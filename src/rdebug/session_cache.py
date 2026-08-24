"""Transport-level capture session caching, shared by MCP/IDE/CI frontends.

Lifecycle is bound to the serving process (one client connection), never a
global singleton: sessions are keyed by absolute capture path, LRU-evicted,
health-checked before reuse, and disposed+reopened on any sign of invalid
native state. Not thread-safe across connections (each transport should
serialise access per client)."""

import os
import time
from collections import OrderedDict
from contextlib import contextmanager

from .observability import record


def _quiet_close(session):
    if session is None:
        return
    try:
        session.close()
    except Exception:
        pass


class SessionManager:
    def __init__(self, factory_provider, max_sessions=4, health_probe=None):
        self._factory_provider = factory_provider
        self._max = max(1, int(max_sessions))
        self._probe = health_probe or (lambda s: s.root_actions())
        self._sessions = OrderedDict()
        self.recoveries = 0

    @contextmanager
    def use(self, capture):
        key = os.path.abspath(capture)
        session = self._sessions.get(key)
        recovered = False
        if session is not None:
            try:
                self._probe(session)
                self._sessions.move_to_end(key)
                record("session_reuse", capture=key)
            except Exception:
                self.dispose(key)
                session = None
                recovered = True
                record("session_probe_failed", capture=key)
        if session is None:
            t0 = time.perf_counter()
            session = self._factory_provider()(capture)
            if recovered:
                self.recoveries += 1
                record("session_recovery", capture=key)
            try:
                self._probe(session)
            except Exception as e:
                _quiet_close(session)
                record("session_open_failed", capture=key, error=str(e))
                raise
            self._sessions[key] = session
            self._evict(keep=key)
            record("session_open", capture=key,
                   latencyMs=round((time.perf_counter() - t0) * 1000.0, 2))
        yield session

    def _evict(self, keep):
        while len(self._sessions) > self._max:
            for key in self._sessions:
                if key != keep:
                    record("session_evict", capture=key)
                    self.dispose(key)
                    break

    def dispose(self, capture):
        key = os.path.abspath(capture)
        session = self._sessions.pop(key, None)
        _quiet_close(session)

    def dispose_all(self):
        for key in list(self._sessions):
            self.dispose(key)

    def stats(self):
        return {"count": len(self._sessions), "paths": list(self._sessions),
                "recoveries": self.recoveries}
