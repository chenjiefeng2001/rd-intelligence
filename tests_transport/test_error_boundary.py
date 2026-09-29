"""M1.0 / D3: a worker failure must not vanish at a boundary.

WorkerError used to derive from RuntimeError while every transport
discriminated on RDebugError. The result was two distinct ways for a
worker failure to disappear:

  1. The IDE handler never matched, so the exception escaped route(),
     BaseHTTPRequestHandler dropped the connection with no body, and the
     client could not tell a crash from a rejected request. This is the
     same failure shape as F-19, which was fixed in the previous round and
     would have been reintroduced by the migration.
  2. workers.py:214-216 converts an RDebugError raised inside the worker
     into a JSON *payload* with ok:true. MCP's `except RDebugError`
     therefore never ran, so the `query_error` telemetry event stopped
     firing -- with no signal that it had.

D3's ruling is that the fix is a minimal, local inheritance change. That
is only acceptable if the whole chain still holds afterwards, so this file
pins the chain rather than the inheritance:

    worker failure -> WorkerError -> RDebugError-compatible
                   -> transport handler -> response body -> query_error

Both transports are exercised, and a negative control guards against
"fixing" the break by over-broadening the handlers.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from rdebug.errors import QueryError, RDebugError
from rdebug.worker_manager import WorkerError

# The transports only write telemetry when the env var is set; without it
# record() is a no-op and the chain would appear to work for the wrong
# reason.
os.environ.setdefault("RDEBUG_TELEMETRY",
                      os.path.join(tempfile.gettempdir(),
                                   "rdebug_m0_d3_telemetry.jsonl"))


def _read_telemetry():
    path = os.environ["RDEBUG_TELEMETRY"]
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _truncate_telemetry():
    path = os.environ["RDEBUG_TELEMETRY"]
    if os.path.exists(path):
        os.unlink(path)


class TestD3Inheritance(unittest.TestCase):
    def test_worker_error_is_an_rdebug_error(self):
        self.assertTrue(issubclass(WorkerError, RDebugError))

    def test_worker_error_is_not_a_domain_error(self):
        # WorkerError means "the process serving the capture is gone", not
        # "the capture said no". Collapsing the two would let a caller that
        # retries a QueryError also retry a dead worker without its bounded
        # recovery contract.
        self.assertFalse(issubclass(WorkerError, QueryError))

    def test_transient_flag_survives_the_base_class_change(self):
        self.assertFalse(WorkerError("x").transient)
        self.assertTrue(WorkerError("x", transient=True).transient)

    def test_message_is_preserved(self):
        self.assertEqual(str(WorkerError("worker dead (rc=1)")), "worker dead (rc=1)")


class TestMcpChain(unittest.TestCase):
    """worker failure -> JSON error payload -> query_error observable."""

    def setUp(self):
        _truncate_telemetry()
        from rdebug_mcp import server
        self.server = server

    def test_worker_error_becomes_a_json_error_payload(self):
        def boom(*a, **kw):
            raise WorkerError("worker exited unexpectedly (rc=1) for x.rdc")

        wrapped = self.server._safe(boom)
        out = wrapped()
        payload = json.loads(out)
        self.assertIn("error", payload)
        self.assertIn("worker exited unexpectedly", payload["error"])
        self.assertEqual(payload["tool"], "boom")

    def test_worker_error_fires_query_error_telemetry(self):
        def boom(*a, **kw):
            raise WorkerError("worker pipe broken (dead)")

        self.server._safe(boom)()
        events = [e for e in _read_telemetry() if e["event"] == "query_error"]
        self.assertEqual(len(events), 1, _read_telemetry())
        self.assertEqual(events[0]["transport"], "mcp")
        self.assertIn("worker pipe broken", events[0]["error"])

    def test_query_error_is_also_recorded_on_the_timed_query(self):
        # _safe wraps the call in timed(...), so a failure must be visible as
        # a query event carrying error= as well, not only query_error.
        def boom(*a, **kw):
            raise WorkerError("worker dead")

        self.server._safe(boom)()
        queries = [e for e in _read_telemetry() if e["event"] == "query"]
        self.assertTrue(queries)
        self.assertTrue(any("worker dead" in str(e.get("error"))
                            for e in queries), queries)

    def test_transient_worker_error_is_still_an_error_not_a_success(self):
        # Recovery is WorkerManager's job, at a lower layer. The transport
        # must still report failure to the client.
        def boom(*a, **kw):
            raise WorkerError("worker dead", transient=True)

        payload = json.loads(self.server._safe(boom)())
        self.assertIn("error", payload)


class _StubSession:
    """Minimal object satisfying SessionManager's default health probe.

    These tests never need a real replay; the point is to reach the
    transport's error handler, not to produce a semantic result.
    """

    def root_actions(self):
        return []

    def close(self):
        pass


def _configure_ide(app):
    app.configure(os.path.join(tempfile.gettempdir(), "nonexistent.rdc"),
                  session_factory=lambda capture: _StubSession())


def _raiser(exc):
    """A zero-arg callable that raises `exc`.

    Patched into app._ROUTES because that table binds the handlers at import
    time, so patching the module attribute has no effect on dispatch.
    """
    def _call(_query):
        raise exc
    return _call


class TestIdeChain(unittest.TestCase):
    """worker failure -> HTTP status + body, never a dropped connection."""

    def setUp(self):
        _truncate_telemetry()
        from rdebug_ide import app
        self.app = app
        # provider() calls session_factory(capture); a 0-arity lambda would
        # raise TypeError inside route() and be reported as a bad request,
        # masking what these tests are actually checking.
        _configure_ide(app)

    def tearDown(self):
        if self.app._manager is not None:
            self.app._manager.dispose_all()
            self.app._manager = None

    def test_worker_error_returns_400_with_a_body(self):
        with mock.patch.dict(
                self.app._ROUTES,
                {"/api/resource": _raiser(WorkerError("worker dead"))}):
            status, payload = self.app.route("/api/resource",
                                             {"id": ["ResourceId::1"]})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        self.assertIn("worker dead", payload["error"])

    def test_worker_error_fires_query_error_telemetry(self):
        with mock.patch.dict(
                self.app._ROUTES,
                {"/api/resource": _raiser(WorkerError("worker pipe broken"))}):
            self.app.route("/api/resource", {"id": ["ResourceId::1"]})
        events = [e for e in _read_telemetry() if e["event"] == "query_error"]
        self.assertEqual(len(events), 1, _read_telemetry())
        self.assertEqual(events[0]["transport"], "ide")

    def test_worker_error_is_not_labelled_a_bad_request(self):
        # A dead worker is a runtime failure, not a malformed request. The
        # two must stay distinguishable so the telemetry for metric class 4
        # (REAL_WORLD_VALIDATION.md:26-27) does not get polluted.
        with mock.patch.dict(
                self.app._ROUTES,
                {"/api/resource": _raiser(WorkerError("worker dead"))}):
            _status, payload = self.app.route("/api/resource",
                                              {"id": ["ResourceId::1"]})
        self.assertNotIn("invalid request parameters", payload["error"])


class _UnrelatedFailure(Exception):
    """Neither an RDebugError nor one of the parse-error types."""


class TestNegativeControls(unittest.TestCase):
    """Guard against fixing D3 by over-broadening the handlers.

    If both transports were changed to `except Exception`, every test above
    would still pass. These assert that unrelated failures are NOT silently
    converted into a tidy 400/error payload: a bug that escapes as a
    traceback is visible, one that becomes a 400 is not.

    Note the IDE legitimately maps (KeyError, IndexError, ValueError,
    TypeError) to 400 -- that is the F-19 fix, where a malformed request
    used to drop the connection with no body. So the control here must use
    a type outside that tuple.
    """

    def setUp(self):
        _truncate_telemetry()

    def test_mcp_still_propagates_an_unrelated_failure(self):
        from rdebug_mcp import server

        def boom(*a, **kw):
            raise _UnrelatedFailure("not a worker failure and not an RDebugError")

        with self.assertRaises(_UnrelatedFailure):
            server._safe(boom)()

    def test_ide_still_propagates_an_unrelated_failure(self):
        from rdebug_ide import app
        _configure_ide(app)
        try:
            with mock.patch.dict(
                    app._ROUTES,
                    {"/api/resource": _raiser(_UnrelatedFailure("unrelated"))}):
                with self.assertRaises(_UnrelatedFailure):
                    app.route("/api/resource", {"id": ["ResourceId::1"]})
        finally:
            if app._manager is not None:
                app._manager.dispose_all()
                app._manager = None

    def test_ide_keeps_its_parse_error_classification(self):
        # A local KeyError from query parsing keeps its bad-request branch.
        # Its worker-side counterpart arrives as WorkerError and is covered
        # by TestIdeChain instead -- the two must stay distinguishable.
        from rdebug_ide import app
        _configure_ide(app)
        try:
            status, payload = app.route("/api/trace", {"y": ["4"]})
            self.assertEqual(status, 400)
            self.assertIn("invalid request parameters", payload["error"])
        finally:
            if app._manager is not None:
                app._manager.dispose_all()
                app._manager = None

    def test_worker_error_does_not_fire_the_bad_request_telemetry_kind(self):
        from rdebug_ide import app
        _configure_ide(app)
        try:
            with mock.patch.dict(app._ROUTES,
                                 {"/api/resource": _raiser(
                                     WorkerError("worker dead"))}):
                app.route("/api/resource", {"id": ["ResourceId::1"]})
            events = [e for e in _read_telemetry() if e["event"] == "query_error"]
            self.assertTrue(events)
            self.assertNotIn("kind", events[0],
                             "a dead worker is a runtime failure, not a "
                             "malformed request; metric class 4 would be "
                             "polluted if it were labelled bad_request")
        finally:
            if app._manager is not None:
                app._manager.dispose_all()
                app._manager = None


if __name__ == "__main__":
    unittest.main()



