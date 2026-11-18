"""Resource access index and causal relationships (R2.1).

Pure logic over the rows returned by ``CaptureSession.usage()``. It never
imports the RenderDoc adapter and never invents information the adapter did
not supply: ``GetUsage`` exposes an event id, a usage name and its raw enum
value -- it does not expose subresource, region or byte coverage. Those stay
explicitly unknown instead of being inferred from an empty observation.

Writer-to-reader relationships are ordered by event id and are therefore
marked ``inferred``: event order is observed, exclusive coverage is not.
"""

from ..evidence import make as make_evidence

_WRITE = {
    "StreamOut",
    "ColorTarget",
    "DepthStencilTarget",
    "Clear",
    "Discard",
    "GenMips",
    "CPUWrite",
}
_READ = {"VertexBuffer", "IndexBuffer", "InputTarget", "Indirect"}
_COPY = {"CopySrc", "CopyDst"}
_RESOLVE = {"Resolve", "ResolveSrc", "ResolveDst"}
_CLEAR = {"Clear", "Discard"}

# Public aliases: resource_flow.py re-exports these for backward compatibility.
# They must contain exactly the names the pre-v2 classify_usage() treated as
# write/read, including copy/resolve directions.
WRITE_USAGES = _WRITE | {"Resolve", "ResolveDst", "CopyDst"}
READ_USAGES = _READ | {"CopySrc", "ResolveSrc"}

_UNKNOWN_REASONS = {
    "subresource": "ReplayController.GetUsage does not expose mip/layer/slice",
    "region": "ReplayController.GetUsage does not expose a written region",
    "coverage": "ReplayController.GetUsage does not expose full vs partial coverage",
    "alias": "equal resource ids do not prove physical memory aliasing",
}


def classify(usage):
    """Return ``(access_type, legacy_kind)`` for a usage name.

    ``legacy_kind`` is deliberately identical to the pre-v2 ``classify_usage``
    mapping so existing callers and baselines keep their exact values.
    """
    if not usage:
        return "unknown", "other"
    name = str(usage)
    if name.endswith("_RWResource"):
        return "readwrite", "write"
    if name in _CLEAR:
        return "clear", "write"
    if name in _COPY:
        return "copy", "write" if name == "CopyDst" else "read"
    if name in _RESOLVE:
        return "resolve", "read" if name == "ResolveSrc" else "write"
    if name in _WRITE or name == "GenMips":
        return "write", "write"
    if name in _READ or name.endswith("_Constants") or name.endswith("_Resource"):
        return "read", "read"
    return "unknown", "other"


def classify_access(usage):
    return classify(usage)[0]


def legacy_kind(usage):
    return classify(usage)[1]


def _unresolved(reason_key, event_id, resource_id, capture):
    return {
        "field": reason_key,
        "reason": _UNKNOWN_REASONS[reason_key],
        "status": "unknown",
        "evidence": [
            make_evidence(
                capture=capture,
                event_id=event_id,
                resource_id=resource_id,
                operation=f"unresolved:{reason_key}",
                source="rdebug.analysis.resource_access",
                status="unknown",
            )
        ],
    }


def build_access_index(rows, actions_index, resource_id, capture):
    """Build an event-ordered access index from raw usage rows.

    A malformed row is kept as an explicit unknown entry. Silently dropping it
    would be the F12 class of defect: a failed lookup masquerading as no data.
    """
    indexed = []
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("eventId") is None or row.get("usage") is None:
            indexed.append(
                {
                    "eventId": None,
                    "position": position,
                    "usage": None,
                    "usageRaw": None,
                    "accessType": "unknown",
                    "legacyKind": "other",
                    "actionName": "",
                    "subresource": None,
                    "region": None,
                    "coverage": "unknown",
                    "status": "unknown",
                    "reason": "usage row missing eventId or usage",
                    "evidence": [
                        make_evidence(
                            capture=capture,
                            resource_id=resource_id,
                            operation="malformed_usage_row",
                            source="ReplayController.GetUsage",
                            status="unknown",
                        )
                    ],
                }
            )
            continue
        eid = int(row["eventId"])
        usage = str(row["usage"])
        access, kind = classify(usage)
        indexed.append(
            {
                "eventId": eid,
                "position": position,
                "usage": usage,
                "usageRaw": row.get("usageRaw"),
                "accessType": access,
                "legacyKind": kind,
                "actionName": actions_index.get(eid, {}).get("name", ""),
                "subresource": None,
                "region": None,
                "coverage": "unknown",
                "status": "observed" if access != "unknown" else "unknown",
                "reason": None if access != "unknown" else "unrecognised usage name",
                "evidence": [
                    make_evidence(
                        capture=capture,
                        event_id=eid,
                        resource_id=resource_id,
                        operation=f"access:{usage}",
                        source="ReplayController.GetUsage",
                        status="observed" if access != "unknown" else "unknown",
                    )
                ],
            }
        )
    # event order is a fact; equal event ids keep their original row order.
    indexed.sort(key=lambda item: (item["eventId"] is None,
                                   item["eventId"] if item["eventId"] is not None else 0,
                                   item["position"]))
    return indexed


def build_versions(accesses, resource_id, capture):
    """Number write events in observed order.

    A version here means "the Nth observed write event", not "the Nth complete
    resource contents": coverage is not exposed, so every version is marked
    inferred and its coverage is unknown.
    """
    versions = []
    number = 0
    for entry in accesses:
        if entry["legacyKind"] != "write":
            continue
        number += 1
        versions.append(
            {
                "version": number,
                "eventId": entry["eventId"],
                "accessType": entry["accessType"],
                "coverage": "unknown",
                "status": "inferred",
                "evidence": [ref for ref in entry["evidence"]],
            }
        )
    return versions


def build_causal_graph(accesses, versions, resource_id, capture):
    """Relate writers to readers by event order, never by guessed coverage."""
    writers = [a for a in accesses if a["legacyKind"] == "write"]
    readers = [a for a in accesses if a["legacyKind"] == "read"]
    edges = []
    for reader in readers:
        if reader["eventId"] is None:
            continue
        for writer in writers:
            if writer["eventId"] is None or writer["eventId"] >= reader["eventId"]:
                continue
            edges.append(
                {
                    "fromEventId": writer["eventId"],
                    "toEventId": reader["eventId"],
                    "kind": "writer_to_reader",
                    "accessType": reader["accessType"],
                    "status": "inferred",
                    "evidence": [dict(ref) for ref in writer["evidence"]],
                }
            )
    overwrites = []
    for previous, following in zip(writers, writers[1:]):
        if previous["eventId"] is None or following["eventId"] is None:
            continue
        overwrites.append(
            {
                "supersededEventId": previous["eventId"],
                "followingEventId": following["eventId"],
                "status": "unknown",
                "reason": _UNKNOWN_REASONS["coverage"],
            }
        )
    unresolved = [_unresolved(key, None, resource_id, capture)
                  for key in ("subresource", "region", "coverage", "alias")]
    return {
        "edges": edges,
        "overwrites": overwrites,
        "versions": versions,
        "unresolved": unresolved,
    }


def build_lifetime(accesses):
    writes = [a["eventId"] for a in accesses if a["legacyKind"] == "write"
              and a["eventId"] is not None]
    reads = [a["eventId"] for a in accesses if a["legacyKind"] == "read"
             and a["eventId"] is not None]
    return {
        "firstWriteEventId": writes[0] if writes else None,
        "lastWriteEventId": writes[-1] if writes else None,
        "lastReadEventId": reads[-1] if reads else None,
        "writeCount": len(writes),
        "readCount": len(reads),
        "creationEventId": None,
        "destructionEventId": None,
        "status": "partial",
        "reason": "creation/destruction events are not exposed by GetUsage",
    }


def analysis_status(accesses, causal):
    """A partial result must never be reported as complete."""
    if not accesses:
        return "unknown"
    if causal["unresolved"] or any(a["status"] == "unknown" for a in accesses):
        return "partial"
    return "complete"
