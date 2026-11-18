"""Measure the R2/R3 resource-access analysis (not a release gate).

Pure logic over synthetic usage rows: no replay, no GPU and no new corpus.
Reports p50/p95 over repeated runs, tracemalloc peak and the incremental
cost of the causal and lifetime layers compared with the access index alone.
"""

import argparse
import json
import statistics
import time
import tracemalloc

from rdebug.analysis.resource_access import (
    build_access_index,
    build_causal_graph,
    build_lifetime,
    build_versions,
    iter_writer_reader_edges,
)

USAGES = ("Clear", "ColorTarget", "PS_Resource", "CopyDst", "CopySrc",
          "CS_Resource", "DepthStencilTarget", "VS_Constants")


def make_rows(count):
    return [
        {"eventId": (i + 1) * 10,
         "usage": USAGES[i % len(USAGES)],
         "usageRaw": i % 16}
        for i in range(count)
    ]


def run_once(count):
    rows = make_rows(count)
    actions = {row["eventId"]: {"name": ""} for row in rows}
    start = time.perf_counter()
    accesses = build_access_index(rows, actions, "ResourceId::91", "bench.rdc")
    index_ms = (time.perf_counter() - start) * 1000.0

    start = time.perf_counter()
    versions = build_versions(accesses, "ResourceId::91", "bench.rdc")
    graph = build_causal_graph(accesses, versions, "ResourceId::91", "bench.rdc")
    lifetime = build_lifetime(accesses)
    analysis_ms = (time.perf_counter() - start) * 1000.0
    return {
        "indexMs": index_ms,
        "analysisMs": analysis_ms,
        "accessCount": len(accesses),
        "edgeCount": len(graph["edges"]),
        "versionCount": len(versions),
        "lifetimeStatus": lifetime["lifetimeStatus"],
    }


def run_stream_once(count, batch_size):
    """Process edges in batches without materializing the whole graph."""
    rows = make_rows(count)
    actions = {row["eventId"]: {"name": ""} for row in rows}
    start = time.perf_counter()
    accesses = build_access_index(rows, actions, "ResourceId::91", "bench.rdc")
    batch = []
    edge_count = 0
    checksum = 0
    for edge in iter_writer_reader_edges(accesses, lightweight=True):
        batch.append(edge)
        if len(batch) >= batch_size:
            for item in batch:
                checksum += item["fromEventId"] + item["toEventId"]
            edge_count += len(batch)
            batch = []
    for item in batch:
        checksum += item["fromEventId"] + item["toEventId"]
    edge_count += len(batch)
    return {"streamMs": (time.perf_counter() - start) * 1000.0,
            "edgeCount": edge_count, "checksum": checksum}


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def measure(count, repeats):
    samples = []
    tracemalloc.start()
    for _ in range(repeats):
        samples.append(run_once(count))
    _, full_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stream_samples = []
    tracemalloc.start()
    for _ in range(repeats):
        stream_samples.append(run_stream_once(count, batch_size=256))
    _, stream_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "size": count,
        "repeats": repeats,
        "indexMsP50": percentile([s["indexMs"] for s in samples], 0.5),
        "indexMsP95": percentile([s["indexMs"] for s in samples], 0.95),
        "analysisMsP50": percentile([s["analysisMs"] for s in samples], 0.5),
        "analysisMsP95": percentile([s["analysisMs"] for s in samples], 0.95),
        "analysisMsMedian": statistics.median([s["analysisMs"] for s in samples]),
        "peakTracedBytes": full_peak,
        "streamMsP50": percentile([s["streamMs"] for s in stream_samples], 0.5),
        "streamMsP95": percentile([s["streamMs"] for s in stream_samples], 0.95),
        "streamPeakBytes": stream_peak,
        "streamBatchSize": 256,
        "edgeCount": samples[-1]["edgeCount"],
        "streamEdgeCount": stream_samples[-1]["edgeCount"],
        "streamChecksum": stream_samples[-1]["checksum"],
        "versionCount": samples[-1]["versionCount"],
        "lifetimeStatus": samples[-1]["lifetimeStatus"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench-resource-access")
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--json", dest="json_path")
    args = ap.parse_args(argv)
    result = {
        "kind": "resource-access-analysis-benchmark",
        "note": "Pure analysis over synthetic rows; no replay, not a gate.",
        "sizes": [measure(n, args.repeats) for n in (8, 64, 512)],
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
