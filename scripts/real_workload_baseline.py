"""R6.1: measure resource-access analysis on an authorized real capture.

This is a measurement tool, not a gate. It never changes a capture, a
manifest or a report schema. Metrics that cannot be derived from the
available evidence are recorded as NOT_ESTABLISHED rather than guessed.
"""

import argparse
import hashlib
import json
import time
import tracemalloc

from rdebug.adapter.core import CaptureSession
from rdebug.analysis.resource_flow import trace_resource


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure(capture, max_resources):
    started = time.perf_counter()
    with CaptureSession(capture) as session:
        resources = session.resources()
        selected = resources[:max_resources] if max_resources else resources
        tracemalloc.start()
        details = []
        for entry in selected:
            resource_started = time.perf_counter()
            result = trace_resource(session, entry["id"])
            elapsed = (time.perf_counter() - resource_started) * 1000.0
            causal = result["causal"]
            details.append({
                "resourceId": entry["id"],
                "resourceName": entry["name"],
                "accessCount": result["summary"]["usageCount"],
                "writerCount": result["summary"]["writerCount"],
                "readerCount": result["summary"]["readerCount"],
                "edgeCount": len(causal["edges"]),
                "overwriteCount": len(causal["overwrites"]),
                "versionCount": len(causal["versions"]),
                "inferredRelationCount": sum(
                    1 for e in causal["edges"] if e["supportLevel"] == "inferred_from_order"),
                "directRelationCount": sum(
                    1 for e in causal["edges"] if e["supportLevel"] == "direct"),
                "unknownRelationCount": sum(
                    1 for e in causal["edges"] if e["status"] == "unknown"),
                "unresolvedFieldCount": len(causal["unresolved"]),
                "lifetimeStatus": result["lifetime"]["lifetimeStatus"],
                "analysisStatus": result["analysisStatus"],
                "elapsedMs": elapsed,
            })
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    total_ms = (time.perf_counter() - started) * 1000.0
    return {
        "kind": "resource-access-real-workload",
        "capture": capture,
        "captureSha256": sha256_of(capture),
        "resourceCount": len(resources),
        "sampledResourceCount": len(selected),
        "capturedResourceIds": [e["id"] for e in resources],
        "totalMs": total_ms,
        "analysisPeakTracedBytes": peak,
        "perResource": details,
        "aggregates": {
            "accessCount": sum(d["accessCount"] for d in details),
            "writerCount": sum(d["writerCount"] for d in details),
            "readerCount": sum(d["readerCount"] for d in details),
            "edgeCount": sum(d["edgeCount"] for d in details),
            "inferredRelationCount": sum(d["inferredRelationCount"] for d in details),
            "directRelationCount": sum(d["directRelationCount"] for d in details),
            "unknownRelationCount": sum(d["unknownRelationCount"] for d in details),
        },
        "notEstablished": [
            "lifecycle_completeness: create/release events are not exposed by GetUsage",
            "content_flow: only event order is observable, not resource content propagation",
            "coverage: full vs partial writes are not exposed by GetUsage",
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="real-workload-baseline")
    ap.add_argument("capture")
    ap.add_argument("--max-resources", type=int, default=16)
    ap.add_argument("--json", dest="json_path")
    args = ap.parse_args(argv)
    result = measure(args.capture, args.max_resources)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
