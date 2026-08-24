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


class TestResultShape(unittest.TestCase):
    def test_summarize_diff_payload(self):
        payload = {
            "comparison": "different",
            "firstDivergence": {"layer": "fragment", "good": {}, "bad": {}},
            "layers": [
                {"layer": "pixel_value", "status": "different"},
                {"layer": "shader_input_values", "status": "unknown"},
            ],
            "evidence": [{"id": "a" * 12, "operation": "diff_pixel"}],
        }
        s = observability.summarize_result(payload)
        self.assertEqual(s["comparison"], "different")
        self.assertEqual(s["firstDivergence"], "fragment")
        self.assertEqual(s["unknownLayers"], ["shader_input_values"])
        self.assertEqual(s["evidenceCount"], 1)

    def test_non_dict_returns_empty(self):
        self.assertEqual(observability.summarize_result("x"), {})

    def test_mcp_wrapper_records_result_shape(self):
        fd, self.path2 = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        prev = os.environ.get("RDEBUG_TELEMETRY")
        os.environ["RDEBUG_TELEMETRY"] = self.path2
        try:
            from rdebug_mcp import server

            prev_factory = server._session_factory
            server._session_factory = lambda c: FakeSession()
            server._MANAGER.dispose_all()
            try:
                server.diff_pixel("cap.rdc", 1, 2, 3, 4)
            finally:
                server._session_factory = prev_factory
                server._MANAGER.dispose_all()
            with open(self.path2, encoding="utf-8") as f:
                events = [json.loads(line) for line in f if line.strip()]
            shapes = [e for e in events if e["event"] == "result_shape"]
            self.assertTrue(shapes)
            self.assertEqual(shapes[0]["comparison"], "same")
            self.assertIn("shader_input_values", shapes[0]["unknownLayers"])
        finally:
            if prev is not None:
                os.environ["RDEBUG_TELEMETRY"] = prev
            else:
                os.environ.pop("RDEBUG_TELEMETRY", None)


if __name__ == "__main__":
    unittest.main()
