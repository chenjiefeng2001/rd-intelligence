"""R6.4: compare full-graph-then-filter with pushed-down streaming query.

Pure logic, no replay, not a gate. Both paths must return the same
(from, to) relation set; only the amount of materialization differs.
"""

import argparse
import json
import statistics
import time

from rdebug.analysis.resource_access import (
    build_access_index,
    build_causal_graph,
    build_versions,
)
from rdebug.analysis.resource_query import query_relations_stream
from rdebug.jsonutil import to_json

USAGES = ("Clear", "ColorTarget", "PS_Resource", "CopyDst", "CopySrc",
          "CS_Resource", "DepthStencilTarget", "VS_Constants")


def make_rows(count):
    return [
        {"eventId": (i + 1) * 10, "usage": USAGES[i % len(USAGES)],
         "usageRaw": i % 16}
        for i in range(count)
    ]


def measure(count, repeats, fraction=0.5):
    rows = make_rows(count)
    actions = {row["eventId"]: {"name": ""} for row in rows}
    accesses = build_access_index(rows, actions, "ResourceId::91", "bench.rdc")
    versions = build_versions(accesses, "ResourceId::91", "bench.rdc")
    cutoff = rows[int(len(rows) * fraction)]["eventId"]
    full, stream = [], []
    full_edges = stream_edges = []
    for _ in range(repeats):
        started = time.perf_counter()
        graph = build_causal_graph(accesses, versions, "ResourceId::91", "bench.rdc")
        to_json(graph)
        full_edges = [e for e in graph["edges"] if e["toEventId"] <= cutoff]
        full.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        stream_edges = list(query_relations_stream(accesses, to_event_max=cutoff))
        stream.append((time.perf_counter() - started) * 1000.0)
    full_pairs = [(e["fromEventId"], e["toEventId"]) for e in full_edges]
    stream_pairs = [(e["fromEventId"], e["toEventId"]) for e in stream_edges]
    return {
        "size": count,
        "repeats": repeats,
        "toEventMax": cutoff,
        "fullPathMsP50": statistics.median(full),
        "pushedDownMsP50": statistics.median(stream),
        "fullMatchedEdgeCount": len(full_pairs),
        "streamedEdgeCount": len(stream_pairs),
        "sameRelationSet": full_pairs == stream_pairs,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench-query-pushdown")
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--json", dest="json_path")
    args = ap.parse_args(argv)
    result = {
        "kind": "query-pushdown-benchmark",
        "note": "Pure logic over synthetic rows; tracemalloc off; not a gate.",
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
