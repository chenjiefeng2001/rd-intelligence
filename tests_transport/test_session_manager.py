import json
import unittest

from test_transport import FakeSession

from rdebug import errors

# SessionManager is no longer re-exported from the MCP transport, which has
# used WorkerManager since M1.3. The module itself still exists and the IDE
# still uses it, so its behaviour stays covered here.
from rdebug.session_cache import SessionManager
from rdebug_mcp import server


class CountingFactory:
    def __init__(self, sessions=None):
        self.calls = []
        self._sessions = list(sessions or [])

    def __call__(self, capture):
        self.calls.append(capture)
        if self._sessions:
            return self._sessions.pop(0)
        return FakeSession()


class TestSessionManager(unittest.TestCase):
    def test_same_capture_reused(self):
        factory = CountingFactory()
        mgr = SessionManager(factory_provider=lambda: factory)
        with mgr.use("cap.rdc") as s1:
            pass
        with mgr.use("cap.rdc") as s2:
            pass
        self.assertEqual(len(factory.calls), 1)
        self.assertIs(s1, s2)

    def test_different_captures_isolated(self):
        factory = CountingFactory()
        mgr = SessionManager(factory_provider=lambda: factory)
        with mgr.use("a.rdc") as sa:
            with mgr.use("b.rdc") as sb:
                self.assertIsNot(sa, sb)
        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(mgr.stats()["count"], 2)

    def test_dispose_one_keeps_other_usable(self):
        factory = CountingFactory()
        mgr = SessionManager(factory_provider=lambda: factory)
        with mgr.use("a.rdc"):
            pass
        with mgr.use("b.rdc"):
            pass
        mgr.dispose("a.rdc")
        self.assertEqual(mgr.stats()["count"], 1)
        with mgr.use("b.rdc"):
            pass
        self.assertEqual(len(factory.calls), 2)

    def test_invalid_session_disposed_and_reopened(self):
        broken = FakeSession()
        probe_seen = []

        def bad_probe(session):
            probe_seen.append(session)
            if session is broken and probe_seen.count(broken) >= 2:
                raise errors.RDebugError("native state invalid")

        factory = CountingFactory([broken])
        mgr = SessionManager(factory_provider=lambda: factory,
                             health_probe=bad_probe)
        with mgr.use("cap.rdc") as s:
            self.assertIs(s, broken)
        with mgr.use("cap.rdc") as s:
            self.assertIsNot(s, broken)
        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(mgr.recoveries, 1)

    def test_open_failure_does_not_poison_cache(self):
        attempts = []

        class FlakyFactory:
            def __call__(self, capture):
                attempts.append(capture)
                if len(attempts) == 1:
                    raise errors.CaptureOpenError("transient failure")
                return FakeSession()

        mgr = SessionManager(factory_provider=lambda: FlakyFactory())
        with self.assertRaises(errors.CaptureOpenError):
            with mgr.use("cap.rdc"):
                pass
        self.assertEqual(mgr.stats()["count"], 0)
        with mgr.use("cap.rdc"):
            pass
        self.assertEqual(mgr.stats()["count"], 1)

    def test_lru_eviction(self):
        factory = CountingFactory()
        mgr = SessionManager(factory_provider=lambda: factory, max_sessions=2)
        for path in ("a.rdc", "b.rdc", "c.rdc"):
            with mgr.use(path):
                pass
        self.assertEqual(mgr.stats()["count"], 2)
        self.assertNotIn("a.rdc", [p[-5:] for p in mgr.stats()["paths"]])
        with mgr.use("b.rdc"):
            pass
        self.assertEqual(len(factory.calls), 3)


class TestTransportReuse(unittest.TestCase):
    """The reuse property, on the path that now serves MCP.

    MCP moved from an in-process SessionManager to a WorkerManager in
    M1.3, so "one session per capture" became "one worker process per
    capture". The property is the same and still the reason the manager
    exists; only the mechanism changed, so the assertions are restated
    against the worker registry rather than deleted.
    """

    def setUp(self):
        self._prev = server._WORKERS
        # One registry, reused by every call: the transport must not build a
        # manager per request.
        try:
            from worker_stub import RecordingWorkers
        except ImportError:  # pragma: no cover - runner-dependent
            from tests_transport.worker_stub import RecordingWorkers
        server._WORKERS = RecordingWorkers(FakeSession())
        self.workers = server._WORKERS

    def tearDown(self):
        server._WORKERS.dispose_all()
        server._WORKERS = self._prev

    def test_sequential_tools_share_one_worker(self):
        server.trace_pixel("cap.rdc", 1, 2)
        server.trace_resource("cap.rdc", "ResourceId::47")
        server.diff_pixel("cap.rdc", 1, 2, 3, 4)
        self.assertEqual(len(self.workers.spawned), 1,
                         "three calls on one capture must reuse one worker")
        self.assertEqual(len(self.workers.query_log), 3)

    def test_cold_warm_semantic_equivalence(self):
        # DESIGN_SPEC §2.9 MUST #2: results must not depend on worker
        # lifetime. Previously "cold vs warm" was first call vs later calls
        # on the same session; it is now first call vs later calls on the
        # same worker process.
        cold = json.loads(server.diff_pixel("cap.rdc", 1, 2, 3, 4))
        server.trace_pixel("cap.rdc", 5, 6)
        warm = json.loads(server.diff_pixel("cap.rdc", 1, 2, 3, 4))
        self.assertEqual(cold, warm)
        self.assertEqual(len(self.workers.spawned), 1)


if __name__ == "__main__":
    unittest.main()

