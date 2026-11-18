"""Resource access index and causal relationships (R2.1).

Pure logic over the rows returned by ``CaptureSession.usage()``. It never
imports the RenderDoc adapter and never invents information the adapter did
not supply: ``GetUsage`` exposes an event id, a usage name and its raw enum
value -- it does not expose subresource, region or byte coverage. Those stay
explicitly unknown instead of being inferred from an empty observation.

Writer-to-reader relationships are ordered by event id and are therefore
marked ``inferred``: event order is observed, exclusive coverage is not.
"""

import bisect
import hashlib
import json

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

# R3.1: the explicit vocabulary of the resource-access relation model.
# These are finite, non-probabilistic enumerations. ``support_level`` in
# particular is never a confidence score: there is no statistical definition
# behind it, so only the three discrete levels below are admitted.
INFORMATION_STATUSES = ("observed", "inferred", "unknown")
SUPPORT_LEVELS = ("direct", "inferred_from_order", "unknown")
CAUSAL_TYPES = ("writer_to_reader", "overwrite", "resource_identity")
ACCESS_ROLES = ("read", "write", "readwrite", "other")


def check_information_status(value):
    if value not in INFORMATION_STATUSES:
        raise ValueError("invalid information status: " + str(value))
    return value


def relation(causal_type, from_event_id, to_event_id, evidence_refs,
             support_level, reason, observation_status):
    """Build one typed causal relation with its evidence boundary attached.

    ``observation_status`` describes what was actually observed (the two
    events and their order); ``support_level`` describes how far the relation
    goes beyond that observation. A relation built from GetUsage alone can
    never be ``direct`` -- that would claim content propagation the adapter
    does not expose.
    """
    if causal_type not in CAUSAL_TYPES:
        raise ValueError("invalid causal type: " + str(causal_type))
    if support_level not in SUPPORT_LEVELS:
        raise ValueError("invalid support level: " + str(support_level))
    check_information_status(observation_status)
    return {
        "causalType": causal_type,
        "fromEventId": from_event_id,
        "toEventId": to_event_id,
        "kind": causal_type,
        "evidenceRefs": list(evidence_refs or []),
        "supportLevel": support_level,
        "reason": reason,
        "observationStatus": observation_status,
        "status": "observed" if support_level == "direct" else (
            "inferred" if support_level == "inferred_from_order" else "unknown"
        ),
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
                    "resourceId": resource_id,
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
                "resourceId": resource_id,
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


def _evidence_refs(*entries):
    refs = []
    for entry in entries:
        for ev in entry.get("evidence", ()):
            refs.append({"id": ev["id"]})
    return refs


def _relation_id(resource, causal_type, from_event_id, to_event_id):
    canonical = json.dumps(
        [resource, causal_type, from_event_id, to_event_id],
        separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def group_accesses_by_resource(accesses):
    """Group accesses so no relation can cross a resource boundary."""
    groups = {}
    for entry in accesses:
        groups.setdefault(entry.get("resourceId") or "", []).append(entry)
    return groups


def iter_writer_reader_edges(accesses, stats=None, max_edges=None,
                             lightweight=False, resource_ids=None,
                             from_event_min=None, from_event_max=None,
                             to_event_min=None, to_event_max=None):
    """Yield writer-to-reader edges without materializing the whole graph.

    Writers are sorted once and located by bisect per reader, so unrelated
    writers are never rescanned. Duplicate (resource, writer, reader, type)
    tuples are dropped. Legitimate relations are never dropped on the
    analyzer's own initiative: truncation occurs only when the caller passes
    an explicit ``max_edges``, and every omitted edge is counted in ``stats``.
    """
    emitted = 0
    omitted = 0
    wanted = set(resource_ids) if resource_ids is not None else None
    for resource, entries in sorted(group_accesses_by_resource(accesses).items()):
        if wanted is not None and resource not in wanted:
            continue
        writers = [a for a in entries
                   if a["legacyKind"] == "write" and a["eventId"] is not None]
        readers = [a for a in entries
                   if a["legacyKind"] == "read" and a["eventId"] is not None]
        writers.sort(key=lambda a: a["eventId"])
        writer_events = [a["eventId"] for a in writers]
        writer_refs = [
            [{"id": ev["id"]} for ev in a.get("evidence", ())] for a in writers]
        writer_evidence = [
            [dict(ev) for ev in a.get("evidence", ())] for a in writers]
        seen = set()
        for reader in sorted(readers, key=lambda a: a["eventId"]):
            if to_event_min is not None and reader["eventId"] < to_event_min:
                continue
            if to_event_max is not None and reader["eventId"] > to_event_max:
                continue
            cutoff = bisect.bisect_left(writer_events, reader["eventId"])
            if from_event_max is not None:
                cutoff = min(cutoff, bisect.bisect_right(writer_events,
                                                         from_event_max))
            if from_event_min is not None:
                start = bisect.bisect_left(writer_events, from_event_min)
            else:
                start = 0
            for i in range(start, cutoff):
                writer = writers[i]
                key = (resource, writer["eventId"], reader["eventId"],
                       "writer_to_reader")
                if key in seen:
                    continue
                seen.add(key)
                if max_edges is not None and emitted >= max_edges:
                    omitted += 1
                    continue
                refs = list(writer_refs[i]) + [
                    {"id": ev["id"]} for ev in reader.get("evidence", ())]
                if lightweight:
                    # Compact projection for streaming/query paths: no full
                    # relation object, no copied evidence payloads.
                    emitted += 1
                    yield {
                        "fromEventId": writer["eventId"],
                        "toEventId": reader["eventId"],
                        "resourceId": resource,
                        "evidenceRefs": refs,
                        "supportLevel": "inferred_from_order",
                        "status": "inferred",
                    }
                    continue
                edge = relation(
                    "writer_to_reader",
                    writer["eventId"],
                    reader["eventId"],
                    refs,
                    "inferred_from_order",
                    "event order is observed; GetUsage exposes no content propagation",
                    "observed",
                )
                # R2 fields are kept verbatim for existing consumers.
                edge["accessType"] = reader["accessType"]
                edge["evidence"] = writer_evidence[i]
                edge["resourceId"] = resource
                # A stable relation id is generated on demand by the R5.2
                # explanation layer. Computing a hash per edge here made the
                # 512-row benchmark ~2.5x slower without changing any R2
                # consumer, so it is deliberately not materialized eagerly.
                emitted += 1
                yield edge
    if stats is not None:
        stats["emitted"] = emitted
        stats["omitted"] = omitted


def summarize_relations(accesses):
    """Count relations by bisect without constructing any relation object.

    For summary-only requests this avoids both object construction and JSON
    serialization of the full graph, which R6.3 identified as the dominant
    cost at large edge counts.
    """
    total = 0
    per_resource = {}
    for resource, entries in sorted(group_accesses_by_resource(accesses).items()):
        events = sorted(a["eventId"] for a in entries
                        if a["legacyKind"] == "write" and a["eventId"] is not None)
        count = 0
        for reader in entries:
            if reader["legacyKind"] == "read" and reader["eventId"] is not None:
                count += bisect.bisect_left(events, reader["eventId"])
        per_resource[resource] = count
        total += count
    return {
        "relationCount": total,
        "perResource": per_resource,
        "status": "inferred",
        "note": "counts only; no relation objects or evidence were materialized",
    }


def build_causal_graph(accesses, versions, resource_id, capture, max_edges=None):
    """Relate writers to readers by event order, never by guessed coverage.

    Every edge carries its own evidence boundary. Event ids and their order
    are observed; content propagation is not, so the strongest support is
    ``inferred_from_order`` -- never ``direct``.

    ``max_edges`` is an explicit, reported limit. A truncated graph is marked
    ``partial`` with an omitted-edge count; it is never presented as complete.
    """
    stats = {"emitted": 0, "omitted": 0}
    edges = list(iter_writer_reader_edges(accesses, stats=stats,
                                          max_edges=max_edges))
    truncated = stats["omitted"] > 0
    overwrites = []
    for resource, entries in sorted(group_accesses_by_resource(accesses).items()):
        writers = [a for a in entries
                   if a["legacyKind"] == "write" and a["eventId"] is not None]
        writers.sort(key=lambda a: a["eventId"])
        seen = set()
        for previous, following in zip(writers, writers[1:]):
            key = (resource, previous["eventId"], following["eventId"])
            if key in seen:
                continue
            seen.add(key)
            overwrite = relation(
                "overwrite",
                previous["eventId"],
                following["eventId"],
                _evidence_refs(previous, following),
                "unknown",
                _UNKNOWN_REASONS["coverage"],
                "unknown",
            )
            overwrite["supersededEventId"] = previous["eventId"]
            overwrite["followingEventId"] = following["eventId"]
            overwrite["resourceId"] = resource
            overwrites.append(overwrite)
    unresolved = [_unresolved(key, None, resource_id, capture)
                  for key in ("subresource", "region", "coverage", "alias")]
    return {
        "edges": edges,
        "overwrites": overwrites,
        "versions": versions,
        "unresolved": unresolved,
        "relationCount": len(edges) + len(overwrites),
        "truncated": truncated,
        "omittedEdgeCount": stats["omitted"],
        "edgeLimit": max_edges,
        "status": "partial" if truncated else "inferred",
    }


LIFETIME_STATUSES = ("observed", "partial", "unknown", "multiple", "order_conflict")


def build_lifetime(accesses, lifecycle_events=None):
    """Describe a resource lifetime without inventing missing endpoints.

    ``lifecycle_events`` is optional and carries explicit create/release
    observations when the caller has them. GetUsage itself does not, so the
    default result has unknown endpoints and an incomplete interval. Multiple
    create/release pairs are reported as separate instances rather than being
    merged by resource id -- equal ids do not prove one continuous lifetime.
    """
    writes = [a["eventId"] for a in accesses if a["legacyKind"] == "write"
              and a["eventId"] is not None]
    reads = [a["eventId"] for a in accesses if a["legacyKind"] == "read"
             and a["eventId"] is not None]
    first_access = min(writes + reads) if (writes or reads) else None
    last_access = max(writes + reads) if (writes or reads) else None

    events = sorted(lifecycle_events or (), key=lambda e: e.get("eventId", 0))
    creates = [e for e in events if e.get("kind") == "create"
               and e.get("eventId") is not None]
    releases = [e for e in events if e.get("kind") == "release"
                and e.get("eventId") is not None]
    create = creates[0] if creates else None
    release = next((r for r in reversed(releases)
                    if last_access is None or r["eventId"] >= last_access), None)

    order_conflict = bool(
        (create and first_access is not None and create["eventId"] > first_access)
        or (release and last_access is not None and release["eventId"] < last_access)
    )

    def endpoint(event, reason, expected_side):
        if event is None:
            return {"status": "unknown", "eventId": None, "observationStatus": "unknown",
                    "reason": reason}
        return {"status": "observed", "eventId": int(event["eventId"]),
                "observationStatus": "observed", "reason": None,
                "evidenceRefs": [
                    {"id": ev.get("id")} for ev in event.get("evidence", ()) if ev.get("id")
                ]}

    creation = endpoint(create, "creation_event_not_observed", "before")
    destruction = endpoint(release, "release_event_not_observed", "after")
    first_endpoint = endpoint(
        {"eventId": first_access} if first_access is not None else None,
        "no_access_event_observed", "first")
    last_endpoint = endpoint(
        {"eventId": last_access} if last_access is not None else None,
        "no_access_event_observed", "last")

    instances = []
    if creates or releases:
        for index_, creation_event in enumerate(creates or [{"eventId": None}], 1):
            following = next(
                (r for r in releases
                 if creation_event["eventId"] is None
                 or r["eventId"] > creation_event["eventId"]),
                None)
            events_in_instance = [
                eid for eid in writes + reads
                if (creation_event["eventId"] is None or eid >= creation_event["eventId"])
                and (following is None or eid <= following["eventId"])
            ]
            instances.append({
                "instanceId": f"instance-{index_}",
                "createEventId": creation_event.get("eventId"),
                "releaseEventId": following.get("eventId") if following else None,
                "accessEventIds": events_in_instance,
                "status": "partial" if following is None else "observed",
            })
    else:
        instances.append({
            "instanceId": "instance-1",
            "createEventId": None,
            "releaseEventId": None,
            "accessEventIds": writes + reads,
            "status": "partial",
        })

    interval_status = (
        "order_conflict" if order_conflict else
        "observed" if creation["status"] == "observed"
        and destruction["status"] == "observed" else
        "partial" if creation["status"] == "observed"
        or destruction["status"] == "observed" else "unknown"
    )
    lifetime_status = (
        "order_conflict" if order_conflict else
        "multiple" if len(creates) > 1 or len(releases) > 1 else
        interval_status
    )

    return {
        # R2 fields: unchanged names and values.
        "firstWriteEventId": writes[0] if writes else None,
        "lastWriteEventId": writes[-1] if writes else None,
        "lastReadEventId": reads[-1] if reads else None,
        "writeCount": len(writes),
        "readCount": len(reads),
        "creationEventId": create["eventId"] if create else None,
        "destructionEventId": release["eventId"] if release else None,
        "status": "partial",
        "reason": "creation/destruction events are not exposed by GetUsage",
        # R3.3: explicit endpoints and interval states.
        "endpoints": {
            "creation": creation,
            "firstAccess": first_endpoint,
            "lastAccess": last_endpoint,
            "release": destruction,
        },
        "interval": {
            "status": interval_status,
            "startEventId": creation["eventId"],
            "endEventId": destruction["eventId"],
            "reason": None if interval_status == "observed" else
                      "lifetime interval is not fully observed",
        },
        "instances": instances,
        "lifetimeStatus": lifetime_status,
        "supportLevel": "observed" if lifetime_status == "observed"
                        else "inferred" if lifetime_status == "partial" else "unknown",
    }


def analysis_status(accesses, causal):
    """A partial result must never be reported as complete."""
    if not accesses:
        return "unknown"
    if causal.get("truncated") or causal["unresolved"] or any(
            a["status"] == "unknown" for a in accesses):
        return "partial"
    return "complete"
