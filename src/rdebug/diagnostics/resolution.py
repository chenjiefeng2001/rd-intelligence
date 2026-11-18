"""D7.2: before/after resolution states for the same finding.

A finding disappearing in a later report is not sufficient to close it. A
resolution needs explicit verification evidence tied to the same finding id.
"""

RESOLUTION_STATUSES = ("open", "in_progress", "resolved", "not_reproduced",
                       "unresolved", "verification_inconclusive")


def evaluate_resolution(before, after, verification_evidence=None, kinds=None):
    """Link a before/after pair by finding identity, not by text similarity.

    ``kinds`` narrows the comparison to specific finding kinds (e.g. only the
    anomaly that a change was meant to fix); normal observations are not
    remediation targets and must not block a resolution decision.
    """
    def selected(report):
        items = report["sections"]["findings"]["content"].get("findings", ())
        if kinds is not None:
            items = [f for f in items if f.get("kind") in kinds]
        return {f["findingId"]: f for f in items}

    before_findings = selected(before)
    after_findings = selected(after)
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
