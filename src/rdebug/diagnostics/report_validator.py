"""D6.3/D7: cross-reference and format consistency checks for a report."""

import re

from .report_model import SECTIONS, validate_report


def validate_report_quality(report, markdown=None):
    """Check every cross-reference and, when given, Markdown/JSON identity parity."""
    validate_report(report)
    sections = report["sections"]
    findings = sections["findings"]["content"].get("findings", ())
    finding_ids = {f["findingId"] for f in findings}
    diagnoses = sections["diagnosis"]["content"].get("chains", ())
    diag_ids = {c["conclusion"]["conclusionId"] for c in diagnoses
                if c.get("conclusion")}
    recommendations = sections["recommendations"]["content"].get("recommendations", ())
    rec_ids = {r["recommendationId"] for r in recommendations}

    for finding in findings:
        if finding["status"] != "not_established" and not finding.get("evidenceRefs"):
            raise ValueError(finding["findingId"] + ": finding without evidence")
    for chain in diagnoses:
        for ref in chain.get("relations", ()):
            if ref.get("to") is None and ref["type"] == "challenged_by":
                continue
        if chain.get("conclusion") and chain["conclusion"]["status"] != "not_established":
            if not chain["conclusion"].get("hypothesisRefs"):
                raise ValueError("diagnosis conclusion without hypothesis")
    for rec in recommendations:
        if not rec.get("rationale"):
            raise ValueError(rec["recommendationId"] + ": no rationale")
        if rec["actionType"] != "no_change" and not rec.get("verificationSteps"):
            raise ValueError(rec["recommendationId"] + ": no verification steps")
        for ref in rec.get("diagnosisRefs", ()):
            if ref not in diag_ids:
                raise ValueError(rec["recommendationId"] + ": unknown diagnosis ref")
    for plan in sections["verification_plan"]["content"].get("plans", ()):
        if plan.get("recommendationRef") not in rec_ids:
            raise ValueError("verification plan points at an unknown recommendation")
    for plan in sections["change_proposals"]["content"].get("changePlans", ()):
        if plan.get("recommendationRef") not in rec_ids:
            raise ValueError("change plan points at an unknown recommendation")
    if markdown is not None:
        md_findings = set(re.findall(r"finding-[0-9a-f]{12}", markdown))
        md_recs = set(re.findall(r"recommendation-[0-9a-f]{12}", markdown))
        if md_findings != finding_ids:
            raise ValueError("Markdown/JSON finding identity mismatch")
        if md_recs != rec_ids:
            raise ValueError("Markdown/JSON recommendation identity mismatch")
        if len(re.findall(r"^## [^\n]+$", markdown, re.MULTILINE)) != len(SECTIONS):
            raise ValueError("Markdown section count mismatch")
    return {
        "findingCount": len(finding_ids),
        "diagnosisCount": len(diag_ids),
        "recommendationCount": len(rec_ids),
        "sections": len(SECTIONS),
        "status": "PASS",
    }
