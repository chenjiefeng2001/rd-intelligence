"""D2: turn analysis results into findings without inventing problems.

A dependency type is not a defect. RAW is normal in graphics workloads. A
finding is emitted only when there is observed evidence to support a specific
claim; otherwise the analyzer records a limitation for the report's
Limitations section instead of manufacturing a problem.

Each rule declares its trigger, required evidence, exclusions, acceptable
alternative explanations, and the conclusions it does and does not permit.
Those declarations are data so controls can assert them.
"""

import hashlib
import json

from ..diagnostics.report_model import FINDING_STATUSES, PRIORITIES, SEVERITIES

RULES = {
    "copy_sampling_dependency": {
        "trigger": "a CopyDst writer precedes PS_Resource reads on one resource",
        "required_evidence": ("writer_event", "reader_event", "resource_id"),
        "exclusions": ("cross_resource", "reader_before_writer"),
        "alternatives": ("unrelated_access", "stale_descriptor_view"),
        "allowed": ("inferred_copy_to_sampling_dependency",),
        "disallowed": (
            "confirmed_content_propagation",
            "shader_read_correctness",
            "application_source_location",
        ),
        "kind": "observation",
        "severity": "info",
        "priority": "P3",
    },
    "lifetime_order_conflict": {
        "trigger": "create or release event contradicts the observed access window",
        "required_evidence": ("lifecycle_event", "access_events"),
        "exclusions": ("no_lifecycle_events",),
        "alternatives": ("timestamp_rounding", "resource_id_reuse"),
        "allowed": ("inferred_lifetime_inconsistency",),
        "disallowed": ("confirmed_application_bug", "source_location"),
        "kind": "anomaly",
        "severity": "high",
        "priority": "P1",
    },
    "subresource_mismatch": {
        "trigger": "observed writer and reader ranges differ on the same resource",
        "required_evidence": ("writer_subresource", "reader_subresource"),
        "exclusions": ("subresource_unknown",),
        "alternatives": ("different_view_of_same_resource", "partial_update"),
        "allowed": ("observed_range_mismatch",),
        "disallowed": ("confirmed_wrong_texture_binding", "application_source_location"),
        "kind": "anomaly",
        "severity": "high",
        "priority": "P1",
    },
    "sampled_content_mismatch": {
        "trigger": "independent pixel-history oracle reports different shader output",
        "required_evidence": ("baseline_pixel_history", "candidate_pixel_history"),
        "exclusions": ("no_passed_shader_output", "difference_within_tolerance"),
        "alternatives": ("different_resource_binding", "wrong_subresource",
                         "capture_or_replay_nondeterminism"),
        "allowed": ("observed_output_difference",),
        "disallowed": ("confirmed_application_root_cause", "content_flow_proven"),
        "kind": "anomaly",
        "severity": "critical",
        "priority": "P0",
    },
}


def _finding_id(category, kind, resource, events):
    canonical = json.dumps([category, kind, resource, sorted(set(events))],
                           separators=(",", ":"), default=str)
    return "finding-" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def _refs(*entries):
    refs = []
    for entry in entries:
        for ev in entry.get("evidence", ()) or ():
            if ev.get("id"):
                refs.append({"id": ev["id"]})
        for ref in entry.get("evidenceRefs", ()) or ():
            if ref.get("id"):
                refs.append({"id": ref["id"]})
    return refs


def _make(category, resource, events, evidence_refs, affected_events, summary,
          limitations):
    rule = RULES[category]
    status = "inferred" if evidence_refs else "not_established"
    return {
        "findingId": _finding_id(category, rule["kind"], resource, affected_events),
        "category": category,
        "kind": rule["kind"],
        "title": category.replace("_", " ").capitalize(),
        "status": status,
        "severity": rule["severity"],
        "priority": rule["priority"],
        "summary": summary,
        "affectedResources": [resource],
        "affectedEvents": affected_events,
        "evidenceRefs": evidence_refs,
        "causalRelations": [],
        "impact": {
            "scope": "resource_access_only",
            "claim": "event-order evidence; no content-flow conclusion",
        },
        "allowedConclusions": list(rule["allowed"]),
        "disallowedConclusions": list(rule["disallowed"]),
        "alternativeExplanations": list(rule["alternatives"]),
        "limitations": limitations,
        "recommendedActions": [],
    }


def build_findings(analysis, subresource_comparisons=None, content_comparison=None):
    """Build findings from a trace_resource result (additive, read-only)."""
    findings = []
    limitations = []
    resource = analysis.get("resource", {}).get("id") or ""
    writers = [e for e in analysis.get("writers", ())
               if e.get("usage") == "CopyDst"]
    readers = [e for e in analysis.get("readers", ())
               if e.get("usage") == "PS_Resource"]
    if writers and readers:
        refs = _refs(writers[0], *readers[:3])
        if refs:
            events = [writers[0]["eventId"]] + [r["eventId"] for r in readers[:3]]
            findings.append(_make(
                "copy_sampling_dependency", resource, events, refs,
                events,
                "A CopyDst write precedes PS_Resource reads on one resource; "
                "the relationship is inferred from event order only.",
                ["content_propagation_not_observed",
                 "application_source_not_attributed"],
            ))
    else:
        limitations.append({
            "category": "copy_sampling_dependency",
            "status": "not_established",
            "reason": "no CopyDst writer with PS_Resource readers on this resource",
        })

    lifetime = analysis.get("lifetime", {})
    if lifetime.get("lifetimeStatus") == "order_conflict":
        creation = lifetime.get("endpoints", {}).get("creation", {})
        refs = [{"id": ref["id"]} for ref in creation.get("evidenceRefs", ())
                if ref.get("id")]
        event_ids = [creation.get("eventId") or 0] + [
            e["eventId"] for e in analysis.get("accesses", ())
            if e.get("eventId") is not None]
        findings.append(_make(
            "lifetime_order_conflict", resource, event_ids, refs, event_ids,
            "A lifecycle event conflicts with the observed access window.",
            ["physical_alias_not_proven"],
        ))

    if content_comparison and content_comparison.get("status") == "different":
        refs = content_comparison.get("evidenceRefs", [])
        findings.append(_make(
            "sampled_content_mismatch", resource,
            [content_comparison.get("eventId") or 0], refs,
            [content_comparison.get("eventId") or 0],
            "An independent pixel-history oracle reports that final shader "
            "output differs from the baseline beyond tolerance.",
            ["root_cause_not_established", "content_flow_not_observed"],
        ))
    elif content_comparison and content_comparison.get("status") == "unknown":
        limitations.append({
            "category": "sampled_content_mismatch",
            "status": "unknown",
            "reason": content_comparison.get("reason", "oracle unavailable"),
        })

    for comparison in subresource_comparisons or ():
        if (comparison.get("status") == "observed"
                and comparison.get("sameSubresource") is False):
            findings.append(_make(
                "subresource_mismatch", resource, [], comparison.get("evidenceRefs", []),
                comparison.get("events", []),
                "Observed writer and reader ranges differ on the same resource.",
                ["content_propagation_not_observed"],
            ))

    for entry in analysis.get("causal", {}).get("unresolved", ()):
        limitations.append({
            "category": entry.get("field"),
            "status": "unknown",
            "reason": entry.get("reason"),
        })

    if not findings:
        limitations.append({
            "category": "findings",
            "status": "not_established",
            "reason": "no rule was triggered by the supplied evidence",
        })
    return {
        "findings": findings,
        "limitations": limitations,
        "findingCount": len(findings),
        "anomalyCount": sum(1 for f in findings if f["kind"] == "anomaly"),
        "status": "inferred" if findings else "not_established",
    }


def validate_findings(result):
    """Structural checks that also enforce the evidence discipline."""
    for finding in result["findings"]:
        if finding["status"] not in FINDING_STATUSES:
            raise ValueError("invalid finding status")
        if finding["severity"] not in SEVERITIES or finding["priority"] not in PRIORITIES:
            raise ValueError("invalid severity or priority")
        if finding["status"] != "not_established" and not finding["evidenceRefs"]:
            raise ValueError(finding["findingId"] + ": finding without evidence refs")
        if not finding["disallowedConclusions"]:
            raise ValueError(finding["findingId"] + ": no conclusion boundary declared")
    return True
