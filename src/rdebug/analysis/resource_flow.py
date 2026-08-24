from ..errors import QueryError
from ..evidence import make as make_evidence
from ..model import ResourceRef
from ..query.events import build_action_index, flatten_actions

WRITE_USAGES = {
    "StreamOut",
    "ColorTarget",
    "DepthStencilTarget",
    "Clear",
    "Discard",
    "GenMips",
    "Resolve",
    "ResolveDst",
    "CopyDst",
    "CPUWrite",
}

READ_USAGES = {
    "VertexBuffer",
    "IndexBuffer",
    "InputTarget",
    "Indirect",
    "CopySrc",
    "ResolveSrc",
}


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
        },
        "evidence": [query_evidence],
    }
