"""E1/E3: an independent failure oracle from rendered output.

The finding that sampled content is wrong must not come from the analyzer's
own dependency graph. This module compares pixel-history shader outputs from
two real captures; only that comparison can trigger a content anomaly.
"""

TOLERANCE = 0.02


def _final_shader_output(payload):
    edits = [m for m in payload.get("modifications", ())
             if m.get("passed") and m.get("shaderOut", {}).get("float")]
    if not edits:
        return None
    return edits[-1]["shaderOut"]["float"][:4]


def _evidence_refs(payload):
    return [{"id": ev["id"]} for ev in payload.get("evidence", ())
            if ev.get("id")]


def compare_shader_outputs(baseline, candidate, event_id, tolerance=TOLERANCE):
    """Compare final shader output at one event/pixel across two captures."""
    before = _final_shader_output(baseline)
    after = _final_shader_output(candidate)
    if before is None or after is None:
        return {"status": "unknown", "reason": "no passed shader output in one capture",
                "eventId": event_id, "evidenceRefs": []}
    difference = max(abs(float(before[i]) - float(after[i])) for i in range(4))
    status = "different" if difference > tolerance else "same"
    return {
        "status": status,
        "eventId": event_id,
        "baselineOutput": before,
        "candidateOutput": after,
        "maxDifference": difference,
        "tolerance": tolerance,
        "evidenceRefs": _evidence_refs(baseline) + _evidence_refs(candidate),
    }
