"""C3: typed resource dependencies with explicit evidence rules.

The access index says *what kind of access* happened; this module says what
ordering relation two accesses on the same resource have. Every dependency
is tied to two observed GetUsage rows, so the strongest support is
``inferred_from_order``: event order is observed, content propagation is not.
Subresource and alias dependencies cannot be derived from GetUsage and are
reported as unresolved, never fabricated.
"""

import bisect
import hashlib
import json

from .resource_access import group_accesses_by_resource

DEPENDENCY_TYPES = ("raw", "war", "waw", "copy", "resolve")
SUPPORT_LEVELS = ("inferred_from_order", "unknown")


def _dep_id(resource, kind, first, second):
    canonical = json.dumps([resource, kind, first, second],
                           separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def _refs(*entries):
    return [{"id": ev["id"]} for entry in entries for ev in entry.get("evidence", ())]


def build_dependency_index(accesses, max_edges=None):
    """Build typed dependencies from ordered accesses on the same resource.

    ``max_edges`` is an explicit, reported limit. A truncated index carries
    ``omittedDependencyCount`` and is never presented as complete.
    """
    dependencies = []
    omitted = 0
    for resource, entries in sorted(group_accesses_by_resource(accesses).items()):
        usable = [a for a in entries if a["eventId"] is not None]
        usable.sort(key=lambda a: a["eventId"])
        writers = [a for a in usable if a["legacyKind"] == "write"]
        readers = [a for a in usable if a["legacyKind"] == "read"]
        writer_events = [a["eventId"] for a in writers]
        writer_positions = range(len(writers))

        # RAW / copy / resolve: a write precedes a read.
        for reader in readers:
            cutoff = bisect.bisect_left(writer_events, reader["eventId"])
            for i in writer_positions:
                if i >= cutoff:
                    break
                writer = writers[i]
                kind = "raw"
                via = None
                if writer["accessType"] == "copy":
                    via = "copy"
                elif writer["accessType"] == "resolve":
                    via = "resolve"
                if max_edges is not None and len(dependencies) >= max_edges:
                    omitted += 1
                    continue
                dependencies.append({
                    "dependencyId": _dep_id(resource, kind, writer["eventId"],
                                            reader["eventId"]),
                    "causalType": kind,
                    "resourceId": resource,
                    "fromEventId": writer["eventId"],
                    "toEventId": reader["eventId"],
                    "via": via,
                    "supportLevel": "inferred_from_order",
                    "status": "inferred",
                    "rule": "write_precedes_read",
                    "evidenceRefs": _refs(writer, reader),
                })

        # WAR: a read precedes a later write.
        for write in writers:
            for read in readers:
                if read["eventId"] >= write["eventId"]:
                    continue
                if max_edges is not None and len(dependencies) >= max_edges:
                    omitted += 1
                    continue
                dependencies.append({
                    "dependencyId": _dep_id(resource, "war", read["eventId"],
                                            write["eventId"]),
                    "causalType": "war",
                    "resourceId": resource,
                    "fromEventId": read["eventId"],
                    "toEventId": write["eventId"],
                    "via": None,
                    "supportLevel": "inferred_from_order",
                    "status": "inferred",
                    "rule": "read_precedes_write",
                    "evidenceRefs": _refs(read, write),
                })

        # WAW: consecutive writes in event order.
        for previous, following in zip(writers, writers[1:]):
            if max_edges is not None and len(dependencies) >= max_edges:
                omitted += 1
                continue
            dependencies.append({
                "dependencyId": _dep_id(resource, "waw", previous["eventId"],
                                        following["eventId"]),
                "causalType": "waw",
                "resourceId": resource,
                "fromEventId": previous["eventId"],
                "toEventId": following["eventId"],
                "via": None,
                "supportLevel": "inferred_from_order",
                "status": "inferred",
                "rule": "write_precedes_write",
                "evidenceRefs": _refs(previous, following),
            })

    return {
        "dependencies": dependencies,
        "dependencyCount": len(dependencies),
        "truncated": omitted > 0,
        "omittedDependencyCount": omitted,
        "limit": max_edges,
        "unresolved": [
            {
                "field": "subresource",
                "status": "unknown",
                "reason": "ReplayController.GetUsage does not expose mip/layer/slice",
            },
            {
                "field": "alias",
                "status": "unknown",
                "reason": "equal resource ids do not prove physical memory aliasing",
            },
        ],
        "status": "partial" if omitted else "inferred",
    }
