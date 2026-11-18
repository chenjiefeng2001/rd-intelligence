"""D5.1: the recommendation contract.

A recommendation is an evidence-bound decision, not a generated opinion.
Action type and executability are separate: `no_change` can be fully valid,
and an actionable-looking type can still be `blocked` or
`insufficient_evidence`. Source locations are only copied from a verified
attribution record; this module never invents a file, function or line.
"""

import hashlib
import json

ACTION_TYPES = ("code_change", "api_state_correction", "instrumentation",
                "capture_workload", "no_change")
RECOMMENDATION_STATUSES = ("insufficient_evidence", "actionable", "blocked")


def _stable_id(prefix, parts):
    canonical = json.dumps(parts, separators=(",", ":"), default=str)
    return prefix + "-" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def recommendation(finding_refs, diagnosis_refs, action_type, status, rationale,
                   evidence_refs=None, source_locations=None, proposed_change=None,
                   expected_outcome=None, risk=None, preconditions=None,
                   verification_steps=None, rollback_strategy=None, priority="P2"):
    """Build one recommendation with all decision fields explicit."""
    if action_type not in ACTION_TYPES:
        raise ValueError("invalid action type: " + str(action_type))
    if status not in RECOMMENDATION_STATUSES:
        raise ValueError("invalid recommendation status: " + str(status))
    if not rationale:
        raise ValueError("a recommendation requires a rationale")
    if action_type != "no_change" and status == "actionable" and not evidence_refs:
        raise ValueError("an actionable change needs evidence references")
    return {
        "recommendationId": _stable_id(
            "recommendation", [sorted(finding_refs), action_type, rationale]),
        "findingRefs": list(finding_refs),
        "diagnosisRefs": list(diagnosis_refs),
        "actionType": action_type,
        "status": status,
        "priority": priority,
        "rationale": rationale,
        "evidenceRefs": [dict(ref) for ref in (evidence_refs or [])],
        "sourceLocations": list(source_locations or []),
        "proposedChange": dict(proposed_change or {}),
        "expectedOutcome": dict(expected_outcome or {}),
        "risk": dict(risk or {}),
        "preconditions": list(preconditions or []),
        "verificationSteps": list(verification_steps or []),
        "rollbackStrategy": dict(rollback_strategy or {}),
    }


def validate_recommendation(item):
    """Enforce traceability and the no-fabricated-location rule."""
    for field in ("findingRefs", "diagnosisRefs", "rationale", "actionType",
                  "status", "verificationSteps"):
        if field not in item:
            raise ValueError("recommendation missing " + field)
    if item["actionType"] not in ACTION_TYPES:
        raise ValueError("invalid action type")
    if item["status"] not in RECOMMENDATION_STATUSES:
        raise ValueError("invalid status")
    if item["actionType"] != "no_change" and not item.get("verificationSteps"):
        raise ValueError("a change recommendation needs verification steps")
    for location in item.get("sourceLocations", ()):
        if not location.get("verifiedByAttribution"):
            raise ValueError("source location is not verified by attribution")
    return True
