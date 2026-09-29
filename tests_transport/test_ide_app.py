import json
import os
import unittest

try:  # unittest discover puts tests_transport/ on sys.path; pytest does not
    from test_transport import FakeSession
    from worker_stub import RecordingWorkers
except ImportError:  # pragma: no cover - runner-dependent
    from tests_transport.test_transport import FakeSession
    from tests_transport.worker_stub import RecordingWorkers

from rdebug_ide import app


class TestIdeOwnership(unittest.TestCase):
    """M1.4 acceptance invariants I1-I3 at the unit level.

    The real-RenderDoc versions, including the ghost check across
    configure(A); configure(B); dispose(B), live in
    tests/integration/test_ide_ownership.py. These use the worker double so
    the lifecycle logic is covered without a capture, and so a failure
    points at the ownership code rather than at a worker spawn.
    """

    def tearDown(self):
        app.dispose()

    def test_configure_establishes_exactly_one_owner(self):
        w = RecordingWorkers(FakeSession())
        app.configure("A.rdc", workers=w)
        self.assertEqual(app._STATE["capture"], os.path.abspath("A.rdc"))
        self.assertTrue(app._STATE["ready"])
        self.assertEqual(w.captures(), [os.path.abspath("A.rdc")])

    def test_reconfigure_releases_the_previous_owner_before_claiming(self):
        # I1: configure(A) -> owner A; configure(B) -> A disposed, owner B.
        # Never sessions=[A,B] with the surface reporting B.
        first = RecordingWorkers(FakeSession())
        app.configure("A.rdc", workers=first)
        first._note_spawn(os.path.abspath("A.rdc"))
        second = RecordingWorkers(FakeSession())
        app.configure("B.rdc", workers=second)
        self.assertEqual(first.disposed, 1,
                         "the previous owner must be released explicitly")
        self.assertEqual(first.captures(), [])
        self.assertEqual(app._STATE["capture"], os.path.abspath("B.rdc"))

    def test_dispose_is_symmetric_with_configure(self):
        # I2: every established capture has an explicit termination path.
        w = RecordingWorkers(FakeSession())
        app.configure("A.rdc", workers=w)
        w._note_spawn(os.path.abspath("A.rdc"))
        app.dispose()
        self.assertEqual(w.disposed, 1)
        self.assertEqual(w.captures(), [])
        self.assertFalse(app._STATE["ready"])
        self.assertIsNone(app._STATE["capture"])

    def test_dispose_is_idempotent(self):
        w = RecordingWorkers(FakeSession())
        app.configure("A.rdc", workers=w)
        app.dispose()
        app.dispose()
        self.assertEqual(w.disposed, 1,
                         "the second dispose has nothing to release")

    def test_failed_configure_leaves_no_owner_and_no_registry_entry(self):
        # I2: a failed configure must not leave a half-initialised object.
        class _Failing(RecordingWorkers):
            def ping(self, capture, timeout=60):
                raise RuntimeError("simulated spawn failure")

        w = _Failing(FakeSession())
        with self.assertRaises(RuntimeError):
            app.configure("bad.rdc", workers=w)
        self.assertEqual(w.disposed, 1, "the manager it made must be released")
        self.assertIsNone(app._STATE["capture"])
        self.assertFalse(app._STATE["ready"])
        self.assertIsNone(app._workers)

    def test_queries_refuse_to_run_unconfigured(self):
        # A half-configured IDE must fail loudly, not query a stale capture.
        app.dispose()
        status, payload = app.route("/api/trace", {"x": ["1"], "y": ["2"]})
        self.assertEqual(status, 400)
        self.assertIn("not configured", payload["error"])

    def test_stats_reports_the_owner_and_recycles(self):
        w = RecordingWorkers(FakeSession())
        app.configure("A.rdc", workers=w)
        # The owner exists from configure(), not from the first query: that
        # is what makes a failed configure detectable at startup.
        payload = json.loads(json.dumps(app.api_stats({})))
        self.assertEqual(payload["sessions"]["count"], 1)
        self.assertEqual(payload["sessions"]["paths"], ["A.rdc"])
        self.assertEqual(payload["sessions"]["recycles"], 0)
        self.assertEqual(payload["sessions"]["unkillable"], [])
        app.route("/api/trace", {"x": ["1"], "y": ["2"]})
        payload = json.loads(json.dumps(app.api_stats({})))
        self.assertEqual(payload["sessions"]["count"], 1)
        # One owner, not one per request.
        self.assertEqual(payload["sessions"]["paths"], ["A.rdc"])


class TestIdeApi(unittest.TestCase):
    def setUp(self):
        # configure() takes a worker registry, not a session factory: it now
        # establishes ownership eagerly and dispose() is its counterpart.
        self.workers = RecordingWorkers(FakeSession())
        app.configure("cap.rdc", workers=self.workers)

    def tearDown(self):
        app.dispose()

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



if __name__ == "__main__":
    unittest.main()


