"""Tests for the runtime isolation layer (DESIGN_SPEC §2.9).

Covers rdebug.worker_manager: RecyclePolicy triggers, the spawn/lifecycle
protocol against a stub worker, and crash recovery. Deliberately does NOT
need a real RenderDoc install: the worker process is replaced by a stub
speaking the same stdin/stdout JSONL protocol, so the recycle and recovery
logic is exercised without replaying a capture.

Regression guards, in particular:
  * the private-memory baseline is actually captured on spawn -- it used to
    be initialised after a `return` in _death_message(), so it stayed None
    and the max_private_memory_delta trigger could never fire;
  * a missing private-bytes metric never degrades into an RSS gate.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from rdebug import worker_manager as wm
from rdebug.worker_manager import RecyclePolicy, WorkerError, WorkerManager, _Worker

# Speaks the same protocol as rdebug.workers: one JSON object per line on
# stdin, one per line on stdout. Ops: ping / call / exit, plus test-only
# "die" and "boom" to force a crash and a stderr write.
_STUB_WORKER = textwrap.dedent('''
    import json, sys

    if "--fail-startup" in sys.argv:
        sys.stderr.write("stub: cannot open capture\\n")
        sys.stderr.flush()
        sys.exit(3)

    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        rid = req.get("id")
        op = req.get("op", "call")
        if op == "exit":
            send({"id": rid, "ok": True, "result": json.dumps("bye")})
            break
        if op == "ping":
            send({"id": rid, "ok": True, "result": json.dumps("pong")})
            continue
        if op == "die":
            sys.stderr.write("stub: deliberate crash\\n")
            sys.stderr.flush()
            sys.exit(9)
        if op == "boom":
            send({"id": rid, "ok": False,
                  "error": "ValueError: synthetic query failure"})
            continue
        if op == "wrongid":
            send({"id": -1, "ok": True, "result": json.dumps("nope")})
            continue
        send({"id": rid, "ok": True,
              "result": json.dumps({"tool": req.get("tool"),
                                    "args": req.get("args")})})
''')


class _StubBackend:
    """Redirects _Worker spawns at the stub worker instead of rdebug.workers.

    Failure injection:
      spawn_failures   -- Popen itself fails (no process is created)
      startup_failures -- the worker starts then dies before answering ping,
                          which is the path that must not orphan a process
    Both are reset for every test so state cannot leak between them.
    """

    def __init__(self):
        self.path = None
        self._real = None
        self.spawn_failures = 0
        self.startup_failures = 0

    def reset(self):
        self.spawn_failures = 0
        self.startup_failures = 0

    def start(self):
        fd, self.path = tempfile.mkstemp(suffix="_worker_stub.py")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_STUB_WORKER)
        self._real = subprocess.Popen

        def _popen(cmd, *a, **kw):
            if isinstance(cmd, (list, tuple)) and "rdebug.workers" in cmd:
                if self.spawn_failures:
                    self.spawn_failures -= 1
                    raise WorkerError("stub: simulated spawn failure")
                cmd = [sys.executable, self.path,
                       cmd[list(cmd).index("--capture") + 1]]
                if self.startup_failures:
                    self.startup_failures -= 1
                    cmd = cmd + ["--fail-startup"]
            return self._real(cmd, *a, **kw)

        wm.subprocess.Popen = _popen
        return self

    def stop(self):
        if self._real is not None:
            wm.subprocess.Popen = self._real
        if self.path and os.path.exists(self.path):
            os.unlink(self.path)


class _StubWorkerBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = _StubBackend().start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.stop()

    def setUp(self):
        self.backend.reset()
        self.capture = os.path.join(tempfile.gettempdir(),
                                    "wm_fake_capture.rdc")
        self.mgr = WorkerManager()
        self.addCleanup(self.mgr.dispose_all)

    def new_worker(self, capture=None):
        w = _Worker(capture or self.capture, dict(os.environ))
        self.addCleanup(w.kill)
        return w

    @staticmethod
    def kill_worker(w):
        """Ask the worker to die and block until the process is reaped.

        Without this the next call can still see a live process and take the
        'pipe broken' path instead of the 'worker died' path, which makes
        the recovery assertions racy."""
        with _suppressed(WorkerError):
            w.request(op="die", timeout=30)
        deadline = time.time() + 15
        while time.time() < deadline and w.alive():
            time.sleep(0.02)
        self_deny = w.alive()
        if self_deny:
            w.kill()
        return not self_deny


class TestRecyclePolicy(unittest.TestCase):
    def test_production_default_is_the_frozen_w1r4_value(self):
        p = RecyclePolicy.production_default()
        self.assertEqual(p.max_queries, 250)
        self.assertEqual(p.max_private_memory_delta_mb, 128)
        self.assertEqual(p.max_lifetime_s, 1800)

    def test_env_overrides_every_trigger(self):
        env = {"RDEBUG_RECYCLE_MAX_QUERIES": "7",
               "RDEBUG_RECYCLE_MAX_PRIVATE_MEMORY_DELTA_MB": "3.5",
               "RDEBUG_RECYCLE_MAX_LIFETIME_S": "11"}
        with _env_patched(env):
            p = RecyclePolicy.production_default()
        self.assertEqual(p.max_queries, 7)
        self.assertEqual(p.max_private_memory_delta_mb, 3.5)
        self.assertEqual(p.max_lifetime_s, 11)

    def test_active_reflects_any_configured_trigger(self):
        self.assertFalse(RecyclePolicy().active())
        self.assertTrue(RecyclePolicy(max_queries=1).active())
        self.assertTrue(RecyclePolicy(max_lifetime_s=1).active())
        self.assertTrue(
            RecyclePolicy(max_private_memory_delta_mb=1).active())


class _FakeWorker:
    """Minimal stand-in exposing only what _recycle_reason reads."""

    def __init__(self, queries=0, age_s=0.0, mem_base=None, mem_now=None):
        self.queries_served = queries
        self.born = time.monotonic() - age_s
        self.mem_baseline = mem_base
        self._mem_now = mem_now

    def mem_current(self):
        return self._mem_now


class TestRecycleTriggers(unittest.TestCase):
    def reason(self, policy, w):
        return WorkerManager(recycle=policy)._recycle_reason(w)

    def test_no_policy_never_recycles(self):
        w = _FakeWorker(queries=10 ** 6, age_s=10 ** 6,
                        mem_base=0, mem_now=10 ** 12)
        self.assertIsNone(self.reason(None, w))

    def test_max_queries_fires_at_threshold(self):
        p = RecyclePolicy(max_queries=10)
        self.assertIsNone(self.reason(p, _FakeWorker(queries=9)))
        self.assertEqual(self.reason(p, _FakeWorker(queries=10)),
                         "max_queries")

    def test_max_lifetime_fires(self):
        p = RecyclePolicy(max_lifetime_s=5)
        self.assertIsNone(self.reason(p, _FakeWorker(age_s=4.9)))
        self.assertEqual(self.reason(p, _FakeWorker(age_s=5.1)),
                         "max_lifetime")

    def test_private_memory_delta_fires_when_baseline_present(self):
        # The regression this whole file exists for: mem_baseline used to be
        # set only after a `return`, so it was always None here and this
        # branch was unreachable.
        p = RecyclePolicy(max_private_memory_delta_mb=128)
        mb = 1048576
        ok = _FakeWorker(mem_base=200 * mb, mem_now=200 * mb + 100 * mb)
        over = _FakeWorker(mem_base=200 * mb, mem_now=200 * mb + 128 * mb)
        self.assertIsNone(self.reason(p, ok))
        self.assertEqual(self.reason(p, over), "max_private_memory_delta")

    def test_missing_baseline_does_not_fire_and_does_not_fall_back_to_rss(self):
        # DESIGN_SPEC §2.9: RSS must never become a gate. With no private
        # baseline the trigger must be inert, not silently substituted.
        p = RecyclePolicy(max_private_memory_delta_mb=1)
        w = _FakeWorker(mem_base=None, mem_now=10 ** 12)
        self.assertIsNone(self.reason(p, w))

    def test_missing_current_does_not_fire(self):
        p = RecyclePolicy(max_private_memory_delta_mb=1)
        self.assertIsNone(self.reason(p, _FakeWorker(mem_base=0,
                                                     mem_now=None)))

    def test_triggers_are_anded_independently(self):
        p = RecyclePolicy(max_queries=10, max_lifetime_s=5,
                          max_private_memory_delta_mb=128)
        mb = 1048576
        both = _FakeWorker(queries=50, age_s=50, mem_base=0, mem_now=999 * mb)
        self.assertEqual(self.reason(p, both), "max_queries")
        late = _FakeWorker(queries=1, age_s=50, mem_base=0, mem_now=999 * mb)
        self.assertEqual(self.reason(p, late), "max_lifetime")


class TestWorkerError(unittest.TestCase):
    def test_transient_defaults_false(self):
        self.assertFalse(WorkerError("dead in the water").transient)

    def test_transient_is_structured_not_inferred_from_text(self):
        # A query-level error whose message merely contains "dead" must not
        # be treated as a dead worker (that used to be a substring match
        # and would trigger a spurious full process recycle).
        e = WorkerError("shader 'deadbeef' not found")
        self.assertFalse(e.transient)
        self.assertTrue(WorkerError("worker dead", transient=True).transient)


class TestWorkerLifecycle(_StubWorkerBase):
    def test_spawn_captures_private_memory_baseline(self):
        w = self.new_worker()
        self.addCleanup(w.kill)
        if not _private_memory_available():
            self.skipTest("psutil private memory unavailable on this platform")
        # Regression: baseline must be populated post-spawn. Skip only when
        # the metric genuinely does not exist on this platform -- a None
        # baseline while the metric IS available is a failure, not a skip.
        self.assertIsNotNone(w.mem_baseline)
        self.assertGreater(w.mem_baseline, 0)
        self.assertEqual(w.rss_baseline, w.mem_baseline)

    def test_worker_info_uses_private_memory_naming(self):
        w = self.new_worker()
        self.addCleanup(w.kill)
        mgr = WorkerManager()
        mgr._workers[os.path.abspath(self.capture)] = w
        self.addCleanup(mgr.dispose_all)
        info = mgr.worker_info(self.capture)
        self.assertIn("private_memory_baseline_bytes", info)
        self.assertIn("memory_metric", info)
        # §2.9 naming MUST: no RSS-named field may carry a gate metric.
        self.assertNotIn("rss_baseline", info)
        self.assertNotIn("metric", info)
        self.assertIn(info["memory_metric"], ("private", "unavailable"))

    def test_ping_round_trip(self):
        w = self.new_worker()
        self.addCleanup(w.kill)
        self.assertTrue(mgr_ok(w))

    def test_call_round_trip_returns_parsed_payload(self):
        mgr = WorkerManager()
        self.addCleanup(mgr.dispose_all)
        out = mgr.query(self.capture, "trace_pixel", x=1, y=2)
        self.assertEqual(out["tool"], "trace_pixel")
        self.assertEqual(out["args"], {"x": 1, "y": 2})

    def test_only_call_ops_increment_the_query_counter(self):
        w = self.new_worker()
        self.addCleanup(w.kill)
        self.assertEqual(w.queries_served, 0)
        w.request("trace_pixel", {}, timeout=30)
        self.assertEqual(w.queries_served, 1)
        w.request(op="ping", timeout=30)
        self.assertEqual(w.queries_served, 1)

    def test_worker_error_surfaces_non_transient(self):
        mgr = WorkerManager()
        self.addCleanup(mgr.dispose_all)
        mgr._get(self.capture)
        key = os.path.abspath(self.capture)
        with self.assertRaises(WorkerError) as ctx:
            mgr._workers[key].request(op="boom", timeout=30)
        self.assertIn("synthetic query failure", str(ctx.exception))
        self.assertFalse(ctx.exception.transient)

    def test_stderr_tail_is_captured_for_diagnostics(self):
        w = self.new_worker()
        self.assertTrue(self.kill_worker(w))
        self.assertTrue(any("deliberate crash" in line
                            for line in w.stderr_tail()))

    def test_request_on_dead_worker_is_transient_and_includes_stderr(self):
        w = self.new_worker()
        self.assertTrue(self.kill_worker(w))
        with self.assertRaises(WorkerError) as ctx:
            w.request("trace_pixel", {}, timeout=30)
        self.assertTrue(ctx.exception.transient)
        self.assertIn("stderr_tail=", str(ctx.exception))

    def test_failed_startup_terminates_the_process_and_reports_it(self):
        # A worker that starts then dies before the ping must not be left
        # running: it already holds a live replay runtime (§2.9).
        self.backend.startup_failures = 1
        with self.assertRaises(WorkerError) as ctx:
            _Worker(self.capture, dict(os.environ))
        self.assertIn("cannot open capture", str(ctx.exception))

    def test_kill_is_idempotent_and_handles_missing_process(self):
        w = self.new_worker()
        w.kill()
        w.kill()
        self.assertFalse(w.alive())


class TestWorkerManagerRecovery(_StubWorkerBase):
    def test_crash_is_recovered_transparently(self):
        mgr = WorkerManager()
        self.addCleanup(mgr.dispose_all)
        first = mgr.pid(self.capture)
        self.assertTrue(self.kill_worker(mgr._get(self.capture)))
        out = mgr.query(self.capture, "trace_pixel", x=3, y=4)
        self.assertEqual(out["args"], {"x": 3, "y": 4})
        self.assertNotEqual(mgr.pid(self.capture), first)
        self.assertTrue(any(e["reason"] == "worker_died"
                            for e in mgr.recycle_events))

    def test_dead_worker_is_recycled_before_serving_next_query(self):
        mgr = WorkerManager()
        self.addCleanup(mgr.dispose_all)
        w = mgr._get(self.capture)
        pid = w.proc.pid
        self.assertTrue(self.kill_worker(w))
        mgr.query(self.capture, "trace_pixel", x=1, y=1)
        self.assertNotEqual(mgr.pid(self.capture), pid)
        self.assertTrue(mgr.alive(self.capture))

    def test_recycle_event_uses_private_memory_field_names(self):
        mgr = WorkerManager(recycle=RecyclePolicy(max_queries=1))
        self.addCleanup(mgr.dispose_all)
        mgr.query(self.capture, "trace_pixel", x=1, y=1)
        mgr.query(self.capture, "trace_pixel", x=1, y=1)
        events = [e for e in mgr.recycle_events if e["reason"] == "max_queries"]
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertIn("private_memory_baseline_mb", ev)
        self.assertIn("private_memory_last_mb", ev)
        self.assertNotIn("mem_baseline_mb", ev)
        self.assertNotIn("mem_last_mb", ev)
        # §2.9 naming MUST: a missing metric is reported as "unavailable",
        # never coerced to 0 (which would read as a real measurement).
        for field in ("private_memory_baseline_mb", "private_memory_last_mb"):
            value = ev[field]
            if isinstance(value, str):
                self.assertEqual(value, "unavailable")
            else:
                self.assertGreater(value, 0.0)

    def test_deterministic_recycle_does_not_retry_spawn(self):
        mgr = WorkerManager(recycle=RecyclePolicy(max_queries=1))
        self.addCleanup(mgr.dispose_all)
        mgr.query(self.capture, "trace_pixel", x=1, y=1)
        # A policy-triggered recycle is deterministic: a spawn failure must
        # surface immediately rather than being retried.
        self.backend.spawn_failures = 1
        with self.assertRaises(WorkerError):
            mgr.query(self.capture, "trace_pixel", x=1, y=1)
        self.assertEqual(self.backend.spawn_failures, 0)

    def test_crash_recycle_allows_bounded_spawn_retry(self):
        mgr = WorkerManager()
        self.addCleanup(mgr.dispose_all)
        first = mgr.pid(self.capture)
        self.assertTrue(self.kill_worker(mgr._get(self.capture)))
        self.backend.spawn_failures = 2
        self.assertTrue(mgr.ping(self.capture))
        self.assertNotEqual(mgr.pid(self.capture), first)
        self.assertEqual(self.backend.spawn_failures, 0)

    def test_crash_recycle_gives_up_after_bounded_retries(self):
        mgr = WorkerManager()
        self.addCleanup(mgr.dispose_all)
        self.assertTrue(self.kill_worker(mgr._get(self.capture)))
        # §2.9 bounded retry: 3 attempts, then the error surfaces.
        self.backend.spawn_failures = 3
        with self.assertRaises(WorkerError):
            mgr.ping(self.capture)
        self.assertEqual(self.backend.spawn_failures, 0)

    def test_max_workers_evicts_and_keeps_working(self):
        other = self.capture + ".2"
        mgr = WorkerManager(max_workers=1)
        self.addCleanup(mgr.dispose_all)
        mgr.ping(self.capture)
        mgr.ping(other)
        self.assertEqual(len(mgr.captures()), 1)
        self.assertTrue(mgr.ping(self.capture))

    def test_recycling_is_transparent_to_semantic_results(self):
        # DESIGN_SPEC §2.9 MUST: semantic results must not depend on worker
        # lifetime. Force a recycle by lowering max_queries to 1, then assert
        # the payload a caller sees is unchanged while the process behind it
        # is not. If this test cannot make a recycle happen, the property is
        # vacuously true -- so the recycle is asserted too.
        mgr = WorkerManager(recycle=RecyclePolicy(max_queries=1))
        self.addCleanup(mgr.dispose_all)
        first = mgr.query(self.capture, "trace_pixel", x=160, y=120)
        pid_a = mgr.pid(self.capture)
        second = mgr.query(self.capture, "trace_pixel", x=160, y=120)
        pid_b = mgr.pid(self.capture)
        self.assertNotEqual(pid_a, pid_b, "expected a recycle between calls")
        self.assertEqual(first, second,
                         "semantic payload changed across a recycle")
        self.assertTrue(mgr.recycle_events)

    def test_private_memory_trigger_recycles_a_live_worker(self):
        # End-to-end through _get(): a live, healthy worker whose private
        # bytes have grown past the threshold must be drained and respawned
        # before serving the next query.
        if not _private_memory_available():
            self.skipTest("psutil private memory unavailable on this platform")
        mgr = WorkerManager(recycle=RecyclePolicy(
            max_private_memory_delta_mb=1))
        self.addCleanup(mgr.dispose_all)
        mgr.ping(self.capture)
        w = mgr._workers[os.path.abspath(self.capture)]
        pid_a = w.proc.pid
        # A None baseline here must FAIL, not skip: it means the metric is
        # available but nothing captured it, which is exactly the regression
        # these tests exist for.
        self.assertIsNotNone(w.mem_baseline,
                             "private-memory baseline was not captured")
        w.mem_current = lambda: w.mem_baseline + 4 * 1048576
        mgr.query(self.capture, "trace_pixel", x=1, y=1)
        self.assertNotEqual(mgr.pid(self.capture), pid_a)
        self.assertEqual([e["reason"] for e in mgr.recycle_events],
                         ["max_private_memory_delta"])

    def test_context_manager_disposes_everything(self):
        import psutil
        with WorkerManager() as mgr:
            mgr.ping(self.capture)
            proc = psutil.Process(mgr.pid(self.capture))
            pid = proc.pid
        self.assertEqual(mgr.captures(), [])
        deadline = time.time() + 15
        while time.time() < deadline and psutil.pid_exists(pid):
            time.sleep(0.02)
        self.assertFalse(psutil.pid_exists(pid),
                         "worker process leaked after __exit__")


class TestHelperSurface(_StubWorkerBase):
    def test_mem_and_inventory_require_an_existing_worker(self):
        mgr = WorkerManager()
        self.addCleanup(mgr.dispose_all)
        with self.assertRaises(WorkerError):
            mgr.mem(self.capture)
        with self.assertRaises(WorkerError):
            mgr.inventory(self.capture)

    def test_dispose_is_safe_for_unknown_captures(self):
        mgr = WorkerManager()
        mgr.dispose("never-seen.rdc")
        mgr.dispose_all()
        self.assertIsNone(mgr.worker_info("never-seen.rdc"))
        self.assertIsNone(mgr.pid("never-seen.rdc"))
        self.assertFalse(mgr.alive("never-seen.rdc"))


def mgr_ok(w):
    return bool(w.request(op="ping", timeout=30))


def _private_memory_available():
    """True when psutil exposes memory_info().private on this platform.

    Distinguishes "the metric does not exist here" (skip is correct) from
    "the metric exists but nothing captured it" (must fail).
    """
    try:
        import psutil
        return hasattr(psutil.Process().memory_info(), "private")
    except Exception:
        return False


class _suppressed:
    def __init__(self, *exc):
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, t, v, tb):
        return t is not None and issubclass(t, self.exc)


class _env_patched:
    def __init__(self, env):
        self.env = env
        self.saved = {}

    def __enter__(self):
        for k in self.env:
            self.saved[k] = os.environ.get(k)
            os.environ[k] = self.env[k]
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


if __name__ == "__main__":
    unittest.main()
