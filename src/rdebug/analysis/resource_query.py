"""R5.3: query an existing trace_resource result without changing it.

Pure read-only filters over the analysis payload. They never rewrite a
status: an ``unknown`` access stays unknown after filtering, and a filtered
subset is never presented as a complete analysis. The MCP protocol and the
CI report schema are deliberately untouched.
"""

from .resource_access import iter_writer_reader_edges, summarize_relations
from .resource_explain import explain_relation, relation_id


def _matches(value, expected):
    return expected is None or value == expected


def query_accesses(result, resource=None, event_id=None, access_type=None,
                   information_status=None):
    """Filter the access index by resource, event, type or information status."""
    accesses = result.get("accesses", ())
    selected = [
        dict(access) for access in accesses
        if _matches(access.get("resourceId"), resource)
        and _matches(access.get("eventId"), event_id)
        and _matches(access.get("accessType"), access_type)
        and _matches(access.get("status"), information_status)
    ]
    return {
        "query": {
            "resource": resource,
            "eventId": event_id,
            "accessType": access_type,
            "informationStatus": information_status,
        },
        "matched": len(selected),
        "available": len(accesses),
        "analysisStatus": result.get("analysisStatus"),
        "partialBySelection": len(selected) != len(accesses),
        "accesses": selected,
    }


def query_relations(result, from_event_id=None, to_event_id=None,
                    support_level=None, causal_type=None):
    """Filter causal relations; returned edges keep their original status."""
    edges = result.get("causal", {}).get("edges", ())
    selected = [
        dict(edge) for edge in edges
        if _matches(edge.get("fromEventId"), from_event_id)
        and _matches(edge.get("toEventId"), to_event_id)
        and _matches(edge.get("supportLevel"), support_level)
        and _matches(edge.get("causalType"), causal_type)
    ]
    return {
        "query": {
            "fromEventId": from_event_id,
            "toEventId": to_event_id,
            "supportLevel": support_level,
            "causalType": causal_type,
        },
        "matched": len(selected),
        "available": len(edges),
        "truncatedSource": bool(result.get("causal", {}).get("truncated")),
        "relations": selected,
    }


def query_lifetime(result, resource=None):
    """Return a resource lifetime with its explicit endpoint states."""
    lifetime = result.get("lifetime", {})
    if resource is not None and resource != result.get("resource", {}).get("id"):
        return {
            "resource": resource,
            "matched": 0,
            "status": "unknown",
            "reason": "resource_not_present_in_result",
            "lifetime": None,
        }
    return {
        "resource": result.get("resource", {}).get("id"),
        "matched": 1,
        "status": lifetime.get("lifetimeStatus", "unknown"),
        "lifetime": dict(lifetime),
    }


def query_explanation(result, relation_id_value=None,
                      from_event_id=None, to_event_id=None):
    """Explain one relation selected by id or by its endpoint events."""
    edges = result.get("causal", {}).get("edges", ())
    edge = None
    if relation_id_value is not None:
        edge = next((e for e in edges if relation_id(e) == relation_id_value), None)
    elif from_event_id is not None and to_event_id is not None:
        edge = next((e for e in edges
                     if e.get("fromEventId") == from_event_id
                     and e.get("toEventId") == to_event_id), None)
    if edge is None:
        return {"matched": 0, "status": "unknown",
                "reason": "relation_not_found", "explanation": None}
    return {"matched": 1, "status": edge.get("status"),
            "explanation": explain_relation(edge)}


def query_relations_stream(accesses, stats=None, max_edges=None, resource=None,
                           from_event_min=None, from_event_max=None,
                           to_event_min=None, to_event_max=None):
    """Stream filtered relations without materializing the full graph.

    Filters are pushed into the generator; no full relation object, no
    explanation and no JSON serialization of unrelated edges is performed.
    Unlike the exact-match R5.3 ``query_relations``, the streamed form takes
    explicit inclusive ranges so a range query never needs the full graph.
    ``stats`` receives ``emitted``/``omitted`` exactly as in the generator,
    so truncation remains explicit.
    """
    return iter_writer_reader_edges(
        accesses, stats=stats, max_edges=max_edges, lightweight=True,
        resource_ids=(resource,) if resource is not None else None,
        from_event_min=from_event_min, from_event_max=from_event_max,
        to_event_min=to_event_min, to_event_max=to_event_max)


def summarize_query_relations(accesses, resource=None):
    """Summary form for callers that only need counts, not relation objects."""
    summary = summarize_relations(accesses)
    if resource is not None:
        return {
            "relationCount": summary["perResource"].get(resource, 0),
            "perResource": {resource: summary["perResource"].get(resource, 0)},
            "status": summary["status"],
            "note": summary["note"] + "; filtered by resource",
            "partialBySelection": resource not in summary["perResource"],
        }
    return dict(summary, partialBySelection=False)


def query_by_status(result, analysis_status=None, evidence_status=None):
    """Filter by analysis-level and evidence-level status independently."""
    if analysis_status is not None and result.get("analysisStatus") != analysis_status:
        return {"matched": 0, "available": 1, "analysisStatus": result.get("analysisStatus"),
                "accesses": [], "partialBySelection": True}
    accesses = [
        dict(a) for a in result.get("accesses", ())
        if _matches(a.get("status"), evidence_status)
    ]
    total = len(result.get("accesses", ()))
    return {
        "matched": len(accesses),
        "available": total,
        "analysisStatus": result.get("analysisStatus"),
        "partialBySelection": len(accesses) != total,
        "accesses": accesses,
    }
