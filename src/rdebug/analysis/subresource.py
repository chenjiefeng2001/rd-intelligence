"""C4: subresource/region resolution and explicit coverage accounting.

Descriptor access can resolve a bound view's mip/layer and byte range for
shader reads. Where it cannot, the result stays ``unknown`` with a reason;
coverage separates analyzed, unobserved and missing-input events instead of
claiming completeness from the mere presence of some access rows.
"""

COVERAGE_STATUSES = ("complete", "partial", "unknown")


def resolve_access_subresources(accesses, descriptor_rows_by_event):
    """Attach descriptor-level subresources to read accesses.

    ``descriptor_rows_by_event`` maps an event id to descriptor rows already
    read through the adapter. Only rows whose resource matches the access are
    attached; unrelated descriptor rows never become evidence for this access.
    """
    resolved = []
    for access in accesses:
        entry = dict(access)
        resource = entry.get("resourceId")
        rows = [
            dict(row) for row in descriptor_rows_by_event.get(entry.get("eventId"), ())
            if row.get("resource") == resource
        ]
        if rows:
            entry["subresources"] = rows
            entry["subresourceStatus"] = "observed"
            entry["subresourceReason"] = None
        else:
            entry["subresources"] = []
            entry["subresourceStatus"] = "unknown"
            entry["subresourceReason"] = (
                "no descriptor access for this event and resource"
            )
        resolved.append(entry)
    return resolved


def build_coverage(accesses, resolved_accesses):
    """Distinguish analyzed, unobserved and missing-input portions."""
    total = len(accesses)
    analyzed = sum(1 for a in resolved_accesses
                   if a.get("subresourceStatus") == "observed")
    # Categories are mutually exclusive: a missing input row is not merely
    # an unobserved subresource, otherwise the sum can exceed the total and
    # the "coverage" claim becomes meaningless.
    unobserved = sum(1 for a in resolved_accesses
                     if a.get("subresourceStatus") == "unknown"
                     and a.get("eventId") is not None
                     and a.get("status") == "observed")
    missing_input = sum(1 for a in resolved_accesses
                        if a.get("status") == "unknown"
                        or a.get("eventId") is None)
    if total == 0:
        status = "unknown"
    elif analyzed == total:
        status = "complete"
    elif analyzed > 0:
        status = "partial"
    else:
        status = "unknown"
    return {
        "accessEventCount": total,
        "analyzedEventCount": analyzed,
        "unobservedEventCount": unobserved,
        "missingInputEventCount": missing_input,
        "status": status,
        "reason": None if status == "complete" else
                  "subresource data is only available for descriptor-backed reads",
    }


def match_subresource(writer, reader):
    """Compare resolved mip/layer/byte ranges; unknown never matches positively."""
    left = (writer.get("subresources") or [None])[0]
    right = (reader.get("subresources") or [None])[0]
    if left is None or right is None:
        return {"status": "unknown", "reason": "subresource_not_observed"}
    fields = ("firstMip", "numMips", "firstSlice", "numSlices",
              "byteOffset", "byteSize")
    missing = [f for f in fields if left.get(f) is None or right.get(f) is None]
    if missing:
        return {"status": "unknown", "reason": "range_fields_missing",
                "fields": missing}
    same = all(left.get(f) == right.get(f) for f in fields)
    return {"status": "observed", "sameSubresource": same,
            "comparedFields": list(fields)}
