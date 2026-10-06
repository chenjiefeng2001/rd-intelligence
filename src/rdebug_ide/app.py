"""Minimal IDE prototype over Stable Core.

Proves the workflow: CI regression -> pixel -> firstDivergence ->
resource provenance -> evidence -> grounded AI prompt. No GPU viewer,
no analysis logic here — every fact comes from Semantic API v1.

M1.4: the capture is served by a dedicated worker process, and the
ownership of that worker is explicit. Previously configure() rebound a
module-global SessionManager without disposing the old one, so a second
configure() left the previous capture's ReplayController alive and
invisible: the surface reported the new capture while a stale session was
still holding native state. configure() and dispose() are now a matched
pair, and a failed configure establishes nothing.
"""

import json
import os
import queue as queuelib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from rdebug.errors import QueryError, RDebugError
from rdebug.jsonutil import to_json
from rdebug.worker_manager import RecyclePolicy, WorkerManager

# The IDE owns at most one capture at a time, and says so in one place.
_STATE = {"capture": None, "baseline": None, "ready": False}
_workers = None
_config_lock = threading.RLock()


def configure(capture, baseline=None, workers=None):
    """Establish `capture` as the IDE's single current owner.

    Invariant 1 -- one current owner. Whatever was owned before is released
    BEFORE the new owner is claimed, so the registry can never hold a
    capture that the surface no longer reports.

    Invariant 2 -- symmetric termination. dispose() releases whatever
    configure() established, and a configure that fails establishes
    nothing: no owner, no registry entry, no half-initialised manager.

    The worker is established eagerly rather than on first request, so a
    bad capture or a missing renderdoc module fails here, at startup,
    instead of surfacing as a confusing error on the first click.

    `workers` exists for tests; production passes nothing.
    """
    global _workers, _STATE
    with _config_lock:
        dispose()
        target = os.path.abspath(capture)
        mgr = workers if workers is not None else WorkerManager(
            recycle=RecyclePolicy.production_default())
        try:
            if not mgr.ping(target):
                raise RDebugError(f"worker did not come up for {target}")
        except BaseException:
            # A failed configure must leave nothing behind, including the
            # manager it created: re-establishing ownership is the caller's
            # next move, not a leftover to discover later.
            try:
                mgr.dispose_all()
            except Exception:
                pass
            _workers = None
            _STATE = {"capture": None, "baseline": None, "ready": False}
            raise
        _workers = mgr
        _STATE = {"capture": target, "baseline": baseline, "ready": True}
    # Outside _config_lock so a slow stream cannot delay ownership transfer. The
    # failed-configure path above raises without publishing, because a capture
    # that never became the owner is not a state anyone should be told about.
    publish("configured", target)
    return _STATE["capture"]


def dispose():
    """Symmetric with configure. Idempotent, and safe to call unconfigured."""
    global _workers, _STATE
    with _config_lock:
        mgr, _workers = _workers, None
        if mgr is not None:
            mgr.dispose_all()
        _STATE = {"capture": None, "baseline": None, "ready": False}
        # Published outside _config_lock: publish() takes _state_lock, and the
        # two are disjoint, but keeping the notification out of the state
        # transition means a slow subscriber cannot delay the teardown.
        publish("disposed")


def _run(tool, **args):
    """Forward a query to the worker that owns the current capture.

    None arguments are dropped so the worker's own defaults apply, matching
    the MCP transport and the pre-migration in-process behaviour.
    """
    if not _STATE["ready"] or _workers is None:
        raise RDebugError("IDE capture is not configured; call configure()")
    return _workers.query(_STATE["capture"], tool,
                          **{k: v for k, v in args.items() if v is not None})


def _parse_xy(text):
    try:
        xs, _, ys = (text or "").partition(",")
        return int(xs.strip()), int(ys.strip())
    except ValueError:
        raise RDebugError("pixel coordinates must be 'x,y' integers")


def _bool_param(query, name, default=False):
    """Normalise a boolean query parameter from a real UI.

    A checkbox serialises as "true"/"false"; a hand-written URL uses "1"/"0".
    Accepting exactly those four is deliberate: widening it to "anything
    truthy" would let a typo silently select the other branch, which is the
    failure mode this replaces. Anything else is a bad request.
    """
    raw = query.get(name, None)
    if raw is None:
        return default
    value = raw[0].strip().lower()
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    raise RDebugError(
        f"{name} must be one of 1/0/true/false")


def _int_param(query, name, default):
    raw = query.get(name, None)
    if raw is None:
        return default
    try:
        value = int(raw[0])
    except (TypeError, ValueError):
        raise RDebugError(f"{name} must be an integer")
    if value < 1:
        raise RDebugError(f"{name} must be at least 1")
    return value


def api_info(query):
    return {"capture": _STATE["capture"], "ci": bool(_STATE["baseline"]),
            "ready": _STATE["ready"]}


def api_ci(query):
    if not _STATE["baseline"]:
        return {"enabled": False}
    # ci.check needs a session, so it runs in the worker like every other
    # capture-touching operation rather than opening a second, unmanaged
    # capture in this process.
    report = _run("ci_check", baseline=_STATE["baseline"])
    failures = []
    for f in report.get("failures", []):
        item = dict(f)
        if f["kind"].startswith("pixel_") and f["name"].startswith("px_"):
            x, y = (int(v) for v in f["name"][len("px_"):].split("_"))
            item["pixel"] = [x, y]
        pair_entry = _STATE["baseline"].get("pairs", {}).get(f["name"], {})
        if f["name"].startswith("pair_") and "a" in pair_entry:
            item["pair"] = {"a": pair_entry["a"], "b": pair_entry["b"]}
        failures.append(item)
    return {"enabled": True, "status": report["status"],
            "captureHashMatch": report["captureHashMatch"],
            "failures": failures}


def _eid_param(query):
    """Event context, carried through exactly or not at all.

    Only the format is decided here, so that a malformed value is a parameter
    error rather than a replay failure. Whether the event actually exists in
    this capture is left to the action tree in the query layer, which already
    classifies that as bad_request. No range is inferred from the number: the
    valid set is membership, not an interval, and a client that guessed an
    interval would reject legal events and accept illegal ones.
    """
    raw = (query.get("eid", None) or [""])[0].strip()
    if not raw:
        return None
    digits = raw[1:] if raw.startswith("-") else raw
    if not (digits.isascii() and digits.isdigit()):
        raise QueryError(f"eid must be an integer; got: {raw}", kind="bad_request")
    return int(raw)


def api_trace(query):
    x, y = int(query["x"][0]), int(query["y"][0])
    # The scope is explicit and defaults to the library's own default rather
    # than a silently tighter number. Truncation is not hidden here: the
    # semantic layer already reports summary.truncatedDraws, and the UI is
    # required to surface it.
    #
    # When the client says nothing about max_draws the argument is omitted
    # rather than filled in from a constant imported out of the analysis layer.
    # Importing one was a Rule 2.6 violation -- a transport may import the four
    # semantic entry points and nothing else -- and copying the number instead
    # would have been a second copy of a default that the semantic layer already
    # owns, free to drift. Letting the layer apply its own default is both the
    # legal answer and the one that cannot disagree.
    requested = _int_param(query, "max_draws", None)
    scope = {} if requested is None else {"max_draws": requested}
    # Only trace and resource accept an event context. diff_pixel has no
    # such parameter and always uses the library default event, so the UI
    # must not offer one here: sending it would be silently ignored.
    return _run("trace_pixel", x=x, y=y, eid=_eid_param(query), **scope)


def api_diff(query):
    a = _parse_xy(query["a"][0])
    b = _parse_xy(query["b"][0])
    deep = _bool_param(query, "deep")
    return _run("diff_pixel", a_x=a[0], a_y=a[1], b_x=b[0], b_y=b[1],
                include_shader_values=deep)


def api_resource(query):
    return _run("trace_resource", resource=query["id"][0], eid=_eid_param(query))



def _evidence_lines(diff_payload):
    lines = []
    first = diff_payload.get("firstDivergence") or {}

    def walk(node):
        if isinstance(node, dict):
            if "id" in node and "operation" in node:
                lines.append("- evidence {} : {} (eventId={}, resourceId={})".format(
                    node["id"], node.get("operation"),
                    node.get("eventId"), node.get("resourceId")))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(diff_payload.get("layers", []))
    walk(diff_payload.get("evidence", []))
    return lines, bool(first)


def explain_prompt(diff_payload, capture):
    first = diff_payload.get("firstDivergence") or {}
    statuses = {ly["layer"]: ly["status"] for ly in diff_payload.get("layers", [])}
    ev_lines, _ = _evidence_lines(diff_payload)
    return "\n".join(
        [
            "You are explaining a GPU pixel diff. Use ONLY the facts below.",
            "Anything not provable from these facts must be marked unknown.",
            "",
            f"capture: {capture}",
            "comparison: {}".format(diff_payload.get("comparison")),
            "firstDivergence layer: {}".format(first.get("layer")),
            f"layer statuses: {json.dumps(statuses)}",
            "good: {}".format(json.dumps(first.get("good", {}).get("value"))),
            "bad: {}".format(json.dumps(first.get("bad", {}).get("value"))),
            "evidence:",
        ]
        + ev_lines
        + [
            "",
            "Task: explain why the first divergence occurs at this layer,",
            "cite evidence ids for every factual claim, and list what would",
            "need to be queried next to prove or refute your hypothesis.",
        ]
    )


def api_explain(query):
    a = _parse_xy(query["a"][0])
    b = _parse_xy(query["b"][0])
    deep = _bool_param(query, "deep")
    payload = _run("diff_pixel", a_x=a[0], a_y=a[1], b_x=b[0], b_y=b[1],
                   include_shader_values=deep)
    return {
        "prompt": explain_prompt(payload, _STATE["capture"]),
        "evidenceIds": sorted(_collect_ids(payload)),
    }


def _collect_ids(node):
    out = set()
    if isinstance(node, dict):
        if "id" in node and "operation" in node:
            out.add(node["id"])
        for v in node.values():
            out |= _collect_ids(v)
    elif isinstance(node, list):
        for v in node:
            out |= _collect_ids(v)
    return out


def api_stats(query):
    # Re-sourced from the worker registry. Not a new telemetry foundation
    # (D5 is deferred): this is the same endpoint answering from the layer
    # that now owns the capture.
    mgr = _workers
    if mgr is None:
        sessions = {"count": 0, "paths": [], "recycles": 0}
    else:
        sessions = {
            "count": len(mgr.captures()),
            "paths": [os.path.basename(c) for c in mgr.captures()],
            "recycles": len(mgr.recycle_events),
            # Any worker that survived terminate()+kill() is reported, never
            # hidden: the registry cannot see one it no longer holds.
            "unkillable": mgr.unkillable(),
        }
    return {"sessions": sessions,
            "telemetry": bool(os.environ.get("RDEBUG_TELEMETRY"))}


def api_history(query):
    """Recent recorded observations.

    Read-only over the recorder's own file. It cannot change a query result,
    which is the property Rule 2.8 exists to protect: this is a view of what
    already happened, not an input to what happens next.
    """
    from rdebug import recorder

    def one(name, default=None):
        raw = query.get(name, [None])[0]
        return default if raw in (None, "") else raw

    def integer(name, default):
        raw = one(name)
        try:
            return int(raw) if raw is not None else default
        except (TypeError, ValueError):
            raise RDebugError(f"{name} must be an integer")

    limit = integer("limit", 50)
    since = one("since")
    until = one("until")
    for name, raw in (("since", since), ("until", until)):
        if raw is not None:
            try:
                float(raw)
            except (TypeError, ValueError):
                raise RDebugError(f"{name} must be a unix timestamp")
    failures_only = str(one("failures", "")).lower() in ("1", "true", "yes")

    return {
        "enabled": recorder.enabled(),
        "store": recorder.stats(),
        "observations": recorder.recent(
            limit=limit, endpoint=one("endpoint"), x=integer("x", None),
            y=integer("y", None), since=since, until=until,
            failures_only=failures_only,
            with_payload=str(one("payloads", "")).lower() in ("1", "true", "yes")),
    }


def api_history_summary(query):
    from rdebug import recorder

    def one(name):
        raw = query.get(name, [None])[0]
        return None if raw in (None, "") else raw

    if not recorder.enabled():
        # Not a zero. A summary of zeroes under `enabled: false` is something a
        # UI will happily render as "0 requests in this session", which is a
        # measurement that was never taken.
        return {"enabled": False, "store": None, "summary": None}
    return {"enabled": True, "store": recorder.stats(),
            "summary": recorder.aggregate(endpoint=one("endpoint"),
                                          since=one("since"),
                                          until=one("until"))}


_ROUTES = {
    "/api/info": api_info,
    "/api/ci": api_ci,
    "/api/trace": api_trace,
    "/api/diff": api_diff,
    "/api/resource": api_resource,
    "/api/explain": api_explain,
    "/api/stats": api_stats,
    "/api/history": api_history,
    "/api/history/summary": api_history_summary,
}

# GET endpoints that exist but do not belong to _ROUTES: /api/events never
# returns, and /api/state takes no query parameters. They are listed so the
# documentation control can require both editions to describe them.
AUX_GET_ROUTES = ("/api/events", "/api/state")


# --------------------------------------------------------------------------
# Change notification.
#
# A stream has to be able to say "nothing changed since you looked". That is
# only possible with a revision: a counter that increases on every observable
# change, so a client that reconnects with the revision it last saw can be told
# the difference between "you are current" and "you missed events 7 and 8".
# Without it, a dropped connection is indistinguishable from an idle one, and
# the failure mode is a client that looks healthy while showing stale data.
#
# This is additive. It observes the state that already exists; it does not
# change how any endpoint computes its answer, and no existing route consults
# it. An endpoint that never calls publish() is simply not streamable, which is
# reported rather than papered over.
#
# Bounded history, because an unbounded event log in a long-lived debug session
# is a memory leak with a friendly name. Once the buffer is full the oldest
# event is dropped, and a client asking for a revision that has already been
# evicted is told so explicitly instead of being handed a silently short gap.
# --------------------------------------------------------------------------

HISTORY_LIMIT = 256

_REVISION = 0
_HISTORY = []
_SUBSCRIBERS = []
_state_lock = threading.Lock()


def revision() -> int:
    with _state_lock:
        return _REVISION


def publish(kind, detail=None):
    """Record one state change and wake every subscriber."""
    global _REVISION
    with _state_lock:
        _REVISION += 1
        event = {"revision": _REVISION, "kind": kind, "detail": detail,
                 "state": snapshot_state()}
        _HISTORY.append(event)
        if len(_HISTORY) > HISTORY_LIMIT:
            del _HISTORY[:len(_HISTORY) - HISTORY_LIMIT]
        waiters = list(_SUBSCRIBERS)
    for queue in waiters:
        try:
            queue.put_nowait(event)
        except Exception:
            # A subscriber that cannot keep up is dropped rather than allowed to
            # block the publisher: a notification channel must never be able to
            # stall a query.
            pass
    return event


def snapshot_state() -> dict:
    """The observable surface, small and JSON-safe."""
    return {"ready": bool(_STATE.get("ready")),
            "capture": _STATE.get("capture"),
            "ci": _STATE.get("baseline") is not None,
            "revision": _REVISION}


def replay_since(last_revision):
    """Events after `last_revision`, or None if that revision was evicted.

    None is distinct from an empty list on purpose. An empty list means "you
    are current"; None means "I no longer have the events you missed" and the
    client has to fall back to a full snapshot rather than assume it is up to
    date.
    """
    with _state_lock:
        if last_revision is None:
            return []
        if last_revision > _REVISION:
            return None            # a revision from another server lifetime
        if last_revision == _REVISION:
            return []
        oldest = _HISTORY[0]["revision"] if _HISTORY else _REVISION + 1
        if last_revision < oldest - 1:
            return None            # the gap predates what is still buffered
        return [e for e in _HISTORY if e["revision"] > last_revision]


def subscribe():
    q = queuelib.Queue()
    with _state_lock:
        _SUBSCRIBERS.append(q)
    return q


def unsubscribe(q):
    with _state_lock:
        if q in _SUBSCRIBERS:
            _SUBSCRIBERS.remove(q)


def _remember(path, query, payload, status, latency_ms):
    """Record one served query, then announce it.

    Every failure is swallowed inside the recorder. A store that cannot be opened
    must not turn a query into an error, which is Rule 2.8 and the reason this is
    a separate function: it is the one place in the request path that knows about
    persistence, so there is exactly one place to audit.

    The event is published whether or not the row was stored. A subscriber that
    only heard about queries the store managed to keep would be told less than
    the truth, and "the log is unwritable" is exactly when someone watching a
    session most needs to know something is wrong.

    The history endpoints are skipped here, in one place, rather than at the call
    sites. Checking at the call sites missed the classified-error path, which made
    a rejected history read publish an event that made the panel read the history
    again: a failing read was enough to keep the loop running. One guard, next to
    the work it governs, cannot be bypassed by a new call site.
    """
    from rdebug import recorder

    if path.startswith("/api/history"):
        return

    error = payload.get("error") if isinstance(payload, dict) else None
    recorder.record("ide", path, ok=not error, status=status, error=error,
                    latency_ms=latency_ms, query=query,
                    summary=_shape(payload))
    publish("query", {"endpoint": path, "ok": not error, "status": status,
                      "latencyMs": latency_ms,
                      "recorded": recorder.dropped() == 0})


def _shape(payload):
    """Result-shape fields derived without mutating the payload."""
    from rdebug.observability import summarize_result

    return summarize_result(payload)


def route(path, query):
    from rdebug.observability import record, record_result, timed

    fn = _ROUTES.get(path)
    if fn is None:
        return 404, {"error": "unknown endpoint", "path": path}
    # Measured once and reused for both the JSONL telemetry and the store, so
    # the two records of the same query cannot disagree about how long it took.
    started = time.perf_counter()
    try:
        with timed("query", transport="ide", endpoint=path):
            payload = fn(query)
        elapsed = round((time.perf_counter() - started) * 1000.0, 2)
        if isinstance(payload, dict):
            # A classified error from the worker arrives as a result dict; it is
            # still a 400, and must not be logged as a good result.
            if payload.get("error") and payload.get("kind"):
                record("query_error", transport="ide", endpoint=path,
                       error=payload["error"], kind=payload["kind"])
                _remember(path, query, payload, 400, elapsed)
                return 400, dict(payload)
            record_result("ide", path, payload)
            # The history endpoints read the recorder; _remember skips them so
            # that looking at the history cannot grow it or announce itself.
            _remember(path, query, payload, 200, elapsed)
        return 200, payload
    except RDebugError as e:
        # A QueryError may already be classified by the query layer (an
        # illegal context_eid is a parameter problem, not a replay failure).
        # Reuse the existing bad_request distinction rather than adding one,
        # so a rejected parameter is not recorded as a runtime failure.
        kind = getattr(e, "kind", None)
        record("query_error", transport="ide", endpoint=path, error=str(e),
               **({"kind": kind} if kind else {}))
        body = {"error": str(e)}
        if kind:
            body["kind"] = kind
        _remember(path, query, body, 400,
                  round((time.perf_counter() - started) * 1000.0, 2))
        return 400, body
    except (KeyError, IndexError, ValueError, TypeError) as e:
        # Malformed query parameters (a missing "x", a non-numeric
        # coordinate). DESIGN_SPEC §2.6 requires runtime errors to come back
        # as JSON rather than interrupting the session; without this the
        # exception escaped the handler and BaseHTTPRequestHandler dropped
        # the connection with no body at all.
        detail = f"{type(e).__name__}: {e}"
        record("query_error", transport="ide", endpoint=path, error=detail,
               kind="bad_request")
        body = {"error": "invalid request parameters: " + detail,
                "endpoint": path}
        _remember(path, query, body, 400,
                  round((time.perf_counter() - started) * 1000.0, 2))
        return 400, body


_STATIC = os.path.join(os.path.dirname(__file__), "static")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = open(os.path.join(_STATIC, "index.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/ui" or parsed.path.startswith("/ui/"):
            # The React build is served alongside the frozen page rather than
            # replacing it. index.html is not a UI choice, it is the fixture the
            # frozen IDE controls cut their functions out of, so it stays exactly
            # where it is and reachable at exactly the same URL.
            self.serve_static(parsed.path)
            return
        if parsed.path in AUX_GET_ROUTES:
            # Not in _ROUTES because neither returns JSON from route(): the
            # stream stays open and the snapshot has no query parameters. They
            # are still endpoints, and naming them here is what lets the
            # documentation control see them -- while they lived only as
            # special cases in do_GET they were undocumented and unchecked.
            if parsed.path == "/api/state":
                # The snapshot a reconnecting client asks for when its revision
                # was evicted, and the first thing a client reads at all. A
                # stream can only carry changes; this carries the state they add
                # up to.
                body = to_json(snapshot_state()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            self.serve_events(parsed)
            return
        if parsed.path.startswith("/api/"):
            query = parse_qs(parsed.query)
            status, payload = route(parsed.path, query)
            body = to_json(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    # Server-sent events.
    #
    # `retry:` is sent up front rather than left to the browser default, because
    # the reconnect policy is a property of this server, not of whatever client
    # happens to connect. A named event carries a revision in both its `id:` and
    # its payload, so `Last-Event-ID` on reconnect is meaningful and a client can
    # also read the revision out of the body if it prefers.
    #
    # The heartbeat is a comment line, not an event: it exists to keep the
    # connection open through an idle period, and emitting it as a named event
    # would make every idle minute look like a state change to the client.
    HEARTBEAT_SECONDS = 15

    def serve_events(self, parsed):
        query = parse_qs(parsed.query)
        raw = query.get("lastEventId", [None])[0]
        header = self.headers.get("Last-Event-ID")
        last = header if header else (raw or None)
        try:
            last_revision = int(last) if last not in (None, "") else None
        except (TypeError, ValueError):
            last_revision = None

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = subscribe()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()

            backlog = replay_since(last_revision)
            if backlog is None:
                # The gap predates the buffer. Say so, with a resync instruction,
                # rather than resuming from a point that leaves a hole.
                state = snapshot_state()
                self.wfile.write(
                    ("event: resync\ndata: " + to_json(state, indent=None) + "\n\n")
                    .encode("utf-8"))
                self.wfile.flush()
            else:
                for event in backlog:
                    self.wfile.write(self._frame(event))
                if backlog:
                    self.wfile.flush()

            # A client that arrives current gets one event so it learns the
            # revision it is at. Silence would leave it unable to reconnect.
            if not backlog:
                self.wfile.write(self._frame({
                    "revision": revision(), "kind": "hello", "detail": None,
                    "state": snapshot_state()}))
                self.wfile.flush()

            while True:
                try:
                    event = q.get(timeout=self.HEARTBEAT_SECONDS)
                except queuelib.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(self._frame(event))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The client went away. That is the normal end of a stream, not an
            # error worth reporting, and the subscriber is removed below either
            # way.
            pass
        finally:
            unsubscribe(q)

    @staticmethod
    def _frame(event):
        # Compact, on one line. SSE only continues a data payload across lines
        # when every line repeats the `data:` prefix, and an unprefixed line is
        # discarded rather than appended -- so a pretty-printed payload arrives
        # as `{` and JSON.parse throws in the client. Compact sidesteps the rule
        # instead of relying on the reader to notice.
        return ("id: {revision}\nevent: {kind}\ndata: {data}\n\n".format(
            revision=event["revision"], kind=event["kind"],
            data=to_json(event, indent=None))).encode("utf-8")

    _UI_ROOT = os.path.join(_STATIC, "ui", "dist")
    _TYPES = {".html": "text/html; charset=utf-8",
              ".js": "text/javascript; charset=utf-8",
              ".css": "text/css; charset=utf-8",
              ".json": "application/json; charset=utf-8",
              ".svg": "image/svg+xml",
              ".ico": "image/x-icon"}

    def serve_static(self, path):
        """Serve the built React app.

        The resolved path is checked to be inside the dist root. A server that
        concatenates a request path onto a directory without that check will
        happily serve any file the process can read, and a debug tool is exactly
        the kind of program people point at a machine they do not fully trust.
        """
        rel = path[len("/ui"):].lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        target = os.path.normpath(os.path.join(self._UI_ROOT, rel))
        root = os.path.normpath(self._UI_ROOT)
        if not (target == root or target.startswith(root + os.sep)):
            self.send_response(403)
            self.end_headers()
            return
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        if not os.path.isfile(target):
            # The app shell, but only for paths that look like client-side
            # routes. Falling back for everything means a missing .js or .ico
            # is answered with 200 and a page of HTML, which turns "the bundle
            # did not load" into a parse error several layers away.
            if os.path.splitext(rel)[1]:
                self.send_response(404)
                self.end_headers()
                return
            target = os.path.join(root, "index.html")
            if not os.path.isfile(target):
                self.send_response(404)
                self.end_headers()
                return
        ext = os.path.splitext(target)[1]
        body = open(target, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type",
                         self._TYPES.get(ext, "application/octet-stream"))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass

    def handle_one_request(self):
        # A client that navigates away mid-stream aborts the socket, and the
        # default implementation lets that surface as a traceback from
        # socketserver even though a dropped subscriber is the normal end of a
        # stream. Serving it quietly is not hiding a fault: the alternative is a
        # stack trace for an event the server does not care about, which trains
        # readers to ignore tracebacks. Anything that is a real fault still
        # propagates, because only the disconnect errors are absorbed.
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True


def main():
    import argparse

    p = argparse.ArgumentParser(prog="rdebug-ide")
    p.add_argument("capture")
    p.add_argument("--baseline", default=None)
    p.add_argument("--port", type=int, default=8760)
    p.add_argument("--rd-path", default=None)
    args = p.parse_args()
    if args.rd_path:
        os.environ.setdefault("RDEBUG_RENDERDOC_PATH", args.rd_path)
    # Eager: a bad capture or a missing renderdoc module fails here, at
    # startup, instead of on the first click.
    configure(args.capture, baseline=args.baseline)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"rdebug-ide serving {args.capture} at http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    finally:
        # Symmetric with configure(): the worker process is torn down rather
        # than left holding an open capture when the server stops.
        dispose()


if __name__ == "__main__":
    main()
