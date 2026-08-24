import argparse
import json
import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rdebug.adapter.core import CaptureSession
from rdebug.analysis.pixel_trace import trace_pixel
from rdebug.analysis.resource_flow import trace_resource
from rdebug.analysis.shader_trace import debug_pixel


class Bench:
    def __init__(self, repeats):
        self.repeats = max(1, repeats)
        self.report = {}

    def run(self, label, fn, *args, **kwargs):
        times = []
        result = None
        for _ in range(self.repeats):
            t0 = time.perf_counter()
            result = fn(*args, **kwargs)
            times.append(round((time.perf_counter() - t0) * 1000.0, 2))
        entry = {"coldMs": times[0], "warmMsBest": min(times[1:]) if len(times) > 1 else None,
                 "warmMsAll": times[1:]}
        self.report[label] = entry
        return result

    def once(self, label, fn, *args, **kwargs):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        self.report[label] = round((time.perf_counter() - t0) * 1000.0, 2)
        return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("capture")
    p.add_argument("--x", type=int, default=320)
    p.add_argument("--y", type=int, default=240)
    p.add_argument("--repeats", type=int, default=4)
    p.add_argument("--max-draws", type=int, default=16)
    args = p.parse_args()

    bench = Bench(args.repeats)
    report = bench.report
    report["_meta"] = {
        "capture": os.path.abspath(args.capture),
        "captureSizeBytes": os.path.getsize(args.capture),
        "repeats": args.repeats,
        "pixel": [args.x, args.y],
    }

    session = bench.once("openSession", CaptureSession, args.capture)

    rows = bench.run("flattenAllEvents", session.action_rows)
    report["_capture"] = {
        "eventCount": len(rows),
        "drawCount": len(session.draw_rows()),
        "resourceCount": len(session.resources()),
        "textureCount": len(session.textures()),
        "bufferCount": len(session.buffers()),
    }
    last_draw = session.last_draw_event_id()
    report["_capture"]["lastDrawEventId"] = last_draw

    pipe = bench.run("pipelineSnapshotAtLastDraw", session.pipeline, last_draw)
    target = (
        pipe["outputTargets"][0]["resource"] if pipe["outputTargets"] else None
    )
    if target is None and pipe["depthTarget"]:
        target = pipe["depthTarget"]["resource"]
    report["_capture"]["traceTarget"] = target

    hist = bench.run("pixelHistorySamePixel", session.pixel_history, target, args.x, args.y,
                     context_eid=last_draw)
    report["_pixelHistory"] = {"modifications": len(hist.modifications)}

    graph = bench.run("tracePixelSamePixel", trace_pixel, session, args.x, args.y,
                      max_draws=args.max_draws)
    report["_tracePixel"] = {
        "modifications": graph["summary"]["modificationCount"],
        "analyzedDraws": graph["summary"]["analyzedDraws"],
        "truncated": graph["summary"].get("truncatedDraws"),
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
    }

    distinct = []
    for i in range(3):
        dx = (i * 37) % 211
        dy = (i * 53) % 173
        t0 = time.perf_counter()
        trace_pixel(session, args.x - 100 + dx, args.y - 80 + dy, max_draws=args.max_draws)
        distinct.append(round((time.perf_counter() - t0) * 1000.0, 2))
    report["tracePixelDistinctPixelsMs"] = distinct

    dbg = bench.run("debugPixel", debug_pixel, session, args.x, args.y, max_steps=4096)
    report["_debugPixel"] = {
        "eventId": dbg["eventId"],
        "instructionCount": dbg["stepCount"],
        "truncated": dbg["truncated"],
    }

    flow = bench.run("traceResourceSameResource", trace_resource, session, target)
    report["_traceResource"] = {
        "usageCount": flow["summary"]["usageCount"],
        "writers": flow["summary"]["writerCount"],
        "readers": flow["summary"]["readerCount"],
    }

    t0 = time.perf_counter()
    shared_hist = session.pixel_history(target, args.x, args.y, context_eid=last_draw)
    shared_graph = trace_pixel(session, args.x, args.y, history=shared_hist,
                               max_draws=args.max_draws)
    shared_dbg = debug_pixel(session, args.x, args.y, history=shared_hist, max_steps=4096)
    shared_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    report["pixelPipelineSharedHistory"] = {
        "totalMs": shared_ms,
        "historyCallsExpected": 1,
        "graphNodes": len(shared_graph["nodes"]),
        "resourceFlows": sorted(shared_graph.get("resourceFlows", {}).keys()),
        "debugEventId": shared_dbg["eventId"],
    }

    separate_ms = (
        report["tracePixelSamePixel"]["coldMs"] + report["debugPixel"]["coldMs"]
    )
    report["pixelPipelineSharedHistory"]["separatePathMsEstimate"] = separate_ms

    tracemalloc.start()
    trace_pixel(session, args.x, args.y, max_draws=args.max_draws)
    debug_pixel(session, args.x, args.y, max_steps=4096)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report["pythonPeakAllocKbDuringAnalysis"] = peak // 1024

    session.close()
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
