import unittest

from test_transport import FakeSession

from rdebug_ide import app


class TestIdeApi(unittest.TestCase):
    def setUp(self):
        app.configure("cap.rdc", session_factory=lambda c: FakeSession())

    def tearDown(self):
        if app._manager is not None:
            app._manager.dispose_all()
        app._manager = None

    def test_info_and_unknown_route(self):
        status, payload = app.route("/api/info", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["capture"].endswith("cap.rdc"))
        status, payload = app.route("/api/nope", {})
        self.assertEqual(status, 404)

    def test_trace_route(self):
        status, payload = app.route("/api/trace", {"x": ["1"], "y": ["2"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["summary"]["target"], "ResourceId::35")

    def test_diff_route_states(self):
        status, payload = app.route("/api/diff",
                                    {"a": ["1,2"], "b": ["3,4"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["comparison"], "same")
        layers = {ly["layer"]: ly["status"] for ly in payload["layers"]}
        self.assertEqual(layers["shader_input_values"], "unknown")

    def test_resource_route(self):
        status, payload = app.route("/api/resource",
                                    {"id": ["ResourceId::47"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["summary"]["writerCount"], 1)

    def test_operational_error_is_400_json(self):
        status, payload = app.route("/api/diff", {"a": ["bad"], "b": ["3,4"]})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_missing_query_parameter_is_400_json_not_a_dropped_connection(self):
        # api_trace() does query["x"][0] directly, so a request without "x"
        # raised KeyError, which escaped the `except RDebugError` handler and
        # made BaseHTTPRequestHandler drop the connection with no body.
        # DESIGN_SPEC §2.6 requires runtime errors to return JSON.
        status, payload = app.route("/api/trace", {"y": ["4"]})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        self.assertIn("invalid request parameters", payload["error"])

    def test_non_numeric_coordinate_is_400_json(self):
        status, payload = app.route("/api/trace",
                                    {"x": ["not-a-number"], "y": ["4"]})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_missing_id_is_400_json(self):
        status, payload = app.route("/api/resource", {})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_explain_prompt_is_grounded(self):
        status, payload = app.route("/api/explain", {"a": ["1,2"], "b": ["3,4"]})
        self.assertEqual(status, 200)
        prompt = payload["prompt"]
        self.assertIn("Use ONLY the facts below", prompt)
        self.assertIn("must be marked unknown", prompt)
        self.assertIn("comparison: same", prompt)
        self.assertTrue(payload["evidenceIds"])

    def test_ci_disabled_without_baseline(self):
        status, payload = app.route("/api/ci", {})
        self.assertEqual(status, 200)
        self.assertFalse(payload["enabled"])

    def test_session_reused_across_calls(self):
        app.configure("cap.rdc", session_factory=lambda c: FakeSession())
        calls = {"n": 0}

        real_factory = app._session_factory

        def counting(c):
            calls["n"] += 1
            return real_factory(c)

        app.configure("cap.rdc", session_factory=counting)
        app.route("/api/trace", {"x": ["1"], "y": ["2"]})
        app.route("/api/trace", {"x": ["1"], "y": ["2"]})
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
