import argparse
import json
import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rdebug.adapter.core import CaptureSession
from rdebug.analysis.pixel_trace import trace_pixel
from rdebug.analysis.shader_trace import debug_pixel


def timed(fn, *args, repeats=1, **kwargs):
    best = None
    result = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        dt = (time.perf_counter() - t0) * 1000.0
        best = dt if best is None else min(best, dt)
    return result, round(best, 2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("capture")
    p.add_argument("--x", type=int, default=320)
    p.add_argument("--y", type=int, default=240)
    p.add_argument("--repeats", type=int, default=3)
    args = p.parse_args()

    report = {
        "capture": os.path.abspath(args.capture),
        "captureSizeBytes": os.path.getsize(args.capture),
    }

    t0 = time.perf_counter()
    session = CaptureSession(args.capture)
    report["openMs"] = round((time.perf_counter() - t0) * 1000.0, 2)

    rows, ms = timed(session.action_rows, repeats=args.repeats)
    draws, ms_draws = timed(session.draw_rows, repeats=args.repeats)
    report["eventCount"] = len(rows)
    report["drawCount"] = len(draws)
    report["resourcesCount"] = len(session.resources())
    report["texturesCount"] = len(session.textures())
    report["buffersCount"] = len(session.buffers())
    report["flattenAllEventsMs"] = ms
    report["filterDrawsMs"] = ms_draws
    last = max(r["eventId"] for r in rows)

    pipe, ms_pipe = timed(session.pipeline, last, repeats=args.repeats)
    report["pipelineAtLastEventId"] = last
    report["pipelineSnapshotMs"] = ms_pipe

    tracemalloc.start()
    graph, ms_trace = timed(trace_pixel, session, args.x, args.y, repeats=args.repeats)
    dbg, ms_dbg = timed(debug_pixel, session, args.x, args.y, repeats=max(1, args.repeats - 1))
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    summary = graph["summary"]
    report["tracePixel"] = {
        "pixel": [args.x, args.y],
        "target": summary.get("target"),
        "modifications": summary["modificationCount"],
        "writeEvents": summary["totalWriteEvents"],
        "analyzedDraws": summary["analyzedDraws"],
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "latencyMsBest": ms_trace,
    }

    report["debugPixel"] = {
        "eventId": dbg["eventId"],
        "primitive": dbg.get("primitive"),
        "shader": {
            "entryPoint": dbg["shader"]["entryPoint"],
            "resource": dbg["shader"]["resource"],
            "debuggable": dbg["shader"]["debuggable"],
        },
        "instructionCount": dbg["stepCount"],
        "truncatedMaxSteps": dbg["truncated"],
        "debugStatus": "ok" if not dbg["truncated"] else "max_steps_truncated",
        "inputs": len(dbg["inputs"]),
        "latencyMsBest": ms_dbg,
    }

    report["pythonPeakAllocKbDuringAnalysis"] = peak_bytes // 1024

    session.close()
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
