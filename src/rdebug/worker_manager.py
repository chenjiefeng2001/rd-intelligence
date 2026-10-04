"""WorkerManager: process-level capture ownership for transports.

Replaces the assumption "one process, many cached sessions" (broken: the
RenderDoc replay runtime is not safe with multiple live controllers in one
process -- W1-R1 findings F-1/F-2/F-3) with:

    one worker process = one replay runtime = one active capture

Registry maps capture path -> worker subprocess. Workers stay alive for
their capture's lifetime (open -> serve -> close), coexist as PROCESSES,
and never share native state. Stable Core is untouched; this module is
transport/runtime infrastructure, sibling to SessionManager.

Synchronous API by design; async transports wrap calls in to_thread."""

import collections
import json
import os
import queue
import subprocess
import sys
import threading
import time

from .errors import RDebugError


class WorkerError(RDebugError):
    """Worker/runtime failure.

    Subclasses RDebugError, not RuntimeError. Every transport discriminates
    on RDebugError to decide "this is an answer-shaped failure" versus "this
    escaped the handler":

        rdebug_mcp/server.py:54   except RDebugError -> {"error": ...} JSON
        rdebug_ide/app.py:199     except RDebugError -> HTTP 400 + body
        rdebug/cli.py:196         except RDebugError -> _fail(e), exit 2

    While this was a RuntimeError, a worker death or spawn failure bypassed
    all of them. In the IDE that is the F-19 failure mode exactly: the
    exception escapes route(), BaseHTTPRequestHandler drops the connection
    with no body, and the client cannot tell a crash from a rejected
    request. A separate lossy path existed as well -- workers.py:214-216
    converts an RDebugError into a JSON *payload* rather than raising, so
    MCP's handler never ran and the `query_error` telemetry event stopped
    firing without any signal.

    It is a direct RDebugError, deliberately not a QueryError or
    CaptureOpenError: those mean "the capture said no", this means "the
    process serving the capture is gone". Callers that distinguish those
    kinds of failure should keep doing so.

    `transient` marks the failures DESIGN_SPEC §2.9 requires to recover
    from with a bounded respawn+retry (the process died, the pipe broke, a
    restart raced an external kill). It is a structured flag rather than a
    substring match on the message so that a query-level error whose text
    merely happens to contain "dead" is not mistaken for a dead worker and
    turned into a full process recycle.
    """

    def __init__(self, message, transient=False):
        super().__init__(message)
        self.transient = transient


class RecyclePolicy:
    """Transparent worker recycling triggers (F-3a mitigation).

    The native replay runtime accumulates state per deep-replay query
    (rdebug-validation Phase 2B-2: ~230-500KB/query, never reclaimed).
    Any exceeded limit drains and respawns the worker BEFORE serving the
    next query; process boundaries return all native state. Limits are
    ANDed as independent triggers; None disables a trigger. Baselines:
    rss delta is measured against the fresh worker's post-open RSS."""

    def __init__(self, max_queries=None, max_private_memory_delta_mb=None,
                 max_lifetime_s=None):
        self.max_queries = max_queries
        self.max_private_memory_delta_mb = max_private_memory_delta_mb
        self.max_lifetime_s = max_lifetime_s

    @classmethod
    def production_default(cls):
        """Phase 2C frozen recommendation (recycle curve, see
        rdebug-validation/docs/W1-R1-PLAN.md): bounded degradation at
        ~4% overhead. These values are engineering defaults, NOT
        architectural constants (DESIGN_SPEC §2.9): per-workload tuning
        is expected and done via env overrides or explicit construction.

        Naming (DESIGN_SPEC §2.9): memory thresholds are
        private-memory-delta based (Windows commit charge); RSS /
        working set MUST NOT gate anything.

        Env overrides: RDEBUG_RECYCLE_MAX_QUERIES,
        RDEBUG_RECYCLE_MAX_PRIVATE_MEMORY_DELTA_MB,
        RDEBUG_RECYCLE_MAX_LIFETIME_S.
        """

        def _env(name, default, cast):
            raw = os.environ.get(name)
            return cast(raw) if raw else default

        return cls(
            max_queries=_env("RDEBUG_RECYCLE_MAX_QUERIES", 250, int),
            max_private_memory_delta_mb=_env(
                "RDEBUG_RECYCLE_MAX_PRIVATE_MEMORY_DELTA_MB", 128, float),
            max_lifetime_s=_env("RDEBUG_RECYCLE_MAX_LIFETIME_S",
                                1800, float))

    def active(self):
        return (self.max_queries is not None
                or self.max_private_memory_delta_mb is not None
                or self.max_lifetime_s is not None)


class _Worker:
    # Observability only: with stderr=DEVNULL (the historical behaviour) a
    # worker that died during startup left behind nothing but an exit code,
    # which is why N3 F-N3-4 could only be observed as "exited unexpectedly".
    # The buffer is a fixed-size ring so a long-lived worker cannot grow it
    # without bound. Nothing here changes worker semantics, lifecycle, or
    # retry policy - it only makes an existing failure explainable.
    STDERR_TAIL_LINES = 200
    STDERR_DRAIN_TIMEOUT_S = 0.5

    def __init__(self, capture, env):
        # Deliberately abspath, not the capture policy: this module is shared by
        # the CLI and by in-process callers, which are not crossing a privilege
        # boundary. The untrusted surface is the MCP tool boundary, and that is
        # where the policy is enforced (see rdebug.capture_policy).
        self.capture = os.path.abspath(capture)
        self.proc = None
        self._lock = threading.Lock()
        self._reader = None
        self._queue = None
        self._next_id = 1
        self.born = time.monotonic()
        self.queries_served = 0
        self.rss_baseline = None
        self.mem_baseline = None
        self._stderr_tail = collections.deque(maxlen=self.STDERR_TAIL_LINES)
        self._stderr_lock = threading.Lock()
        self._stderr_reader = None
        self._stderr_done = threading.Event()
        self._spawn(env)

    def _spawn(self, env):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "rdebug.workers",
             "--capture", self.capture],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            # Was DEVNULL. Must stay paired with the drain thread below:
            # an undrained PIPE would let a chatty worker block on a full
            # stderr buffer, which WOULD be a semantic change.
            stderr=subprocess.PIPE, text=True, bufsize=1,
            env=env, cwd=os.getcwd())
        self._queue = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._pump_stderr,
                                               daemon=True)
        self._stderr_reader.start()
        try:
            ready = self.request("ping", op="ping", timeout=120)
        except WorkerError:
            # Never leave a spawned process behind: a worker that failed the
            # startup round trip still holds an open capture handle and,
            # with it, a live replay runtime (DESIGN_SPEC §2.9). On Linux
            # an orphaned child is reaped into init; on Windows it lingers
            # holding commit charge until the session ends.
            self.kill()
            raise
        if not ready:
            self.kill()
            raise WorkerError(f"worker failed to start for {self.capture}")
        # Baseline for the private-memory-delta trigger is taken here, after
        # the worker's capture is open and the first round trip succeeded, so
        # it measures the FRESH worker's steady state rather than interpreter
        # start-up cost. Private bytes (Windows commit charge) rather than
        # RSS: working sets get trimmed under memory pressure, private tracks
        # the native state this process actually owns (DESIGN_SPEC §2.9).
        #
        # This must run on every spawn: a recycled worker needs a new
        # baseline or the next delta is measured across two native runtimes.
        self._capture_baseline()

    def _pump_stderr(self):
        """Bounded, non-blocking stderr drain into a ring buffer."""
        try:
            for line in self.proc.stderr:
                line = line.rstrip("\n")
                if line:
                    with self._stderr_lock:
                        self._stderr_tail.append(line)
        except Exception as e:
            # A dead drain thread means the ring stops filling AND the pipe
            # is never drained, so every later death would report
            # stderr_tail=<empty> -- re-creating the "only observable as
            # exited unexpectedly" blind spot this buffer exists to remove.
            # Record the failure in the buffer instead of losing it.
            with self._stderr_lock:
                self._stderr_tail.append(
                    f"<stderr drain thread failed: {type(e).__name__}: {e}>")
        finally:
            self._stderr_done.set()

    def stderr_tail(self):
        """Last STDERR_TAIL_LINES stderr lines. Diagnostic only.

        Never used as a gate, threshold, or retry input.
        """
        with self._stderr_lock:
            return list(self._stderr_tail)

    def _death_message(self, what):
        """Exit code + bounded stderr tail for a worker-death error."""
        rc = self.proc.poll() if self.proc else "?"
        if self._stderr_reader is not None:
            # The stderr pipe usually closes a hair after stdout; give the
            # drain a bounded moment so the tail is not truncated.
            self._stderr_reader.join(timeout=self.STDERR_DRAIN_TIMEOUT_S)
        msg = f"{what} (rc={rc}) for {self.capture}"
        tail = self.stderr_tail()
        if tail:
            msg += " stderr_tail=" + " | ".join(tail[-8:])
        else:
            msg += " stderr_tail=<empty>"
        return msg

    def _capture_baseline(self):
        """Snapshot the private-memory baseline this worker's delta is
        measured against. Called once per successful spawn."""
        mem = self.private_bytes()
        if mem is None:
            # psutil missing, or a platform whose memory_info() has no
            # 'private' field (non-Windows). Left None on purpose:
            # _recycle_reason() treats a missing baseline as "trigger not
            # evaluable" rather than guessing, so the query-count and
            # lifetime triggers still work. worker_info() surfaces
            # metric="unavailable" so the gap is observable instead of
            # silently degrading to an RSS gate (forbidden, §2.9).
            self.mem_baseline = None
            self.rss_baseline = None
            return
        self.mem_baseline = mem
        self.rss_baseline = mem

    def _pump(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line:
                try:
                    self._queue.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self._queue.put(None)

    def request(self, tool=None, args=None, op="call", timeout=600):
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                raise WorkerError(self._death_message("worker dead"),
                                  transient=True)
            rid = self._next_id
            self._next_id += 1
            req = {"id": rid, "op": op}
            if op == "call":
                req["tool"] = tool
                req["args"] = args or {}
                self.queries_served += 1
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                # Death detected later than alive()'s poll(): normalize
                # to the standard dead-worker error so callers (and
                # WorkerManager.query's forced-respawn retry) treat it
                # identically.
                raise WorkerError(
                    self._death_message("worker pipe broken (dead)"),
                    transient=True) from None

            deadline = time.time() + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self.kill()
                    raise WorkerError(
                        f"worker timeout ({timeout}s) on "
                        f"{self.capture}/{tool or op}")
                try:
                    msg = self._queue.get(timeout=min(remaining, 5))
                except queue.Empty:
                    continue
                if msg is None:
                    raise WorkerError(
                        self._death_message("worker exited unexpectedly"),
                        transient=True)
                if msg.get("id") != rid:
                    continue
                if not msg.get("ok"):
                    raise WorkerError(str(msg.get("error")))
                return msg.get("result")

    def rss_bytes(self):
        """working_set_observation: diagnostic only (DESIGN_SPEC §2.9).
        MUST NOT be used as gate/threshold input."""
        try:
            import psutil
            return psutil.Process(self.proc.pid).memory_info().rss
        except Exception:
            return None

    def private_bytes(self):
        try:
            import psutil
            return psutil.Process(self.proc.pid).memory_info().private
        except Exception:
            return None

    def mem_current(self):
        """Private bytes, or None when that metric cannot be read.

        No RSS fallback, deliberately. This value is fed to the
        private-memory-delta gate, and the baseline it is compared against
        is always private bytes. A fallback here would compare RSS against
        a private-bytes baseline -- different units, and working sets are
        trimmed under memory pressure (baseline drift up to -35MB was
        measured), so the trigger would either silently disable itself or
        fire spuriously. Returning None leaves the trigger unevaluable,
        which _recycle_reason() handles and worker_info() reports as
        memory_metric="unavailable". DESIGN_SPEC §2.9 forbids RSS as a
        gate input; the diagnostic-only reading stays in rss_bytes().
        """
        return self.private_bytes()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def kill(self):
        """Terminate the worker, escalating until it is actually gone.

        Returns True when the process is confirmed reaped. A failed kill is
        not the same as a successful one: the worker would keep an open
        .rdc handle and a live replay runtime (§2.9) while the registry
        believes it is disposed. terminate() being ignored is rare but
        real, so fall through to kill() and then report honestly rather
        than swallowing the evidence.
        """
        if self.proc is None:
            return True
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.close()
                except Exception:
                    pass
                try:
                    self.proc.terminate()
                except Exception:
                    pass
            try:
                self.proc.wait(timeout=10)
            except Exception:
                pass
            if self.proc.poll() is None:
                # terminate() was ignored or too slow: escalate.
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=10)
                except Exception:
                    pass
        finally:
            # Close every pipe. The stdout/stderr readers are daemon threads
            # blocked on read(); once the process is reaped they see EOF, but
            # the handles themselves are only released here. Without this a
            # long-lived transport leaks one handle set per recycle.
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:
                    if stream is not None and not stream.closed:
                        stream.close()
                except Exception:
                    pass
        return not self.alive()

    def dispose(self):
        """Ask the worker to exit, then kill it. True when confirmed gone."""
        if self.proc is None:
            return True
        try:
            with self._lock:
                if self.proc.poll() is None:
                    self.proc.stdin.write(json.dumps(
                        {"id": self._next_id, "op": "exit"}) + "\n")
                    self.proc.stdin.flush()
        except Exception:
            pass
        return self.kill()


class WorkerManager:
    """capture -> worker process registry. Context-manager aware.

    recycle: optional RecyclePolicy; when set, _get() drains and respawns
    a worker before its next query once any trigger fires. Recycling is
    transparent to callers (same capture key, fresh native runtime)."""

    def __init__(self, max_workers=None, recycle=None):
        self.max_workers = max_workers
        self.recycle = recycle
        self.recycle_events = []
        self._workers = {}

    def _env(self):
        import rdebug
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(
            rdebug.__file__)))
        env = dict(os.environ)
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def _recycle_reason(self, w):
        p = self.recycle
        if p is None or not p.active():
            return None
        if (p.max_queries is not None
                and w.queries_served >= p.max_queries):
            return "max_queries"
        if (p.max_lifetime_s is not None
                and time.monotonic() - w.born >= p.max_lifetime_s):
            return "max_lifetime"
        if p.max_private_memory_delta_mb is not None:
            cur = w.mem_current()
            if (cur is not None and w.mem_baseline is not None
                    and cur - w.mem_baseline
                    >= p.max_private_memory_delta_mb * 1048576):
                return "max_private_memory_delta"
        return None

    def _get(self, capture) -> _Worker:
        key = os.path.abspath(capture)
        w = self._workers.get(key)
        reason = None
        if w is not None:
            if not w.alive():
                # Crash / OOM / driver reset == forced recycle
                # (DESIGN_SPEC §2.9): next query transparently respawns.
                reason = "worker_died"
            else:
                reason = self._recycle_reason(w)
        if reason is not None:
            event = {
                "capture": os.path.basename(key),
                "reason": reason,
                "queries_served": w.queries_served,
                # DESIGN_SPEC §2.9 naming MUST: private-memory semantics in
                # the field name. "unavailable" (not 0) when no baseline was
                # captured, so a missing metric is never read as a real one.
                "private_memory_baseline_mb": (
                    round(w.mem_baseline / 1048576, 1)
                    if w.mem_baseline is not None else "unavailable"),
                "private_memory_last_mb": (
                    round((w.mem_current() or 0) / 1048576, 1)
                    if w.mem_current() is not None else "unavailable"),
                "lifetime_s": round(time.monotonic() - w.born, 1),
            }
            self.dispose(key)
            self.recycle_events.append(event)
            w = None
        if w is None:
            if (self.max_workers is not None
                    and len(self._workers) >= self.max_workers):
                oldest = next(iter(self._workers))
                self.dispose(oldest)
            attempts = 3 if reason == "worker_died" else 1
            # A freshly respawned worker can die once during native
            # startup right after its predecessor was killed externally
            # (observed ~once per few hundred forced kills). Recovery
            # must be deterministic (DESIGN_SPEC §2.9), hence bounded
            # retries for crash-triggered respawns only.
            for i in range(attempts):
                try:
                    w = _Worker(key, self._env())
                    break
                except WorkerError:
                    if i == attempts - 1:
                        raise
                    time.sleep(0.5 * (i + 1))
            self._workers[key] = w
        return w

    def query(self, capture, tool, timeout=600, **args):
        """Execute a Semantic API v1 tool in the capture's worker.
        Returns the parsed payload; structured query errors surface as
        {"error": ..., "tool": ...} dicts exactly like the MCP transport.

        The capture is always forwarded into the args the worker receives, so
        the worker's own bound-capture guard (workers.py) actually engages.
        It used to be absent, which made the guard pass vacuously: a
        transport that forgot to forward `capture` got no check at all, and
        §2.9's "one worker = one capture" was enforced only by the registry
        key and never re-verified inside the worker. This is a fix to an
        existing guard, not a new correctness mechanism -- the guard was
        already written and already mandatory.

        If the worker died between health checks (pipe write fails), one
        forced dispose+respawn retry is made -- crash recovery must be
        deterministic (DESIGN_SPEC §2.9)."""

        key = os.path.abspath(capture)
        args.setdefault("capture", key)
        try:
            result = self._get(capture).request(tool, args,
                                                 timeout=timeout)
        except WorkerError as e:
            if not e.transient:
                raise
            event = {
                "capture": os.path.basename(key),
                "reason": "worker_died",
                "queries_served": None,
                "note": "detected at query-time pipe failure",
            }
            self.dispose(key)
            self.recycle_events.append(event)
            result = self._get(capture).request(tool, args,
                                                 timeout=timeout)
        payload = json.loads(result)
        return payload

    def identity(self, capture, timeout=60):
        """READ-ONLY observation of who serves `capture`. Not a Contract.

        Diagnostic only: it is not an input to health, recycle or any gate,
        and no transport depends on it to work. Exists so the migration
        acceptance checks can read a fact instead of inferring one from logs
        or object addresses.

        Note what it does and does not prove. worker_pid is a real,
        verifiable process identity, so distinct captures having distinct
        worker_pids is genuine *process* isolation. It is NOT runtime
        isolation: RenderDoc exposes no identity for the replay runtime or a
        ReplayController, so those fields come back "unobservable" with a
        reason rather than an approximation. Do not read a PID difference as
        a runtime-level observation.
        """
        key = os.path.abspath(capture)
        w = self._workers.get(key)
        if w is None:
            raise WorkerError(f"no worker for {key}")
        return json.loads(w.request(op="identity", timeout=timeout))

    def ping(self, capture, timeout=60):
        return bool(self._get(capture).request(op="ping", timeout=timeout))

    def rss(self, capture):
        """working_set_observation: diagnostic only (DESIGN_SPEC §2.9)."""
        key = os.path.abspath(capture)
        w = self._workers.get(key)
        return w.rss_bytes() if w else None

    def pid(self, capture):
        key = os.path.abspath(capture)
        w = self._workers.get(key)
        return w.proc.pid if w else None

    def mem(self, capture, timeout=300, gc=False, snapshot=False, top=8):
        """F-3a instrumentation: Python-layer memory view from the worker.
        Requires RDEBUG_WORKER_TRACEMALLOC=1 for tracemalloc fields; the
        object census works regardless. Worker must already exist."""

        key = os.path.abspath(capture)
        w = self._workers.get(key)
        if w is None:
            raise WorkerError(f"no worker for {key}")
        result = w.request(op="mem",
                           args={"gc": gc, "snapshot": snapshot,
                                 "top": top},
                           timeout=timeout)
        return json.loads(result)

    def inventory(self, capture, timeout=600):
        """Structural metadata (texture dims/ids, event count) via the
        worker's inventory op. Legal-arg-space only, no semantic values
        (W2 blinding, docs/W2-PROTOCOL.md §3)."""

        key = os.path.abspath(capture)
        w = self._workers.get(key)
        if w is None:
            raise WorkerError(f"no worker for {key}")
        return json.loads(w.request(op="inventory", timeout=timeout))

    def alive(self, capture):
        key = os.path.abspath(capture)
        w = self._workers.get(key)
        return bool(w and w.alive())

    def worker_info(self, capture):
        """Generation observability: pid, queries served, memory baseline.

        Field naming follows DESIGN_SPEC §2.9: the baseline is reported as
        `private_memory_baseline_bytes` and never as an "rss" field, because
        it holds private bytes (Windows commit charge) whenever that metric
        is available. `memory_metric` states which one was actually read;
        "unavailable" means the private-memory-delta trigger cannot be
        evaluated for this worker (psutil absent, or a platform without
        memory_info().private).
        """
        key = os.path.abspath(capture)
        w = self._workers.get(key)
        if w is None:
            return None
        metric = ("private" if w.private_bytes() is not None
                  else "unavailable")
        return {"pid": w.proc.pid,
                "queries_served": w.queries_served,
                "private_memory_baseline_bytes": w.mem_baseline,
                "memory_metric": metric,
                "age_s": round(time.monotonic() - w.born, 1)}

    def private(self, capture):
        key = os.path.abspath(capture)
        w = self._workers.get(key)
        return w.private_bytes() if w else None

    def dispose(self, capture):
        key = os.path.abspath(capture)
        w = self._workers.pop(key, None)
        if w is not None and not w.dispose():
            # The registry no longer knows about this worker, so a survivor
            # would be invisible from here on while still holding the
            # capture. Record it rather than pretending the dispose worked.
            self.recycle_events.append({
                "capture": os.path.basename(key),
                "reason": "dispose_failed",
                "pid": w.proc.pid if w.proc else None,
                "note": "worker survived terminate() and kill(); the replay "
                        "runtime may still be live in that process",
            })

    def dispose_all(self):
        for key in list(self._workers):
            self.dispose(key)

    def unkillable(self):
        """Workers that could not be confirmed dead, most recent first."""
        return [e for e in self.recycle_events
                if e.get("reason") == "dispose_failed"]

    def captures(self):
        return list(self._workers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.dispose_all()
        return False
