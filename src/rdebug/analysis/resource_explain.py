"""R5.2: traceable explanations for resource-access relations.

An explanation is built on demand for a relation the caller actually wants
to understand. It is deliberately NOT materialized for every edge: R5.1 shows
that a per-edge hash made the 512-row case ~2.5x slower, and an explanation is
useful only when someone inspects that relation.

The rule names are finite and non-probabilistic. An explanation states which
rule was applied, which evidence supports it and exactly what remains
unobserved; it never upgrades an inferred relation to an observed one.
"""

import hashlib
import json

from .resource_access import CAUSAL_TYPES, SUPPORT_LEVELS

RULES = {
    "writer_to_reader": "writer_precedes_reader_in_event_order",
    "overwrite": "later_write_follows_earlier_write",
    "resource_identity": "same_resource_id",
}
LIMITATIONS = {
    "writer_to_reader": (
        "resource_content_flow_not_observed",
        "coverage_not_observed",
        "subresource_not_observed",
    ),
    "overwrite": (
        "coverage_not_observed",
        "region_not_observed",
    ),
    "resource_identity": (
        "physical_alias_not_proven",
    ),
}


def relation_id(edge):
    """Stable id of a relation, independent of dict key order or revision."""
    canonical = json.dumps(
        [edge.get("resourceId") or "", edge.get("causalType") or "writer_to_reader",
         edge.get("fromEventId"), edge.get("toEventId")],
        separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def explain_relation(edge):
    """Build one traceable explanation for an existing relation object."""
    causal_type = edge.get("causalType") or "writer_to_reader"
    if causal_type not in CAUSAL_TYPES:
        raise ValueError("invalid causal type: " + str(causal_type))
    support = edge.get("supportLevel") or "unknown"
    if support not in SUPPORT_LEVELS:
        raise ValueError("invalid support level: " + str(support))
    observation = edge.get("observationStatus") or "unknown"
    if observation not in ("observed", "inferred", "unknown"):
        raise ValueError("invalid observation status: " + str(observation))
    return {
        "relationId": relation_id(edge),
        "causalType": causal_type,
        "supportLevel": support,
        "observationStatus": observation,
        "evidenceRefs": [dict(ref) for ref in edge.get("evidenceRefs", ())],
        "reason": edge.get("reason") or "no reason recorded",
        "rule": RULES[causal_type],
        "limitations": list(LIMITATIONS[causal_type]),
        "status": edge.get("status") or (
            "observed" if support == "direct" else
            "inferred" if support == "inferred_from_order" else "unknown"),
        "canConcludeContentFlow": support == "direct",
    }


def explain_relations(edges):
    """Batch form for a caller that already has a small selected edge set."""
    return [explain_relation(edge) for edge in edges]
