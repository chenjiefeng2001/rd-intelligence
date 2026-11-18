"""D3.2/D3.3: derive a diagnosis chain from findings.

The engine deliberately does NOT diagnose an observation-only finding. An
anomaly is required before hypotheses are generated, and even then the
default conclusion is provisional or not_established unless direct evidence
supports an established one. Alternative explanations carry discriminating
checks so the next investigation step is explicit.
"""

from .diagnosis_model import (
    chain,
    conclusion,
    fact,
    hypothesis,
    validate_chain,
)

ALTERNATIVE_RULES = {
    "lifetime_order_conflict": (
        ("resource_id_reuse", "A reused id can look like an inconsistent lifetime",
         "query creation events after each apparent release"),
        ("timestamp_rounding", "Event ordering may be coarser than the lifecycle event",
         "compare raw event ids for create/release and accesses"),
    ),
    "subresource_mismatch": (
        ("different_view_of_same_resource", "Two views can reference one resource differently",
         "compare view ids, not only resource ids"),
        ("partial_update", "A partial write may legitimately cover a smaller range",
         "compare byte ranges and mip/layer coverage"),
    ),
    "sampled_content_mismatch": (
        ("wrong_resource_binding", "A different resource may be bound at the shader slot",
         "compare descriptor resource ids at the sampling event"),
        ("wrong_upload_source", "The copy source may carry unintended content",
         "inspect the source resource contents before the copy"),
        ("replay_nondeterminism", "The two captures may differ outside the suspected change",
         "re-run the baseline capture twice and compare the oracle"),
    ),
}

HYPOTHESIS_RULES = {
    "lifetime_order_conflict": (
        "Resource lifetime endpoints may not describe the observed access window.",
        ("lifecycle_event_after_access",),
        ("no_lifecycle_events",),
    ),
    "subresource_mismatch": (
        "The writer and reader may be using different subresource ranges.",
        ("observed_range_mismatch",),
        ("subresource_unknown",),
    ),
    "sampled_content_mismatch": (
        "The uploaded resource content may not be the content the shader samples.",
        ("independent_output_difference",),
        ("no_passed_shader_output",),
    ),
}


def _can_establish(source_analysis, evidence_refs):
    """Establishment needs an independent oracle and a verified source level."""
    data = source_analysis or {}
    level = data.get("sourceLevel", "S0")
    return bool(data.get("establishedByOracle")) and level in ("S3", "S4") \
        and bool(evidence_refs)


def build_diagnosis(finding, source_analysis=None):
    """Return a diagnosis chain, or None for a normal observation."""
    if finding.get("kind") != "anomaly":
        return None
    category = finding.get("category")
    if category not in HYPOTHESIS_RULES:
        return conclusion_chain(finding, reason="no hypothesis rule for this category")

    statement, supporting, exclusions = HYPOTHESIS_RULES[category]
    evidence_refs = finding.get("evidenceRefs", [])
    facts = [
        fact(statement, "inferred", evidence_refs,
             source_analysis_refs=[finding["findingId"]],
             limitations=["event_order_only"]),
    ]
    primary = hypothesis(
        statement,
        status="supported" if evidence_refs else "candidate",
        supporting=[finding["findingId"]],
        contradicting=[],
        assumptions=["the reported finding accurately reflects the capture"],
        missing=["direct_content_flow_evidence"],
        discriminating_checks=["inspect original events named in evidenceRefs"],
    )
    alternatives = []
    for key, alt_statement, check in ALTERNATIVE_RULES.get(category, ()):
        alternatives.append(
            hypothesis(alt_statement, status="candidate",
                       supporting=[], contradicting=[],
                       assumptions=[key],
                       missing=["evidence_to_distinguish_" + key],
                       discriminating_checks=[check]))

    established = _can_establish(source_analysis, evidence_refs)
    result = conclusion(
        "established" if established else
        "provisional" if evidence_refs else "not_established",
        [primary["hypothesisId"]],
        [f["factId"] for f in facts],
        "an independent oracle and verified source mapping establish the "
        "diagnosis" if established else
        "anomaly finding is supported by event-order evidence; alternatives "
        "remain until the discriminating checks are performed",
        alternatives=[h["hypothesisId"] for h in alternatives],
    )
    relations = [
        {"type": "supported_by", "from": finding["findingId"],
         "to": facts[0]["factId"]},
        {"type": "explained_by", "from": finding["findingId"],
         "to": primary["hypothesisId"]},
        {"type": "challenged_by", "from": primary["hypothesisId"],
         "to": alternatives[0]["hypothesisId"]} if alternatives else
        {"type": "challenged_by", "from": primary["hypothesisId"], "to": None},
        {"type": "evaluated_as", "from": primary["hypothesisId"],
         "to": result["conclusionId"]},
    ]
    item = chain(finding["findingId"], facts, [primary] + alternatives,
                 alternatives, relations, result)
    validate_chain(item)
    return item


def conclusion_chain(finding, reason):
    """A not_established chain for an anomaly with no applicable rule."""
    item = chain(
        finding["findingId"],
        facts=[],
        hypotheses=[],
        alternatives=[],
        relations=[],
        result=conclusion("not_established", [], [], reason),
    )
    validate_chain(item)
    return item


def build_diagnoses(finding_result, source_analysis=None):
    """Diagnose every anomaly; observations and zero-finding results stay empty."""
    items = []
    for finding in finding_result.get("findings", ()):
        item = build_diagnosis(finding, source_analysis)
        if item is not None:
            items.append(item)
    return {
        "diagnoses": items,
        "diagnosisCount": len(items),
        "observationOnly": bool(finding_result.get("findings")) and not items,
        "status": "not_established" if not items else "provisional",
    }
