import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rdebug.adapter.core import CaptureSession
from rdebug.analysis.pixel_diff import diff_pixel


def instrument(session, counts, times):
    def wrap(name, fn):
        def inner(*args, **kwargs):
            counts[name] += 1
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                times[name].append(round((time.perf_counter() - t0) * 1000.0, 2))
        return inner

    session.pixel_history = wrap("pixel_history", session.pixel_history)
    session.usage = wrap("usage", session.usage)
    session.pipeline = wrap("pipeline", session.pipeline)
    session.root_actions = wrap("root_actions", session.root_actions)


def main():
    capture = sys.argv[1]
    out = sys.argv[2]
    report = {"capture": os.path.abspath(capture)}

    session = CaptureSession(capture)
    counts = Counter()
    times = {
        "pixel_history": [],
        "usage": [],
        "pipeline": [],
        "root_actions": [],
    }
    instrument(session, counts, times)

    t0 = time.perf_counter()
    result = diff_pixel(session, (320, 240), (10, 10)).to_dict()
    total_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    first = result["firstDivergence"]
    report["totalMs"] = total_ms
    report["callCounts"] = dict(counts)
    report["callTimesMs"] = {
        k: {"calls": len(v), "totalMs": round(sum(v), 2), "maxMs": max(v) if v else None}
        for k, v in times.items()
    }
    report["comparison"] = result["comparison"]
    report["firstDivergence"] = (
        {"layer": first["layer"], "path": first.get("path")} if first else None
    )
    report["layerStatuses"] = {ly["layer"]: ly["status"] for ly in result["layers"]}
    report["unknownLayers"] = [ly["layer"] for ly in result["layers"]
                               if ly["status"] == "unknown"]

    def count_evidence(node):
        n = 0
        if isinstance(node, dict):
            if "id" in node and "operation" in node:
                n += 1
            for v in node.values():
                n += count_evidence(v)
        elif isinstance(node, list):
            for v in node:
                n += count_evidence(v)
        return n

    report["evidenceCount"] = count_evidence(result["layers"]) + count_evidence(
        result["evidence"]
    )
    report["payloadBytes"] = len(json.dumps(result))

    t0 = time.perf_counter()
    result2 = diff_pixel(session, (320, 240), (10, 10)).to_dict()
    report["rerunMs"] = round((time.perf_counter() - t0) * 1000.0, 2)
    report["semanticallyStable"] = (
        result2["firstDivergence"] == result["firstDivergence"]
        and result2["comparison"] == result["comparison"]
    )
    report["historyCallsAfterRerun"] = counts["pixel_history"]

    session.close()
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
