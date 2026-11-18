"""D7.2: before/after resolution states for the same finding.

A finding disappearing in a later report is not sufficient to close it. A
resolution needs explicit verification evidence tied to the same finding id.
"""

RESOLUTION_STATUSES = ("open", "in_progress", "resolved", "not_reproduced",
                       "unresolved", "verification_inconclusive")


def evaluate_resolution(before, after, verification_evidence=None):
    """Link a before/after pair by finding identity, not by text similarity."""
    before_findings = {
        f["findingId"]: f
        for f in before["sections"]["findings"]["content"].get("findings", ())}
    after_findings = {
        f["findingId"]: f
        for f in after["sections"]["findings"]["content"].get("findings", ())}
    results = []
    for finding_id, original in before_findings.items():
        if finding_id in after_findings:
            status = "unresolved"
            reason = "the same finding still appears in the re-analysis"
        elif not verification_evidence:
            status = "verification_inconclusive"
            reason = "finding absent after change, but no verification evidence supplied"
        elif verification_evidence.get(finding_id, {}).get("passed") is True:
            status = "resolved"
            reason = "finding absent after change and targeted verification passed"
        else:
            status = "verification_inconclusive"
            reason = "targeted verification did not pass"
        results.append({
            "findingRef": finding_id,
            "status": status,
            "reason": reason,
            "originalStatus": original.get("status"),
            "actionType": (
                next((r["actionType"] for r in
                      before["sections"]["recommendations"]["content"]
                      .get("recommendations", ())
                      if finding_id in r.get("findingRefs", ())), None)
            ),
        })
    return {
        "comparisons": results,
        "resolvedCount": sum(1 for r in results if r["status"] == "resolved"),
        "status": "resolved" if results and all(
            r["status"] == "resolved" for r in results) else "open",
    }
