import json
import os
import tempfile
import unittest

from test_transport import FakeSession

from rdebug import errors, observability
from rdebug_mcp.server import SessionManager


class TestObservability(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("RDEBUG_TELEMETRY")
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.environ["RDEBUG_TELEMETRY"] = self.path

    def tearDown(self):
        if self._prev is not None:
            os.environ["RDEBUG_TELEMETRY"] = self._prev
        else:
            os.environ.pop("RDEBUG_TELEMETRY", None)

    def _lines(self):
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_disabled_by_default(self):
        os.environ.pop("RDEBUG_TELEMETRY", None)
        self.assertFalse(observability.record("x", a=1))
        self.assertEqual(os.path.getsize(self.path), 0)

    def test_record_and_timed(self):
        self.assertTrue(observability.record("session_open", capture="a.rdc",
                                             latencyMs=1.5))
        with observability.timed("query", transport="mcp", tool="trace_pixel"):
            pass
        lines = self._lines()
        self.assertEqual(lines[0]["event"], "session_open")
        self.assertEqual(lines[0]["capture"], "a.rdc")
        self.assertEqual(lines[1]["event"], "query")
        self.assertEqual(lines[1]["tool"], "trace_pixel")
        self.assertIn("latencyMs", lines[1])
        self.assertIsNone(lines[1]["error"])

    def test_record_never_raises(self):
        os.environ["RDEBUG_TELEMETRY"] = os.path.join(
            self.path, "nonexistent_dir", "x.jsonl"
        )
        self.assertFalse(observability.record("x"))


class TestSessionManagerTelemetry(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        self._prev = os.environ.get("RDEBUG_TELEMETRY")
        os.environ["RDEBUG_TELEMETRY"] = self.path

    def tearDown(self):
        if self._prev is not None:
            os.environ["RDEBUG_TELEMETRY"] = self._prev
        else:
            os.environ.pop("RDEBUG_TELEMETRY", None)

    def _events(self):
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line)["event"] for line in f if line.strip()]

    def test_open_reuse_evict_events(self):
        factory_calls = []

        def factory(c):
            factory_calls.append(c)
            return FakeSession()

        mgr = SessionManager(factory_provider=lambda: factory, max_sessions=1)
        with mgr.use("a.rdc"):
            pass
        with mgr.use("a.rdc"):
            pass
        with mgr.use("b.rdc"):
            pass
        events = self._events()
        self.assertIn("session_open", events)
        self.assertIn("session_reuse", events)
        self.assertIn("session_evict", events)
        self.assertNotIn("session_recovery", events)

    def test_recovery_event(self):
        broken = FakeSession()
        seen = []

        def probe(session):
            seen.append(session)
            if session is broken and seen.count(broken) >= 2:
                raise errors.RDebugError("invalid")

        def factory(c):
            factory.calls.append(c)
            return broken if len(factory.calls) == 1 else FakeSession()

        factory.calls = []

        mgr = SessionManager(factory_provider=lambda: factory, health_probe=probe)
        with mgr.use("a.rdc"):
            pass
        with mgr.use("a.rdc"):
            pass
        self.assertIn("session_recovery", self._events())


if __name__ == "__main__":
    unittest.main()
