"""Minimal IDE prototype over Stable Core.

Proves the workflow: CI regression -> pixel -> firstDivergence ->
resource provenance -> evidence -> grounded AI prompt. No GPU viewer,
no analysis logic here — every fact comes from Semantic API v1.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from rdebug.analysis.pixel_diff import diff_pixel
from rdebug.analysis.pixel_trace import trace_pixel
from rdebug.analysis.resource_flow import trace_resource
from rdebug.ci import check as ci_check
from rdebug.errors import RDebugError
from rdebug.jsonutil import to_json
from rdebug.session_cache import SessionManager

_STATE = {"capture": None, "baseline": None}
_session_factory = None
_manager = None


def configure(capture, baseline=None, session_factory=None):
    global _STATE, _session_factory, _manager
    _STATE["capture"] = os.path.abspath(capture)
    _STATE["baseline"] = baseline
    _session_factory = session_factory

    def provider():
        if session_factory is not None:
            return session_factory
        from rdebug.adapter.core import CaptureSession

        return CaptureSession

    _manager = SessionManager(factory_provider=provider)


def _session():
    return _manager.use(_STATE["capture"])


def _parse_xy(text):
    try:
        xs, _, ys = (text or "").partition(",")
        return int(xs.strip()), int(ys.strip())
    except ValueError:
        raise RDebugError("pixel coordinates must be 'x,y' integers")


def api_info(query):
    return {"capture": _STATE["capture"], "ci": bool(_STATE["baseline"])}


def api_ci(query):
    if not _STATE["baseline"]:
        return {"enabled": False}
    with _session() as s:
        report = ci_check(s, _STATE["baseline"])
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
    with _session() as s:
        return trace_pixel(s, x, y, max_draws=int(query.get("max_draws", ["4"])[0]))


def api_diff(query):
    a = _parse_xy(query["a"][0])
    b = _parse_xy(query["b"][0])
    deep = query.get("deep", ["0"])[0] == "1"
    with _session() as s:
        return diff_pixel(s, a, b, include_shader_values=deep).to_dict()


def api_resource(query):
    rid = query["id"][0]
    with _session() as s:
        return trace_resource(s, rid)


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
    with _session() as s:
        payload = diff_pixel(s, a, b, include_shader_values=deep).to_dict()
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
    stats = _manager.stats() if _manager is not None else {"count": 0}
    return {"sessions": stats, "telemetry": bool(os.environ.get("RDEBUG_TELEMETRY"))}


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
    configure(args.capture, baseline=args.baseline)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"rdebug-ide serving {args.capture} at http://127.0.0.1:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
