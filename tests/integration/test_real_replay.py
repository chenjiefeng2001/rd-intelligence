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
        flows = graph.get("resourceFlows", {})
        self.assertTrue(flows, "expected at least one sampled texture to expand")
        for rid, flow in flows.items():
            for entry in flow["writers"] + flow["readers"]:
                ev = entry["evidence"][0]
                self.assertEqual(ev["resourceId"], rid)
                self.assertIn("id", ev)
        for e in graph["edges"]:
            if e["label"] == "written_by":
                self.assertTrue(e["evidence"][0]["resourceId"].startswith("ResourceId"))
        for rid in flows:
            self.assertIn(f"resource:{rid}", [n["id"] for n in graph["nodes"]])

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

    def test_clear_semantic_invariants(self):
        from rdebug.analysis.pixel_trace import trace_pixel

        s = self._session
        graph = trace_pixel(s, x=10, y=10, max_draws=4)
        clears = [n for n in graph["nodes"]
                  if n["kind"] == "draw" and n["attrs"].get("clear")]
        self.assertTrue(clears, "expected at least one clear event on the pixel")
        clear_ids = {c["id"] for c in clears}
        for e in graph["edges"]:
            if e["from"] in clear_ids:
                self.assertNotEqual(e["label"], "bound_ps")
                self.assertNotEqual(e["label"], "reads")
        for c in clears:
            self.assertFalse(c["attrs"]["fragmentCandidate"])
            self.assertTrue(c["attrs"]["passed"] >= 0)
        self.assertGreater(graph["summary"]["modificationCount"], 0)

    def test_diff_pixel_smoke(self):
        from rdebug.analysis.pixel_diff import diff_pixel

        s = self._session
        same = diff_pixel(s, (10, 10), (20, 10))
        self.assertEqual(same.comparison, "same")
        self.assertTrue(same.equal)

        diff = diff_pixel(s, (320, 240), (10, 10))
        self.assertEqual(diff.comparison, "different")
        first = diff.first_divergence
        self.assertIsNotNone(first)
        self.assertIn(first["layer"],
                      ("fragment", "pixel_value", "input_bindings"))
        self.assertTrue(first["good"]["evidence"] or first["bad"]["evidence"])
        parsed = type(diff).parse(diff.to_dict())
        self.assertEqual(parsed.comparison, diff.comparison)

    def test_diff_pixel_shader_values_modes(self):
        from rdebug.analysis.pixel_diff import diff_pixel

        s = self._session
        structural = diff_pixel(s, (320, 240), (330, 240))
        structural_entry = next(
            ly for ly in structural.payload["layers"]
            if ly["layer"] == "shader_input_values"
        )
        self.assertEqual(structural_entry["status"], "unknown")

        deep = diff_pixel(s, (320, 240), (330, 240), include_shader_values=True)
        deep_entry = next(
            ly for ly in deep.payload["layers"]
            if ly["layer"] == "shader_input_values"
        )
        self.assertIn(deep_entry["status"], ("same", "different"))
        if deep_entry["status"] == "different":
            self.assertEqual(deep.first_divergence["layer"], "shader_input_values")


if __name__ == "__main__":
    unittest.main()
