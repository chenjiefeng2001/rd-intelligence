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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from rdebug.errors import RDebugError
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
    return _STATE["capture"]


def dispose():
    """Symmetric with configure. Idempotent, and safe to call unconfigured."""
    global _workers, _STATE
    with _config_lock:
        mgr, _workers = _workers, None
        if mgr is not None:
            mgr.dispose_all()
        _STATE = {"capture": None, "baseline": None, "ready": False}


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


def api_trace(query):
    x, y = int(query["x"][0]), int(query["y"][0])
    return _run("trace_pixel", x=x, y=y,
                max_draws=int(query.get("max_draws", ["4"])[0]))


def api_diff(query):
    a = _parse_xy(query["a"][0])
    b = _parse_xy(query["b"][0])
    deep = query.get("deep", ["0"])[0] == "1"
    return _run("diff_pixel", a_x=a[0], a_y=a[1], b_x=b[0], b_y=b[1],
                include_shader_values=deep)


def api_resource(query):
    return _run("trace_resource", resource=query["id"][0])



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
    deep = query.get("deep", ["0"])[0] == "1"
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


_ROUTES = {
    "/api/info": api_info,
    "/api/ci": api_ci,
    "/api/trace": api_trace,
    "/api/diff": api_diff,
    "/api/resource": api_resource,
    "/api/explain": api_explain,
    "/api/stats": api_stats,
}


def route(path, query):
    from rdebug.observability import record, record_result, timed

    fn = _ROUTES.get(path)
    if fn is None:
        return 404, {"error": "unknown endpoint", "path": path}
    try:
        with timed("query", transport="ide", endpoint=path):
            payload = fn(query)
        if isinstance(payload, dict):
            record_result("ide", path, payload)
        return 200, payload
    except RDebugError as e:
        record("query_error", transport="ide", endpoint=path, error=str(e))
        return 400, {"error": str(e)}
    except (KeyError, IndexError, ValueError, TypeError) as e:
        # Malformed query parameters (a missing "x", a non-numeric
        # coordinate). DESIGN_SPEC §2.6 requires runtime errors to come back
        # as JSON rather than interrupting the session; without this the
        # exception escaped the handler and BaseHTTPRequestHandler dropped
        # the connection with no body at all.
        detail = f"{type(e).__name__}: {e}"
        record("query_error", transport="ide", endpoint=path, error=detail,
               kind="bad_request")
        return 400, {"error": "invalid request parameters: " + detail,
                     "endpoint": path}


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

    def log_message(self, fmt, *args):
        pass


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
