"""R6.3: attribute the cost of resource-access analysis by stage.

Pure-logic profiling over synthetic rows: no replay, no new corpus, not a
gate. It separates grouping, indexing, candidate search, edge generation,
relation materialization, explanation, serialization and query filtering so
a later optimization is based on measured cost rather than assumption.
"""

import argparse
import bisect
import json
import statistics
import time

from rdebug.analysis.resource_access import (
    build_access_index,
    build_causal_graph,
    build_versions,
    group_accesses_by_resource,
    iter_writer_reader_edges,
)
from rdebug.analysis.resource_explain import explain_relations
from rdebug.analysis.resource_query import query_relations
from rdebug.jsonutil import to_json

USAGES = ("Clear", "ColorTarget", "PS_Resource", "CopyDst", "CopySrc",
          "CS_Resource", "DepthStencilTarget", "VS_Constants")


def make_rows(count):
    return [
        {"eventId": (i + 1) * 10,
         "usage": USAGES[i % len(USAGES)],
         "usageRaw": i % 16}
        for i in range(count)
    ]


def timed(fn):
    started = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - started) * 1000.0


def profile_once(count, explanation_sample=64):
    rows = make_rows(count)
    actions = {row["eventId"]: {"name": ""} for row in rows}
    accesses, index_ms = timed(
        lambda: build_access_index(rows, actions, "ResourceId::91", "bench.rdc"))
    groups, grouping_ms = timed(lambda: group_accesses_by_resource(accesses))

    def index_writers():
        prepared = []
        for entries in groups.values():
            writers = [a for a in entries
                       if a["legacyKind"] == "write" and a["eventId"] is not None]
            writers.sort(key=lambda a: a["eventId"])
            prepared.append([a["eventId"] for a in writers])
        return prepared

    writer_events, writer_index_ms = timed(index_writers)

    def search_candidates():
        total = 0
        for entries in groups.values():
            events = [a["eventId"] for a in entries
                      if a["legacyKind"] == "write" and a["eventId"] is not None]
            for reader in entries:
                if reader["legacyKind"] == "read" and reader["eventId"] is not None:
                    total += bisect.bisect_left(events, reader["eventId"])
        return total

    candidates, candidate_ms = timed(search_candidates)
    light_edges, light_ms = timed(
        lambda: list(iter_writer_reader_edges(accesses, lightweight=True)))
    versions, _ = timed(
        lambda: build_versions(accesses, "ResourceId::91", "bench.rdc"))
    graph, materialize_ms = timed(
        lambda: build_causal_graph(accesses, versions, "ResourceId::91", "bench.rdc"))
    sample = graph["edges"][:explanation_sample]
    _, explain_ms = timed(lambda: explain_relations(sample))
    _, serialize_ms = timed(lambda: to_json(graph))
    _, query_ms = timed(lambda: query_relations(
        {"causal": graph}, support_level="inferred_from_order"))
    return {
        "indexMs": index_ms,
        "groupingMs": grouping_ms,
        "writerIndexMs": writer_index_ms,
        "candidateSearchMs": candidate_ms,
        "edgeGenerationMs": light_ms,
        "materializationMs": materialize_ms,
        "explanationMs": explain_ms,
        "serializationMs": serialize_ms,
        "queryFilterMs": query_ms,
        "candidateCount": candidates,
        "lightEdgeCount": len(light_edges),
        "materializedEdgeCount": len(graph["edges"]),
    }


STAGES = ("indexMs", "groupingMs", "writerIndexMs", "candidateSearchMs",
          "edgeGenerationMs", "materializationMs", "explanationMs",
          "serializationMs", "queryFilterMs")


def summarize(count, repeats):
    samples = [profile_once(count) for _ in range(repeats)]
    return {
        "size": count,
        "repeats": repeats,
        "stagesMsP50": {
            stage: statistics.median([s[stage] for s in samples])
            for stage in STAGES
        },
        "candidateCount": samples[-1]["candidateCount"],
        "lightEdgeCount": samples[-1]["lightEdgeCount"],
        "materializedEdgeCount": samples[-1]["materializedEdgeCount"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="profile-resource-access")
    ap.add_argument("--repeats", type=int, default=15)
    ap.add_argument("--json", dest="json_path")
    args = ap.parse_args(argv)
    result = {
        "kind": "resource-access-stage-profile",
        "note": "Pure logic over synthetic rows; not a gate.",
        "sizes": [summarize(n, args.repeats) for n in (8, 64, 512)],
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
