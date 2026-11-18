from ..errors import QueryError
from ..evidence import make as make_evidence
from ..model import ResourceRef
from ..query.events import build_action_index, flatten_actions
from .resource_access import (
    READ_USAGES,
    WRITE_USAGES,
    analysis_status,
    build_access_index,
    build_causal_graph,
    build_lifetime,
    build_versions,
)


def classify_usage(name):
    if not name:
        return "other"
    if name in WRITE_USAGES or name.endswith("_RWResource"):
        return "write"
    if name in READ_USAGES or name.endswith("_Constants"):
        return "read"
    if name.endswith("_Resource"):
        return "read"
    return "other"


def _entry(row, action_name, resource_id, capture):
    eid = int(row["eventId"])
    usage = str(row["usage"])
    return {
        "eventId": eid,
        "usage": usage,
        "kind": classify_usage(usage),
        "actionName": action_name,
        "evidence": [
            make_evidence(
                capture=capture,
                event_id=eid,
                resource_id=resource_id,
                operation=f"usage:{usage}",
                source="ReplayController.GetUsage",
            )
        ],
    }


def trace_resource(session, resource, context_eid=None, include_other=False):
    ref = ResourceRef.parse(resource)
    if not ref.id:
        raise QueryError("trace_resource requires a resource id")
    if context_eid is None:
        context_eid = session.last_draw_event_id()

    rows = session.usage(ref.id)
    actions_index = build_action_index(flatten_actions(session.root_actions()))

    writers = []
    readers = []
    other = []
    for row in rows:
        entry = _entry(row, actions_index.get(row["eventId"], {}).get("name", ""), ref.id,
                       session.path)
        if entry["kind"] == "write":
            writers.append(entry)
        elif entry["kind"] == "read":
            readers.append(entry)
        else:
            other.append(entry)

    query_evidence = make_evidence(
        capture=session.path,
        event_id=int(context_eid),
        resource_id=ref.id,
        operation="trace_resource",
        source="rdebug.analysis.resource_flow",
        data={"usageCount": len(rows)},
    )

    def last(entries):
        return entries[-1]["eventId"] if entries else None

    # R2.1: additive analysis over the same rows. The legacy keys above are
    # untouched; callers that only read writers/readers/summary see no change.
    accesses_all = build_access_index(rows, actions_index, ref.id, session.path)
    versions = build_versions(accesses_all, ref.id, session.path)
    causal = build_causal_graph(accesses_all, versions, ref.id, session.path)
    lifetime = build_lifetime(accesses_all)
    accesses = accesses_all if include_other else [
        a for a in accesses_all if a["legacyKind"] != "other"
    ]
    status = analysis_status(accesses_all, causal)

    return {
        "resource": {"id": ref.id, "name": ref.name},
        "contextEventId": int(context_eid),
        "writers": writers,
        "readers": readers,
        "other": other if include_other else [],
        "summary": {
            "usageCount": len(rows),
            "writerCount": len(writers),
            "readerCount": len(readers),
            "otherCount": len(other),
            "firstWriterEventId": writers[0]["eventId"] if writers else None,
            "lastWriterEventId": last(writers),
            "lastReaderEventId": last(readers),
            "unknownCount": sum(1 for a in accesses_all if a["status"] == "unknown"),
            "versionCount": len(versions),
        },
        "evidence": [query_evidence],
        "schemaVersion": "trace_resource/2",
        "analysisStatus": status,
        "accesses": accesses,
        "causal": causal,
        "lifetime": lifetime,
    }
