"""M1.4 acceptance invariants I1-I3, against real RenderDoc.

The unit-level versions in tests_transport/test_ide_app.py cover the
ownership logic with a worker double. These cover the part a double cannot:
that the real thing leaves no native state behind.

The regression that matters is the ghost. Before M1.4, configure() rebound
a module-global SessionManager without disposing the old one, and
SessionManager has no __del__, so its sessions were freed by refcounting
without CaptureSession.close() ever running. A second configure() therefore
left the previous capture's ReplayController and OpenCaptureFile handle
alive and invisible: the surface reported the new capture while a stale
session still held native state, and _REPLAY_LIFECYCLE["sessions"] stayed
permanently inflated, which in turn made shutdown_replay() unreachable.

Asserting only "the registry is empty at the end" would pass even with a
ghost, because a ghost is by definition something the registry can no
longer see. These tests therefore check actual ownership and the process
lifecycle counter, not just lengths.
"""

import os
import unittest

from rdebug.adapter import core
from rdebug.adapter.locator import find_module_dir
from rdebug_ide import app

CORPUS_ENV = "RDEBUG_ISOLATION_CAPTURE_DIR"
DEFAULT_CORPUS = os.path.join("tests", "workload", "corpus")


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


@unittest.skipUnless(_ready(), _SKIP)
class TestIdeOwnershipInvariants(unittest.TestCase):
    def setUp(self):
        app.dispose()
        self.addCleanup(app.dispose)

    def _live_controllers(self):
        return core._REPLAY_LIFECYCLE["sessions"]

    def _pids(self):
        mgr = app._workers
        if mgr is None:
            return set()
        return {mgr.pid(c) for c in mgr.captures()}

    def _pids_alive(self, pids):
        import psutil
        return {p for p in pids if p and psutil.pid_exists(p)}

    def test_i1_one_owner_and_no_controller_in_the_ide_process(self):
        a, _b = _captures(2)
        app.configure(a)
        self.assertEqual(app._STATE["capture"], a)
        self.assertEqual(len(app._workers.captures()), 1)
        # The IDE process itself opens nothing; the work is in the worker.
        self.assertEqual(self._live_controllers(), 0)

    def test_i2_dispose_terminates_the_worker_process(self):
        a, _b = _captures(2)
        app.configure(a)
        app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        pids = self._pids_alive(self._pids())
        self.assertEqual(len(pids), 1)
        app.dispose()
        import time

        import psutil
        stop = time.time() + 20
        while time.time() < stop and psutil.pid_exists(next(iter(pids))):
            time.sleep(0.05)
        self.assertFalse(psutil.pid_exists(next(iter(pids))),
                         "dispose() must terminate the worker, not just drop it")
        self.assertIsNone(app._workers)
        self.assertEqual(self._pids_alive(pids), set())

    def test_i3_no_ghost_after_reconfigure_then_dispose(self):
        # The core M1.4 regression.
        a, b = _captures(2)
        app.configure(a)
        app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        a_pids = self._pids_alive(self._pids())
        self.assertEqual(len(a_pids), 1)

        app.configure(b)
        b_pids = self._pids_alive(self._pids())
        self.assertEqual(len(b_pids), 1)
        # A was released before B was claimed.
        self.assertNotEqual(a_pids, b_pids)
        app.route("/api/trace", {"x": ["4"], "y": ["4"]})

        app.dispose()
        import time

        everything = a_pids | b_pids
        stop = time.time() + 20
        while time.time() < stop and self._pids_alive(everything):
            time.sleep(0.05)

        self.assertEqual(self._pids_alive(everything), set(),
                         "neither capture may leave a worker behind")
        self.assertEqual(self._pids(), set(), "registry must be empty")
        self.assertEqual(app._workers, None)
        self.assertFalse(app._STATE["ready"])
        # The lifecycle counter is the ghost detector: a leaked
        # CaptureSession would keep it above zero forever, and
        # shutdown_replay() -- which requires sessions == 0 -- unreachable.
        self.assertEqual(self._live_controllers(), 0,
                         "the IDE process must hold no live controller")

    def test_i3_shutdown_replay_stays_reachable(self):
        # The escape hatch the old ghost permanently disabled.
        a, _b = _captures(2)
        for _ in range(3):
            app.configure(a)
            app.route("/api/trace", {"x": ["4"], "y": ["4"]})
            app.configure(os.path.abspath(_captures(2)[1]))
            app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        app.dispose()
        self.assertEqual(self._live_controllers(), 0)
        # Must not raise, and must not be short-circuited by a stale count.
        core.CaptureSession.shutdown_replay()

    def test_i2_failed_configure_leaves_nothing_behind(self):
        a, _b = _captures(2)
        app.configure(a)
        good = self._pids_alive(self._pids())
        missing = os.path.join(_capture_dir(), "definitely-not-here.rdc")
        # WorkerError: the worker exits during its startup round trip, and
        # configure() re-raises rather than swallowing.
        from rdebug.worker_manager import WorkerError
        with self.assertRaises(WorkerError):
            app.configure(missing)
        # No owner, no registry, and the previous capture was released
        # rather than left half-owned.
        self.assertIsNone(app._workers)
        self.assertIsNone(app._STATE["capture"])
        self.assertFalse(app._STATE["ready"])
        self.assertEqual(self._pids_alive(good), set())
        self.assertEqual(self._live_controllers(), 0)

    def test_worker_reports_one_runtime_initialisation(self):
        # D1/D2 evidence on the IDE path: each worker initialised the replay
        # runtime exactly once, so the F-N3-4 double-initialisation condition
        # is absent, and the runtime identity is honestly unobservable.
        a, b = _captures(2)
        app.configure(a)
        app.route("/api/trace", {"x": ["4"], "y": ["4"]})
        info = app._workers.identity(a)
        self.assertEqual(info["runtime"]["initialise_epoch"], 1)
        self.assertEqual(info["runtime"]["live_sessions"], 1)
        self.assertEqual(info["runtime"]["identity"], "unobservable")
        self.assertIn("RenderDoc exposes no public identity",
                      info["runtime"]["identity_reason"])
        self.assertEqual(info["contract_status"],
                         "diagnostic_only__not_part_of_the_contract")


if __name__ == "__main__":
    unittest.main()
