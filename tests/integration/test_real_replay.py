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
            x=int(os.environ.get("RDEBUG_INTEGRATION_X", "8")),
            y=int(os.environ.get("RDEBUG_INTEGRATION_Y", "8")),
            max_draws=4,
        )
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)


if __name__ == "__main__":
    unittest.main()
