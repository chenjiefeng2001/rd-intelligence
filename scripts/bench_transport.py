"""D6 evidence collection: did the process-isolation migration cost queries?

Answers exactly one question -- whether moving MCP/IDE from an in-process
SessionManager to a WorkerManager produced a measurable query performance
regression -- and nothing else. It is a measurement tool, not a gate: no
threshold is read, no threshold is compared, and its output must not be
used to turn the existing workload perf gate into a migration gate.

Runs against whatever tree PYTHONPATH points at, using only the transport
surface that is identical before and after the migration:

    server.trace_pixel(capture, x, y, max_draws=N)   -> JSON string
    app.configure(capture) / app.route(path, query)  -> (status, payload)

Because the surface is unchanged, the same script measures both trees, so
the before/after comparison cannot be confounded by the script itself.

Two phases, deliberately separate:

  --discover   find a covered pixel and a background pixel through the
               public API, and print them. Run once.
  --bench      measure with the coordinates handed in explicitly, so both
               trees query literally the same pixels rather than each
               rediscovering them.

Cold and warm are never mixed: the first query after the transport is
configured carries session/worker establishment and replay-runtime
initialisation, and is reported on its own. Mixing it into a warm p95
would manufacture a regression out of startup cost.
"""

import argparse
import json
import os
import statistics
import sys
import time


def _quiet():
    os.environ.setdefault("RDEBUG_TELEMETRY", os.devnull)


def _abs(path):
    return os.path.abspath(path)


def _mcp_query(capture, x, y, max_draws):
    from rdebug_mcp import server
    raw = server.trace_pixel(capture, x, y, max_draws=max_draws)
    return json.loads(raw)


def _ide_query(capture, x, y, max_draws):
    from rdebug_ide import app
    status, payload = app.route("/api/trace", {
        "x": [str(x)], "y": [str(y)], "max_draws": [str(max_draws)]})
    if status != 200:
        raise RuntimeError(f"IDE status {status}: {payload}")
    return payload


def _configure(transport, capture):
    """Establish the transport's session/worker, and return a release callable.

    Written against BOTH trees on purpose. Before the migration the MCP
    transport exposed `_MANAGER` (an in-process SessionManager) and the IDE
    exposed `_manager`; after it they expose `_WORKERS` and a module-level
    `dispose()`. If this only understood one tree, the before/after
    comparison would be measuring the script's assumptions rather than the
    migration.
    """
    if transport == "ide":
        from rdebug_ide import app
        app.configure(capture)

        def _release_ide():
            if hasattr(app, "dispose"):          # post-migration
                app.dispose()
            elif getattr(app, "_manager", None) is not None:  # pre-migration
                app._manager.dispose_all()
                app._manager = None
        return _release_ide

    from rdebug_mcp import server
    mgr = getattr(server, "_WORKERS", None) or getattr(server, "_MANAGER", None)
    if mgr is not None:
        mgr.dispose_all()

    def _release_mcp():
        current = (getattr(server, "_WORKERS", None)
                   or getattr(server, "_MANAGER", None))
        if current is not None:
            current.dispose_all()
    return _release_mcp


def _setup():
    sys.path.insert(0, os.environ.get("RDEBUG_SRC", "src"))


def _trace_is_used(payload):
    """A covered pixel: the trace found a fragment that wrote it."""
    try:
        return bool(payload["summary"]["modificationCount"])
    except (KeyError, TypeError):
        return False


def discover(capture, transport, max_scan=24):
    """Find a covered pixel and a background pixel, deterministically."""
    query = _mcp_query if transport == "mcp" else _ide_query
    release = _configure(transport, capture)
    try:
        first = query(capture, 1, 1, max_draws=4)
        edges = first.get("summary", {}).get("width", 0), \
            first.get("summary", {}).get("height", 0)
        # Fall back to a scan when the payload carries no geometry.
        w, h = (edges if all(edges) else (0, 0))
        covered = background = None
        candidates = [(x, y)
                      for x in range(2, 2 + max_scan)
                      for y in range(2, 2 + max_scan)]
        for x, y in candidates:
            p = query(capture, x, y, max_draws=4)
            if covered is None and _trace_is_used(p):
                covered = (x, y)
            if background is None and not _trace_is_used(p) and p.get("edges") is not None:
                background = (x, y)
            if covered and background:
                break
        if not covered:
            # Nothing in the scan is covered; use the target itself.
            covered = (1, 1)
        if not background:
            background = (1, 1)
        return {"covered": list(covered), "background": list(background),
                "geometry": [w, h]}
    finally:
        release()


def bench(capture, transport, covered, background, warm, max_draws, only=None):
    """Return cold and warm timings, kept apart.

    `only` restricts the run to a single measurement point. That exists
    because cold cost cannot be measured reliably when two points share a
    process: the first point pays process warm-up and the second inherits
    it, which produced a 3x difference between two points on the same
    capture in an earlier run. One point per process makes each figure
    self-contained.

    Establish time (configure / worker spawn) is timed separately from the
    first query, because the two moved to different places: pre-migration
    the cost sat in the first query, post-migration the IDE establishes
    its worker eagerly inside configure(). Reporting only "first query"
    would attribute the IDE's worker spawn to nothing at all.
    """
    query = _mcp_query if transport == "mcp" else _ide_query
    results = {}
    points = [("covered", tuple(covered)), ("background", tuple(background))]
    if only:
        points = [(p, c) for p, c in points if p == only]

    for label, (x, y) in points:
        # A fresh transport per measurement point, so the cold figure is the
        # cost of establishing the runtime and not a leftover from the
        # previous point.
        t_est = time.perf_counter()
        release = _configure(transport, capture)
        establish_ms = (time.perf_counter() - t_est) * 1000.0
        try:
            t0 = time.perf_counter()
            payload = query(capture, x, y, max_draws=max_draws)
            cold_ms = (time.perf_counter() - t0) * 1000.0
            if "error" in payload:
                raise RuntimeError(f"query failed: {payload['error']}")
            warm_ms = []
            for _ in range(warm):
                t1 = time.perf_counter()
                query(capture, x, y, max_draws=max_draws)
                warm_ms.append((time.perf_counter() - t1) * 1000.0)
        finally:
            release()
        warm_ms.sort()
        n = len(warm_ms)
        results[label] = {
            "establish_ms": round(establish_ms, 3),
            "cold_first_query_ms": round(cold_ms, 3),
            "establish_plus_first_query_ms": round(establish_ms + cold_ms, 3),
            "warm_n": n,
            "warm_p50_ms": round(statistics.median(warm_ms), 3) if n else None,
            "warm_p95_ms": (round(warm_ms[min(n - 1, int(0.95 * n))], 3)
                            if n else None),
            "warm_max_ms": round(warm_ms[-1], 3) if n else None,
            "warm_min_ms": round(warm_ms[0], 3) if n else None,
        }
    return results


def summarise(after, before):
    """Absolute and relative deltas, post minus pre."""
    out = {}
    for transport, rows in after.items():
        out[transport] = {}
        for point in ("covered", "background"):
            cur, ref = rows[point], before.get(transport, {}).get(point)
            if not ref:
                continue
            entry = {}
            for metric in ("cold_first_query_ms", "warm_p50_ms",
                           "warm_p95_ms", "warm_max_ms"):
                a, b = cur.get(metric), ref.get(metric)
                if a is None or b is None:
                    continue
                entry[metric] = {
                    "pre": b,
                    "post": a,
                    "abs_delta_ms": round(a - b, 3),
                    "rel_delta_pct": (round((a - b) / b * 100.0, 2)
                                      if b else None),
                }
            entry["warm_n"] = cur.get("warm_n")
            out[transport][point] = entry
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench_transport")
    ap.add_argument("--capture", required=True)
    ap.add_argument("--transport", choices=("mcp", "ide"), required=True)
    ap.add_argument("--mode", choices=("discover", "bench"),
                    default="bench")
    ap.add_argument("--covered", default="", help='"x,y" from --discover')
    ap.add_argument("--background", default="")
    ap.add_argument("--warm", type=int, default=40)
    ap.add_argument("--max-draws", type=int, default=4)
    ap.add_argument("--label", default="")
    ap.add_argument("--only", choices=("covered", "background"), default="",
                    help="measure one point per process; required for a "
                         "trustworthy cold figure")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    _quiet()
    _setup()
    capture = _abs(args.capture)

    if args.mode == "discover":
        found = discover(capture, args.transport)
        found["capture"] = capture
        print(json.dumps(found, indent=2))
        return 0

    def _xy(text):
        x, y = text.split(",")
        return [int(x), int(y)]

    data = {
        "label": args.label,
        "transport": args.transport,
        "capture": capture,
        "covered": _xy(args.covered),
        "background": _xy(args.background),
        "warm_n": args.warm,
        "max_draws": args.max_draws,
        "only": args.only,
        "rows": bench(capture, args.transport, _xy(args.covered),
                      _xy(args.background), args.warm, args.max_draws,
                      only=args.only or None),
    }
    text = json.dumps(data, indent=2)
    print(text)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
