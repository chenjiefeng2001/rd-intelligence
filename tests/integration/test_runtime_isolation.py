"""§2.9 MUST: a process must not hold a second live ReplayController.

core.py holds _REPLAY_LIFECYCLE as a process global, so InitialiseReplay()
runs once per process while every CaptureSession carries its own
ReplayController. N sessions therefore share one replay runtime with N
controllers coexisting -- the W1-R1 F-1/F-2 shape.

This is the invariant itself, checked at runtime, deliberately NOT a
shadow of whatever enforcement mechanism happens to exist. A static check
for "is there a raise in __init__" can only prove the shape of the fix;
opening two sessions and counting controllers is what actually proves the
property. The static shape check lives in audit_boundaries.py as Gate B
and is labelled there as a proxy.

State of the two tests below:

  test_worker_isolation_*  -- the target state, already true. A worker
    process is one capture and therefore one runtime, so two captures get
    two processes. This is the property the migration is trying to give
    the transports, so it is worth proving it holds on the target path
    before anything is rewired.

  test_transport_path_keeps_one_controller -- currently VIOLATED, which is
    why it is marked expectedFailure. M0 measured 2 distinct
    ReplayControllers sharing 1 runtime in a single process. When the
    transports are wired to WorkerManager (M1.3) this test will start
    passing, and unittest will then report unexpectedSuccess, which fails
    the suite until the decorator is removed. That is the intent: the
    violation cannot be forgotten, and the fix cannot pass unnoticed.
"""

import os
import unittest

from rdebug.adapter import core
from rdebug.adapter.core import CaptureSession
from rdebug.adapter.locator import find_module_dir

# A directory env var of its own: RDEBUG_INTEGRATION_CAPTURE names a single
# file for the replay tests, and pointing it at a directory breaks them.
CORPUS_ENV = "RDEBUG_ISOLATION_CAPTURE_DIR"
DEFAULT_CORPUS = os.path.join("tests", "workload", "corpus")


def _capture_dir():
    return os.environ.get(CORPUS_ENV) or DEFAULT_CORPUS


def _captures(n=2):
    """First n *.rdc in the corpus, so the test does not hardcode a name."""
    d = _capture_dir()
    found = sorted(os.path.join(d, f) for f in os.listdir(d)
                   if f.endswith(".rdc"))
    if len(found) < n:
        raise unittest.SkipTest(f"need {n} captures in {d}")
    return [os.path.abspath(p) for p in found[:n]]


def _ready():
    return find_module_dir() is not None and os.path.isdir(_capture_dir())


_SKIP = f"set {CORPUS_ENV} to a directory of .rdc captures and make the " \
        "renderdoc python module importable (RDEBUG_RENDERDOC_PATH)"


@unittest.skipUnless(_ready(), _SKIP)
class TestOneLiveControllerPerProcess(unittest.TestCase):
    def _live_controllers(self):
        """Live CaptureSessions in this process, each holding a controller."""
        return core._REPLAY_LIFECYCLE["sessions"]

    def test_single_session_is_one_controller(self):
        # The positive control: the invariant is satisfiable and our
        # measurement agrees with reality. Without this, a test that always
        # sees 2 could just be a broken counter.
        s = CaptureSession(_captures(1)[0])
        try:
            self.assertEqual(self._live_controllers(), 1)
        finally:
            s.close()

    @unittest.expectedFailure
    def test_legacy_session_manager_path_keeps_one_controller(self):
        """The §2.9 invariant, on the path that still violates it.

        Since M1.3 the MCP transport is served by WorkerManager, so MCP no
        longer appears here; this now covers the legacy in-process
        SessionManager, which rdebug_ide still uses. SessionManager defaults
        to max_sessions=4, so holding two captures is normal usage there.

        expectedFailure, not skipped: the violation is real and must stay
        visible. When the IDE is wired to WorkerManager (M1.4) this test
        will start passing and unittest will report unexpectedSuccess,
        failing the suite until the decorator is removed.
        """
        from rdebug.session_cache import SessionManager

        a, b = _captures(2)
        # factory_provider is a zero-arg callable returning the class,
        # matching how the transports wire it.
        mgr = SessionManager(factory_provider=lambda: CaptureSession)
        try:
            with mgr.use(a) as sa, mgr.use(b) as sb:
                self.assertIsNot(sa, sb, "sanity: two distinct sessions")
                self.assertLessEqual(
                    self._live_controllers(), 1,
                    "two CaptureSessions are live in one process, sharing "
                    "one replay runtime: the W1-R1 F-1/F-2 shape")
        finally:
            mgr.dispose_all()

    def test_mcp_transport_path_keeps_one_controller(self):
        """The same invariant, on the path migrated in M1.3.

        Two captures go through the real MCP transport, so each gets its own
        worker process and this process never holds a second controller.
        This is the property the migration was for, and it is the control
        that shows the expectedFailure above is about the legacy path rather
        than about the measurement being wrong.
        """
        from rdebug_mcp import server

        a, b = _captures(2)
        self.addCleanup(server._WORKERS.dispose_all)
        # Two different captures, so two workers, and a query against each.
        server.trace_pixel(a, 4, 4)
        server.trace_pixel(b, 4, 4)
        self.assertEqual(self._live_controllers(), 0,
                         "the transport must not open a controller here; "
                         "the work is done in the worker processes")
        pids = {server._WORKERS.pid(a), server._WORKERS.pid(b)}
        self.assertEqual(len(pids), 2,
                         "two captures must be served by two processes")
        for cap in (a, b):
            info = server._WORKERS.identity(cap)
            # Each worker initialised the runtime exactly once, so the
            # F-N3-4 double-initialisation condition is absent.
            self.assertEqual(info["runtime"]["initialise_epoch"], 1)
            self.assertEqual(info["runtime"]["live_sessions"], 1)


@unittest.skipUnless(_ready(), _SKIP)
class TestWorkerIsolationTargetState(unittest.TestCase):
    """The property the migration is trying to give the transports.

    Already true on the worker path, so it is not expectedFailure: it is
    the evidence that the target state is achievable, measured before
    anything is rewired.
    """

    def test_two_captures_get_two_worker_processes(self):
        from rdebug.worker_manager import WorkerManager

        a, b = _captures(2)
        mgr = WorkerManager()
        try:
            self.assertTrue(mgr.ping(a))
            self.assertTrue(mgr.ping(b))
            self.assertNotEqual(mgr.pid(a), mgr.pid(b),
                                "each capture must own a distinct process")
            self.assertEqual(len(mgr.captures()), 2)
        finally:
            mgr.dispose_all()

    def test_worker_refuses_a_foreign_capture(self):
        # workers.py:204-209 rejects a request naming a capture it is not
        # bound to. Driven through _Worker.request rather than
        # WorkerManager.query because query() takes `capture` as its first
        # positional, so it cannot also be forwarded in the args dict --
        # which is precisely the wiring trap recorded in the M0 scope
        # document §5.6-3: a transport that forgets to forward `capture`
        # makes this guard pass vacuously.
        from rdebug.worker_manager import WorkerError, WorkerManager

        a, b = _captures(2)
        mgr = WorkerManager()
        try:
            mgr.ping(a)
            w = mgr._workers[os.path.abspath(a)]
            with self.assertRaises(WorkerError) as ctx:
                w.request("trace_pixel", {"capture": b, "x": 1, "y": 1})
            self.assertIn("worker bound to", str(ctx.exception))
        finally:
            mgr.dispose_all()

    def test_query_without_capture_in_args_leaves_the_guard_vacuous(self):
        # Documents the trap rather than the guarantee: WorkerManager.query
        # does not inject `capture` into the forwarded args, so this call
        # reaches the worker's guard with capture absent and the guard
        # passes without verifying anything. A migrated transport MUST
        # forward capture explicitly; audit_boundaries.py Gate A cannot
        # detect the omission, which is why this test is here.
        from rdebug.worker_manager import WorkerManager

        a, _b = _captures(2)
        mgr = WorkerManager()
        try:
            mgr.ping(a)
            w = mgr._workers[os.path.abspath(a)]
            # No "capture" key: the guard cannot compare and lets it through.
            self.assertFalse(w.request("trace_pixel", {"x": 1, "y": 1},
                                       timeout=600) is None)
        finally:
            mgr.dispose_all()


if __name__ == "__main__":
    unittest.main()
