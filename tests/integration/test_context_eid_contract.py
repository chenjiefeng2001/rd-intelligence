"""Contract controls for context_eid (DESIGN_SPEC section 2.10, ruling A).

Written before the fix, per the approved sequence, so the controls could be
shown to fail against the unfixed code. The negative controls are what catch
the defect; the positive controls are what catch an over-strict fix.

Positive controls must pass before AND after the fix. Negative controls must
fail before the fix and pass after it. A post-fix failure in a positive
control therefore means the fix itself is wrong, not that the test is bad.
"""

import os
import unittest

from rdebug.adapter.locator import find_module_dir
from rdebug.errors import QueryError, RDebugError

CAPTURE_ENV = "RDEBUG_INTEGRATION_CAPTURE"


def _ready():
    return bool(os.environ.get(CAPTURE_ENV)) and find_module_dir() is not None


def _open_session():
    from rdebug.adapter.core import CaptureSession

    session = CaptureSession(os.environ[CAPTURE_ENV])
    session.__enter__()
    return session


def _ids_outside(s):
    """Ids that are not real events, including one inside the id range."""
    valid = sorted({r["eventId"] for r in s.action_rows()})
    outside = [v + 1000 for v in valid[-1:]]
    lo, hi = valid[0], valid[-1]
    for cand in range(lo, hi + 1):
        if cand not in valid:
            outside.append(cand)
            break
    return outside


@unittest.skipUnless(
    _ready(),
    f"set {CAPTURE_ENV} to a .rdc file and make the renderdoc python module "
    "importable (RDEBUG_RENDERDOC_PATH) to run integration tests",
)
class TestContextEidRealCapture(unittest.TestCase):
    """Controls 1, 3, 4 and the post-invalid recovery check, on a real capture."""

    @classmethod
    def setUpClass(cls):
        cls.session = _open_session()

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    def _valid_ids(self):
        return sorted({r["eventId"] for r in self.session.action_rows()})

    def test_positive_valid_draw_eid_is_accepted_and_matches_baseline(self):
        s = self.session
        draws = [r["eventId"] for r in s.action_rows() if r.get("isDraw")]
        self.assertTrue(draws, "capture has no draw events to use as a control")
        eid = draws[-1]

        first = s.pipeline(eid)
        second = s.pipeline(eid)

        self.assertEqual(first, second, "valid eid is not deterministic")
        self.assertEqual(s.current_event_id, eid)
        self.assertIsInstance(first, dict)

    def test_positive_non_draw_real_eid_is_accepted(self):
        """A real non-draw event is still legal; validity is not draw-only."""
        s = self.session
        nondraw = [
            r["eventId"] for r in s.action_rows() if not r.get("isDraw")
        ]
        if not nondraw:
            self.skipTest("capture has no non-draw events")
        eid = nondraw[-1]
        self.assertIsInstance(s.pipeline(eid), dict)
        self.assertEqual(s.current_event_id, eid)

    def test_negative_nonexistent_eid_raises_parameter_error(self):
        """The control that catches the defect: no silent wrong result."""
        s = self.session
        for bad in _ids_outside(s):
            with self.subTest(eid=bad):
                with self.assertRaises(QueryError) as ctx:
                    s.set_event(bad)
                self.assertEqual(
                    getattr(ctx.exception, "kind", None),
                    "bad_request",
                    "an illegal context_eid must be classified as a parameter "
                    "error, not a query or replay failure",
                )

    def test_negative_nonexistent_eid_yields_no_semantic_result(self):
        """A rejected eid must not travel on to produce a payload."""
        s = self.session
        bad = _ids_outside(s)[-1]
        with self.assertRaises(QueryError):
            s.pipeline(bad)
        self.assertNotEqual(
            s.current_event_id,
            bad,
            "a rejected eid must not be recorded as the current event",
        )

    def test_invalid_eid_is_not_a_worker_or_replay_failure(self):
        """Parameter error must not be dressed up as a runtime failure."""
        s = self.session
        bad = _ids_outside(s)[-1]
        with self.assertRaises(QueryError):
            s.set_event(bad)
        try:
            s.set_event(bad)
        except RDebugError as exc:
            self.assertNotIn("worker", type(exc).__name__.lower())
            self.assertNotIn("replay", type(exc).__name__.lower())

    def test_post_invalid_recovers_and_matches_baseline(self):
        """After illegal eids the runtime must still be usable and correct."""
        s = self.session
        draws = [r["eventId"] for r in s.action_rows() if r.get("isDraw")]
        eid = draws[-1]
        baseline = s.pipeline(eid)

        for bad in _ids_outside(s)[:3]:
            with self.assertRaises(QueryError):
                s.set_event(bad)

        self.assertEqual(
            s.pipeline(eid),
            baseline,
            "a valid query after an illegal eid diverged from the baseline",
        )
        self.assertEqual(s.current_event_id, eid)

    def test_no_explicit_eid_does_not_move_the_current_event(self):
        """The None path must keep its existing meaning: no event selection."""
        s = self.session
        eid = [r["eventId"] for r in s.action_rows() if r.get("isDraw")][-1]
        s.set_event(eid)
        s.pipeline()
        self.assertEqual(
            s.current_event_id,
            eid,
            "passing no eid must not silently change the context event",
        )


class _FakeAction:
    def __init__(self, event_id, flags, children=()):
        self.eventId = event_id
        self.flags = flags
        self.actionId = event_id
        self.customName = ""
        self.children = list(children)
        self.numIndices = 3
        self.numInstances = 1


class _FakeController:
    """Synthetic tree: a top-level Dispatch holding a NESTED non-draw child.

    Ids 2, 10 and 11 exist; 3..9 are inside the id range but do not exist.
    A draw-only predicate would reject 11. A range predicate would accept 5.
    """

    def __init__(self, rd):
        af = rd.ActionFlags
        nested = _FakeAction(11, int(af.Dispatch))
        dispatch = _FakeAction(10, int(af.Dispatch), children=[nested])
        draw = _FakeAction(2, int(af.Drawcall))
        self._tree = [draw, dispatch]
        self.set_calls = []

    def GetRootActions(self):
        return self._tree

    def SetFrameEvent(self, eid, force):
        self.set_calls.append((eid, force))

    def GetPipelineState(self):
        return {"synthetic": True}

    def Shutdown(self):
        pass


@unittest.skipUnless(
    _ready(),
    f"set {CAPTURE_ENV} to a .rdc file and make the renderdoc python module "
    "importable (RDEBUG_RENDERDOC_PATH) to run integration tests",
)
class TestContextEidNestedSyntheticTree(unittest.TestCase):
    """The false-positive control, on a synthetic action tree.

    No capture in this environment contains a nested action (all 19 checked
    files report zero nested rows), so this is synthetic evidence, not
    real-capture evidence.
    """

    def setUp(self):
        self.session = _open_session()
        self.fake = _FakeController(self.session._rd)
        self.session._ctrl = self.fake

    def tearDown(self):
        self.session._cap = None
        self.session.close()

    def test_nested_non_draw_eid_is_accepted(self):
        """MUST NOT be rejected: a nested non-draw event is a real event."""
        self.session.set_event(11)
        self.assertEqual(self.fake.set_calls[-1][0], 11)
        self.assertEqual(self.session.current_event_id, 11)

    def test_top_level_non_draw_eid_is_accepted(self):
        self.session.set_event(10)
        self.assertEqual(self.session.current_event_id, 10)

    def test_draw_eid_is_accepted(self):
        self.session.set_event(2)
        self.assertEqual(self.session.current_event_id, 2)

    def test_in_range_but_absent_eid_is_rejected(self):
        """5 sits between 2 and 11 but is not an event: membership, not range."""
        with self.assertRaises(QueryError) as ctx:
            self.session.set_event(5)
        self.assertEqual(getattr(ctx.exception, "kind", None), "bad_request")
        self.assertEqual(
            self.fake.set_calls,
            [],
            "SetFrameEvent must not be reached for a rejected eid",
        )

    def test_rejection_happens_before_set_frame_event(self):
        with self.assertRaises(QueryError):
            self.session.set_event(9999)
        self.assertEqual(self.fake.set_calls, [])


def _capture_dir():
    d = os.environ.get("RDEBUG_ISOLATION_CAPTURE_DIR")
    if d and os.path.isdir(d):
        return d
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "workload", "corpus",
    )


class _Telemetry:
    """Isolated telemetry sink so a row can assert on query_error."""

    def __init__(self):
        import tempfile

        fd, self.path = tempfile.mkstemp(suffix="_eid.jsonl")
        os.close(fd)
        self.prev = os.environ.get("RDEBUG_TELEMETRY")
        os.environ["RDEBUG_TELEMETRY"] = self.path

    def events(self, name):
        import json

        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh
                    if line.strip() and json.loads(line)["event"] == name]

    def close(self):
        import os as _os

        if self.prev is not None:
            os.environ["RDEBUG_TELEMETRY"] = self.prev
        else:
            os.environ.pop("RDEBUG_TELEMETRY", None)
        if _os.path.exists(self.path):
            _os.unlink(self.path)


@unittest.skipUnless(
    _ready() and os.path.isdir(_capture_dir()),
    "needs a renderdoc module and a corpus capture directory",
)
class TestContextEidTransportContract(unittest.TestCase):
    """An illegal eid must be a parameter error on every surface.

    Complements the M15 N3 row, which pins the other direction: a dead worker
    must never be labelled bad_request. Here the classification is required to
    be present, and must not be a replay/query failure.
    """

    def setUp(self):
        from rdebug_ide import app
        from rdebug_mcp import server

        server._WORKERS.dispose_all()
        app.dispose()
        self.addCleanup(app.dispose)
        self.addCleanup(server._WORKERS.dispose_all)
        self.tel = _Telemetry()
        self.addCleanup(self.tel.close)

    def _capture(self):
        for name in sorted(os.listdir(_capture_dir())):
            if name.endswith(".rdc"):
                return os.path.abspath(os.path.join(_capture_dir(), name))
        self.skipTest("no capture available")

    def _bad_eid(self, capture):
        s = _open_session_path(capture)
        try:
            return _ids_outside(s)[-1]
        finally:
            s.close()

    def test_illegal_eid_is_structured_bad_request_on_mcp(self):
        """The reachable transport path: MCP -> worker -> error body."""
        import json

        from rdebug_mcp import server

        capture = self._capture()
        bad = self._bad_eid(capture)

        payload = json.loads(server.trace_pixel(capture, 4, 4, eid=bad))
        self.assertIn("error", payload)
        self.assertIn(str(bad), payload["error"])
        self.assertEqual(payload.get("kind"), "bad_request")
        for banned in ("nodes", "edges", "resourceFlows", "summary"):
            self.assertNotIn(
                banned, payload,
                f"a rejected eid must not emit a semantic {banned}",
            )

        errors = [e for e in self.tel.events("query_error")
                  if e["transport"] == "mcp"]
        self.assertTrue(errors, "query_error must be observable")
        self.assertTrue(any(e.get("kind") == "bad_request" for e in errors),
                        "MCP must classify an illegal eid as bad_request")

    def test_legal_eid_after_illegal_still_works_over_transports(self):
        import json

        from rdebug_mcp import server

        capture = self._capture()
        bad = self._bad_eid(capture)
        s = _open_session_path(capture)
        try:
            good = [r["eventId"] for r in s.action_rows() if r.get("isDraw")][-1]
        finally:
            s.close()

        json.loads(server.trace_pixel(capture, 4, 4, eid=bad))
        payload = json.loads(server.trace_pixel(capture, 4, 4, eid=good))
        self.assertNotIn("error", payload)
        self.assertTrue(payload.get("nodes"), "a valid eid must yield a graph")
        self.assertIn("summary", payload)

    def test_ide_route_classifies_a_kind_carrying_query_error(self):
        """The IDE's classification, driven the way M15 N3 drives a worker death.

        No IDE endpoint accepts an eid today, so the illegal-eid case cannot
        arise there yet; what must hold is that the classification is in place
        for whenever one is added.
        """
        from rdebug_ide import app

        def boom(*_a, **_kw):
            raise QueryError("context event 9999 is not an event in this capture",
                             kind="bad_request")

        app.configure(self._capture())
        original = app._run
        app._run = boom
        try:
            status, body = app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        finally:
            app._run = original

        self.assertEqual(status, 400)
        self.assertIn("9999", body["error"])
        self.assertEqual(body.get("kind"), "bad_request")
        errors = [e for e in self.tel.events("query_error")
                  if e["transport"] == "ide"]
        self.assertTrue(errors)
        self.assertTrue(any(e.get("kind") == "bad_request" for e in errors),
                        "IDE must classify it as bad_request")

    def test_no_ide_endpoint_exposes_eid_today(self):
        """Pins the current fact, so adding eid forces a matching test."""
        from rdebug_ide import app

        handlers = [getattr(app, n) for n in dir(app)
                    if n.startswith("api_") and callable(getattr(app, n))]
        for fn in handlers:
            with self.subTest(fn=fn.__name__):
                self.assertNotIn(
                    "eid",
                    fn.__code__.co_varnames[:fn.__code__.co_argcount],
                    "an IDE endpoint now accepts eid; it must also classify an "
                    "illegal one as bad_request and be covered by a test",
                )


def _open_session_path(path):
    from rdebug.adapter.core import CaptureSession

    session = CaptureSession(path)
    session.__enter__()
    return session
