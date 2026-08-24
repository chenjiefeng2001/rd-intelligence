import os
import unittest

from rdebug.adapter.locator import find_module_dir

CAPTURE_ENV = "RDEBUG_INTEGRATION_CAPTURE"


def _real_environment_ready():
    if not os.environ.get(CAPTURE_ENV):
        return False
    return find_module_dir() is not None


@unittest.skipUnless(
    _real_environment_ready(),
    f"set {CAPTURE_ENV} to a .rdc file and make the renderdoc python module "
    "importable (RDEBUG_RENDERDOC_PATH) to run integration tests",
)
class TestRealReplay(unittest.TestCase):
    CAPTURE = None
    SESSION_KWARGS = {}

    @classmethod
    def setUpClass(cls):
        from rdebug.adapter.core import CaptureSession

        cls._session = CaptureSession(os.environ[CAPTURE_ENV])
        cls._session.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._session.close()

    def test_capture_opens_and_reports(self):
        s = self._session
        rows = s.action_rows()
        self.assertGreater(len(rows), 0)
        self.assertTrue(s.driver)

    def test_draws_have_events(self):
        draws = self._session.draw_rows(limit=100)
        for d in draws:
            self.assertTrue(d["isDraw"])

    def test_pipeline_snapshot_at_last_event(self):
        s = self._session
        payload = s.pipeline(s.last_event_id())
        self.assertIn("eventId", payload)

    def test_trace_pixel_smoke(self):
        from rdebug.analysis.pixel_trace import trace_pixel

        s = self._session
        graph = trace_pixel(
            s,
            x=int(os.environ.get("RDEBUG_INTEGRATION_X", "320")),
            y=int(os.environ.get("RDEBUG_INTEGRATION_Y", "240")),
            max_draws=4,
        )
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)

    def test_debug_pixel_smoke(self):
        from rdebug.analysis.shader_trace import debug_pixel

        s = self._session
        trace = debug_pixel(
            s,
            x=int(os.environ.get("RDEBUG_INTEGRATION_X", "320")),
            y=int(os.environ.get("RDEBUG_INTEGRATION_Y", "240")),
            max_steps=2048,
        )
        self.assertTrue(trace["shader"]["debuggable"])
        self.assertGreater(trace["stepCount"], 0)
        self.assertFalse(trace["truncated"])
        for ev in trace["evidence"]:
            self.assertIn("id", ev)

    def test_trace_resource_smoke(self):
        from rdebug.analysis.resource_flow import trace_resource

        s = self._session
        pipe = s.pipeline(s.last_draw_event_id())
        outs = pipe.get("outputTargets") or []
        self.assertTrue(outs)
        target = outs[0]["resource"]
        flow = trace_resource(s, target)
        self.assertGreater(flow["summary"]["writerCount"], 0)
        for entry in flow["writers"] + flow["readers"]:
            ev = entry["evidence"][0]
            self.assertEqual(ev["resourceId"], target)
            self.assertIn("id", ev)


if __name__ == "__main__":
    unittest.main()
