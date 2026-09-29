"""M1.5: the IDE's CI workflow must still work through the worker.

The ci_check op was added in M1.4 so the IDE could keep its Stable Core
surface. What M1.5 has to show is not that the op exists but that the
workflow still completes, still goes through WorkerManager, and does not
reintroduce transport-local replay state.

A real baseline is recorded from a real capture, then consumed through the
IDE route -- so the whole path crosses the process boundary.
"""
import json
import os
import unittest

from rdebug.adapter import core
from rdebug.adapter.core import CaptureSession
from rdebug.adapter.locator import find_module_dir
from rdebug.ci import record
from rdebug_ide import app

CORPUS_ENV = "RDEBUG_ISOLATION_CAPTURE_DIR"
DEFAULT_CORPUS = os.path.join("tests", "workload", "corpus")


def _capture_dir():
    return os.environ.get(CORPUS_ENV) or DEFAULT_CORPUS


def _capture():
    d = _capture_dir()
    found = sorted(os.path.join(d, f) for f in os.listdir(d)
                   if f.endswith(".rdc"))
    if not found:
        raise unittest.SkipTest(f"no .rdc in {d}")
    return os.path.abspath(found[0])


def _ready():
    return find_module_dir() is not None and os.path.isdir(_capture_dir())


_SKIP = (f"set {CORPUS_ENV} to a directory of .rdc captures and make the "
         "renderdoc python module importable (RDEBUG_RENDERDOC_PATH)")


@unittest.skipUnless(_ready(), _SKIP)
class TestIdeCiWorkflowThroughWorker(unittest.TestCase):
    def setUp(self):
        app.dispose()
        self.addCleanup(app.dispose)
        self.capture = _capture()

    def test_ci_baseline_recorded_in_process_then_checked_in_the_worker(self):
        # 1. Record a baseline. Done in-process because ci.record has no
        #    worker op and does not need one: it is an authoring step, not
        #    something a transport performs repeatedly.
        session = CaptureSession(self.capture)
        try:
            baseline = record(session, {"name": "m15", "pixels": [[4, 4]]})
        finally:
            session.close()
        self.assertIsInstance(baseline, dict)
        self.assertTrue(baseline)

        # 2. Consume it through the IDE, which must cross the process
        #    boundary rather than opening a capture of its own.
        before = core._REPLAY_LIFECYCLE["sessions"]
        app.configure(self.capture, baseline=baseline)
        status, payload = app.route("/api/ci", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["enabled"])
        self.assertIn("status", payload)
        # 3. The IDE process itself still opened nothing.
        self.assertEqual(core._REPLAY_LIFECYCLE["sessions"], before)
        self.assertEqual(core._REPLAY_LIFECYCLE["sessions"], 0)

    def test_ci_check_ran_in_the_worker_process(self):
        session = CaptureSession(self.capture)
        try:
            baseline = record(session, {"name": "m15b", "pixels": [[4, 4]]})
        finally:
            session.close()
        app.configure(self.capture, baseline=baseline)
        app.route("/api/ci", {})
        info = app._workers.identity(self.capture)
        # The worker serving the IDE owns a live session, proving the CI
        # check executed there and not in the transport.
        self.assertEqual(info["runtime"]["live_sessions"], 1)
        self.assertEqual(info["runtime"]["initialise_epoch"], 1)
        self.assertEqual(info["runtime"]["identity"], "unobservable")

    def test_tampered_baseline_is_reported_as_a_failure_not_swallowed(self):
        # A CI gate that cannot fail is the failure-to-look family again
        # (F12 put a wrong result into a CI baseline). Tamper the real key,
        # captureSha256, and the check must report a regression -- and must
        # still do so after the baseline has crossed the process boundary.
        session = CaptureSession(self.capture)
        try:
            baseline = record(session, {"name": "m15c", "pixels": [[4, 4]]})
        finally:
            session.close()
        tampered = json.loads(json.dumps(baseline))
        tampered["captureSha256"] = "0" * 64
        app.configure(self.capture, baseline=tampered)
        status, payload = app.route("/api/ci", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "regression",
                         "a wrong capture hash must not report a pass")
        self.assertFalse(payload["captureHashMatch"])
        self.assertTrue(any(f.get("path") == "captureSha256"
                            for f in payload["failures"]))

    def test_ci_disabled_without_a_baseline(self):
        app.configure(self.capture)
        status, payload = app.route("/api/ci", {})
        self.assertEqual(status, 200)
        self.assertFalse(payload["enabled"])


if __name__ == "__main__":
    unittest.main()
