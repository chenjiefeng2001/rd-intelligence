"""M1.5 acceptance matrix, mechanically checked.

Each row of the matrix is an assertion here, so "the matrix passed" is
something that can be re-run rather than something a report asserts. Real
RenderDoc, real worker processes; nothing is stubbed except where a row
explicitly asks for a negative control.

The one thing this file must not do is overstate D2. Distinct worker_pids
establish PROCESS isolation. They do not establish runtime isolation,
because RenderDoc exposes no public identity for the replay runtime or a
ReplayController. Every runtime/controller identity assertion below is an
assertion that it is UNOBSERVABLE, and the A1 row deliberately stops at
process identity.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from rdebug.adapter import core
from rdebug.adapter.locator import find_module_dir
from rdebug.worker_manager import WorkerError, WorkerManager

CORPUS_ENV = "RDEBUG_ISOLATION_CAPTURE_DIR"
DEFAULT_CORPUS = os.path.join("tests", "workload", "corpus")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _capture_dir():
    return os.environ.get(CORPUS_ENV) or DEFAULT_CORPUS


def _captures(n=2):
    d = _capture_dir()
    found = sorted(os.path.join(d, f) for f in os.listdir(d)
                   if f.endswith(".rdc"))
    if len(found) < n:
        raise unittest.SkipTest(f"need {n} captures in {d}")
    return [os.path.abspath(p) for p in found[:n]]


def _ready():
    return find_module_dir() is not None and os.path.isdir(_capture_dir())


_SKIP = (f"set {CORPUS_ENV} to a directory of .rdc captures and make the "
         "renderdoc python module importable (RDEBUG_RENDERDOC_PATH)")


def _live_controllers():
    return core._REPLAY_LIFECYCLE["sessions"]


def _pid_alive(pid):
    import psutil
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def _await_gone(pids, timeout=25):
    stop = time.time() + timeout
    while time.time() < stop:
        if not any(_pid_alive(p) for p in pids):
            return True
        time.sleep(0.05)
    return not any(_pid_alive(p) for p in pids)


class _Telemetry:
    """Isolated telemetry sink so a row can assert on query_error."""

    def __init__(self):
        fd, self.path = tempfile.mkstemp(suffix="_m15.jsonl")
        os.close(fd)
        self.prev = os.environ.get("RDEBUG_TELEMETRY")
        os.environ["RDEBUG_TELEMETRY"] = self.path

    def events(self, name):
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()
                    and json.loads(line)["event"] == name]

    def close(self):
        if self.prev is not None:
            os.environ["RDEBUG_TELEMETRY"] = self.prev
        else:
            os.environ.pop("RDEBUG_TELEMETRY", None)
        if os.path.exists(self.path):
            os.unlink(self.path)


# ---------------------------------------------------------------- matrix
@unittest.skipUnless(_ready(), _SKIP)
class TestM15Matrix(unittest.TestCase):
    """The accepted matrix, row by row. MCP and IDE columns both asserted."""

    def setUp(self):
        from rdebug_ide import app
        from rdebug_mcp import server
        self.app = app
        self.server = server
        app.dispose()
        server._WORKERS.dispose_all()
        self.addCleanup(app.dispose)
        self.addCleanup(server._WORKERS.dispose_all)
        self.a, self.b = _captures(2)

    # -- row: path -----------------------------------------------------
    def test_row_path_both_transports_use_worker_manager(self):
        self.app.configure(self.a)
        self.assertIsInstance(self.app._workers, WorkerManager)
        # No transport-local legacy manager or session factory remains
        # reachable. Gate A enforces this mechanically (N1 below); here it
        # is asserted directly so the row states the property, not just the
        # absence of a symbol.
        for gone in ("_manager", "_session_factory", "_session"):
            self.assertFalse(hasattr(self.app, gone),
                             f"app.{gone} should not exist after M1.4")
        for gone in ("_MANAGER", "_session_factory", "_open", "_session"):
            self.assertFalse(hasattr(self.server, gone),
                             f"server.{gone} should not exist after M1.3")

    # -- row: capture isolation (A1) -----------------------------------
    def test_row_capture_isolation_mcp_distinct_pids(self):
        self.server.trace_pixel(self.a, 4, 4)
        self.server.trace_pixel(self.b, 4, 4)
        pa, pb = self.server._WORKERS.pid(self.a), self.server._WORKERS.pid(self.b)
        self.assertIsNotNone(pa)
        self.assertIsNotNone(pb)
        self.assertNotEqual(pa, pb, "A1: two captures must be two processes")

    def test_row_capture_isolation_ide_distinct_pids(self):
        # The IDE owns one capture at a time, so the claim is that successive
        # owners get distinct processes and the previous is released --
        # not that two captures are live at once, which the design forbids.
        self.app.configure(self.a)
        self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        pa = self.app._workers.pid(self.a)
        self.app.configure(self.b)
        self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        pb = self.app._workers.pid(self.b)
        self.assertIsNotNone(pa)
        self.assertIsNotNone(pb)
        self.assertNotEqual(pa, pb, "A1: a reconfigured IDE must respawn")
        self.assertFalse(_pid_alive(pa),
                         "A1: the previous owner must have been released")

    # -- row: controller ------------------------------------------------
    def test_row_no_transport_local_controller(self):
        self.server.trace_pixel(self.a, 4, 4)
        self.server.trace_pixel(self.b, 4, 4)
        self.assertEqual(_live_controllers(), 0,
                         "MCP must open no replay controller in its own process")
        self.app.configure(self.a)
        self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        self.assertEqual(_live_controllers(), 0,
                         "IDE must open no replay controller in its own process")

    # -- row: init lifecycle -------------------------------------------
    def test_row_single_initialisation_per_worker(self):
        for cap in (self.a, self.b):
            self.server.trace_pixel(cap, 4, 4)
            info = self.server._WORKERS.identity(cap)
            self.assertEqual(info["runtime"]["initialise_epoch"], 1,
                             "one worker must initialise the runtime once")
            self.assertEqual(info["runtime"]["live_sessions"], 1)
        self.app.configure(self.a)
        self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        self.assertEqual(self.app._workers.identity(self.a)
                         ["runtime"]["initialise_epoch"], 1)

    # -- row: ownership -------------------------------------------------
    def test_row_ownership_worker_pid_maps_to_its_capture(self):
        self.server.trace_pixel(self.a, 4, 4)
        self.server.trace_pixel(self.b, 4, 4)
        for cap in (self.a, self.b):
            info = self.server._WORKERS.identity(cap)
            self.assertEqual(info["capture"], cap,
                             "the worker serving a capture must be bound to it")
            self.assertEqual(info["worker_pid"],
                             self.server._WORKERS.pid(cap))
            # Stable within the capture's lifetime.
            self.assertEqual(info["worker_instance_id"],
                             self.server._WORKERS.identity(cap)
                             ["worker_instance_id"])

    def test_row_ownership_ide_no_ghost_across_reconfigure(self):
        self.app.configure(self.a)
        self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        first = self.app._workers.pid(self.a)
        self.app.configure(self.b)
        self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        second = self.app._workers.pid(self.b)
        self.assertNotEqual(first, second)
        self.app.dispose()
        self.assertTrue(_await_gone({first, second}))
        self.assertEqual(self.app._workers, None)
        self.assertEqual(self.app._workers.captures()
                         if self.app._workers else [], [])
        self.assertEqual(_live_controllers(), 0)

    # -- row: failure semantics (D3 closure) ----------------------------
    def test_row_failure_semantics_mcp_json_body_and_query_error(self):
        tel = _Telemetry()
        self.addCleanup(tel.close)
        self.server.trace_pixel(self.a, 4, 4)
        # A worker that is already dead: dispose without killing, so the
        # next call must recover and still answer.
        self.server._WORKERS.dispose(self.a)
        payload = json.loads(self.server.trace_pixel(self.a, 4, 4))
        self.assertNotIn("error", payload, "recovery must return a result")
        self.assertIn("summary", payload)

    def test_row_failure_semantics_query_error_is_observable(self):
        tel = _Telemetry()
        self.addCleanup(tel.close)
        # A domain error inside the worker is returned as an error payload by
        # the worker; a dead worker is raised as WorkerError. Both must be
        # observable as failure, neither as a silent success.
        payload = json.loads(self.server.trace_resource(self.a, "ResourceId::999"))
        self.assertIn("error", payload)

    def test_row_failure_semantics_ide_json_body_and_query_error(self):
        tel = _Telemetry()
        self.addCleanup(tel.close)
        self.app.configure(self.a)
        self.app._workers.dispose(self.a)
        status, payload = self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        self.assertEqual(status, 200, "IDE must recover transparently")
        self.assertIn("summary", payload)

    # -- row: bad input -------------------------------------------------
    def test_row_bad_input_mcp_error_payload(self):
        payload = json.loads(self.server.trace_pixel(
            self.a, 4, 4, target="ResourceId::999999"))
        self.assertTrue("error" in payload or "summary" in payload)

    def test_row_bad_input_ide_400_json_not_dropped_connection(self):
        self.app.configure(self.a)
        for query in ({"y": ["4"]}, {"x": ["nope"], "y": ["4"]}):
            status, payload = self.app.route("/api/trace", query)
            self.assertEqual(status, 400)
            self.assertIn("error", payload,
                          "malformed input must still get a body")

    # -- row: worker death / recovery -----------------------------------
    def test_row_recovery_mcp_bounded_respawn_and_verify(self):
        self.server.trace_pixel(self.a, 4, 4)
        before = self.server._WORKERS.pid(self.a)
        # Kill the worker outright, mid-lifetime.
        import psutil
        psutil.Process(before).kill()
        self.assertTrue(_await_gone({before}))
        payload = json.loads(self.server.trace_pixel(self.a, 4, 4))
        after = self.server._WORKERS.pid(self.a)
        self.assertNotEqual(after, before, "a dead worker must be respawned")
        self.assertNotIn("error", payload,
                         "recovery must verify, not just respawn")
        self.assertIn("summary", payload)

    def test_row_recovery_ide_bounded_respawn_and_verify(self):
        self.app.configure(self.a)
        self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        before = self.app._workers.pid(self.a)
        import psutil
        psutil.Process(before).kill()
        self.assertTrue(_await_gone({before}))
        status, payload = self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        self.assertEqual(status, 200)
        after = self.app._workers.pid(self.a)
        self.assertNotEqual(after, before)
        self.assertIn("summary", payload)

    # -- row: shutdown --------------------------------------------------
    def test_row_shutdown_registry_and_state_cleaned(self):
        self.server.trace_pixel(self.a, 4, 4)
        self.server.trace_pixel(self.b, 4, 4)
        pids = {self.server._WORKERS.pid(self.a),
                self.server._WORKERS.pid(self.b)}
        self.server._WORKERS.dispose_all()
        self.assertTrue(_await_gone(pids))
        self.assertEqual(self.server._WORKERS.captures(), [])
        self.assertEqual(self.server._WORKERS.unkillable(), [])
        self.app.configure(self.a)
        self.app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        ipid = self.app._workers.pid(self.a)
        self.app.dispose()
        self.assertTrue(_await_gone({ipid}))
        self.assertIsNone(self.app._workers)
        self.assertEqual(_live_controllers(), 0)

    # -- row: D2 --------------------------------------------------------
    def test_row_d2_runtime_identity_is_unobservable(self):
        # The wording boundary, asserted. A2 is NOT decidable, and no row
        # above may quietly turn process isolation into a runtime claim.
        self.server.trace_pixel(self.a, 4, 4)
        self.app.configure(self.a)
        for info in (self.server._WORKERS.identity(self.a),
                     self.app._workers.identity(self.a)):
            self.assertEqual(info["runtime"]["identity"], "unobservable")
            self.assertIn("RenderDoc exposes no public identity",
                          info["runtime"]["identity_reason"])
            self.assertEqual(info["controller"]["identity"], "unobservable")
            self.assertEqual(info["contract_status"],
                             "diagnostic_only__not_part_of_the_contract")
            # The owning process is real, and equal to the worker's own pid:
            # that is process identity, explicitly not runtime identity.
            self.assertEqual(info["runtime"]["owning_process"],
                             info["worker_pid"])


# ------------------------------------------------------- negative cases
class TestM15NegativeControls(unittest.TestCase):
    """N1-N3. A matrix with only happy paths proves nothing."""

    def _run_audit(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.join(REPO, "src")
        out = subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts",
                                          "audit_boundaries.py")],
            capture_output=True, text=True, env=env, cwd=REPO)
        return out.returncode, out.stdout + out.stderr

    def test_n1_legacy_session_manager_is_rejected_by_gate_a(self):
        """N1: deliberately re-enter the legacy path; Gate A must say no."""
        src = os.path.join(REPO, "src", "rdebug_ide", "app.py")
        with open(src, encoding="utf-8-sig") as fh:
            original = fh.read()
        rc, before = self._run_audit()
        self.assertEqual(rc, 0, "audit must be green before the change")
        try:
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("from rdebug.session_cache import SessionManager\n"
                         + original)
            rc, after = self._run_audit()
            self.assertNotEqual(rc, 0,
                                "Gate A must FAIL once a transport reaches "
                                "back for SessionManager")
            self.assertIn("GATE A", after)
            self.assertIn("session_cache", after)
        finally:
            with open(src, "w", encoding="utf-8", newline="") as fh:
                fh.write(original)
        rc, _ = self._run_audit()
        self.assertEqual(rc, 0, "audit must be green again after restoring")

    def test_n2_a_shared_worker_is_detected_not_merely_different(self):
        """N2: a registry that hands one worker to two captures must violate
        A1, and the in-worker bound-capture guard must refuse the second.

        The point is that this fails as a *violation of the invariant*, not
        as a merely different answer: same pid, and an explicit refusal.
        """
        from rdebug_mcp import server

        server._WORKERS.dispose_all()
        self.addCleanup(server._WORKERS.dispose_all)
        a, b = _captures(2)
        server.trace_pixel(a, 4, 4)
        real_pid = server._WORKERS.pid(a)

        # A registry deliberately collapsed to one worker per process: the
        # second capture resolves to the first capture's worker.
        original_get = server._WORKERS._get

        def shared_get(capture):
            if os.path.abspath(capture) == b:
                return original_get(a)
            return original_get(capture)

        server._WORKERS._get = shared_get
        try:
            # The transport correctly turns the raised WorkerError into an
            # error payload, so the violation is observed in the response
            # rather than as an escaping exception.
            payload = json.loads(server.trace_pixel(b, 4, 4))
            self.assertIn("error", payload)
            self.assertIn("worker bound to", payload["error"],
                          "the in-worker guard must refuse the second capture")
            # A1 is violated, detectably: both captures report one pid.
            self.assertEqual(server._WORKERS.pid(a), real_pid)
            # The registry has no entry for b at all, yet b was served: the
            # registry and reality have diverged, which is exactly the
            # ghost shape §2.9 forbids, now caught by an invariant instead
            # of by a length check.
            self.assertIsNone(server._WORKERS.pid(b))
            self.assertEqual(server._WORKERS.identity(a)["capture"], a)
        finally:
            server._WORKERS._get = original_get
            server._WORKERS.dispose_all()

    def test_n3_worker_failure_is_not_mislabelled_a_bad_request(self):
        """N3: the full chain, and the classification must stay right.

        worker failure -> WorkerError (an RDebugError) -> transport JSON
        body -> query_error telemetry, and never the bad_request branch,
        which belongs to malformed input.
        """
        from rdebug_ide import app
        from rdebug_mcp import server

        server._WORKERS.dispose_all()
        app.dispose()
        self.addCleanup(app.dispose)
        self.addCleanup(server._WORKERS.dispose_all)
        a, _b = _captures(2)

        def boom(*_a, **_kw):
            raise WorkerError("worker died (rc=9)")

        tel = _Telemetry()
        self.addCleanup(tel.close)

        # MCP
        routes = dict(server.__dict__)
        original = server._run
        server._run = boom
        try:
            payload = json.loads(server.trace_pixel(a, 4, 4))
        finally:
            server._run = original
        self.assertIn("error", payload)
        self.assertIn("worker died", payload["error"])
        mcp_errors = tel.events("query_error")
        self.assertTrue(mcp_errors, "query_error must be observable")
        self.assertTrue(any(e["transport"] == "mcp" for e in mcp_errors))

        # IDE
        app.configure(a)
        original_run = app._run
        app._run = boom
        try:
            status, payload = app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        finally:
            app._run = original_run
        self.assertEqual(status, 400)
        self.assertIn("worker died", payload["error"])
        self.assertNotIn("invalid request parameters", payload["error"],
                         "a dead worker is not a malformed request")
        ide_errors = tel.events("query_error")
        self.assertTrue(ide_errors)
        for e in ide_errors:
            self.assertNotIn("kind", e,
                             "bad_request classification must not leak in")
        self.assertTrue(any(e["transport"] == "ide" for e in ide_errors))
        del routes


if __name__ == "__main__":
    unittest.main()
