"""D6.1: assemble the single authoritative JSON report from structured objects."""

from .change_planner import build_change_plans
from .diagnosis_engine import build_diagnoses
from .finding_builder import build_findings
from .mapping_resolver import resolve_attribution
from .recommendation_engine import build_recommendations
from .report_model import REPORT_SCHEMA, empty_report, set_section, validate_report
from .verification_planner import build_verification_plans


def assemble_report(analysis, metadata=None, capture=None, content_comparison=None):
    """Build the full twelve-section report; JSON is the only source of truth."""
    findings = build_findings(analysis, content_comparison=content_comparison)
    mappings = [resolve_attribution(analysis, metadata)]
    established_by_oracle = bool(
        content_comparison and content_comparison.get("status") == "different"
        and metadata and (metadata.get("binary_identity") or {}).get("verified")
        and (metadata.get("source_revision") or {}).get("verified"))
    diagnoses = build_diagnoses(findings, {
        "establishedByOracle": established_by_oracle,
        "sourceLevel": mappings[0]["highestVerifiedLevel"],
    })
    recommendations = build_recommendations(findings, diagnoses, mappings, capture)
    changes = build_change_plans(recommendations, mappings)
    verification = build_verification_plans(recommendations, changes, findings)

    report = empty_report(
        capture=capture,
        capture_sha256=(metadata or {}).get("capture_sha256"),
        analysis_revision=(metadata or {}).get("analysis_revision"))
    report["schema"] = REPORT_SCHEMA

    set_section(report, "executive_summary", "present", None, {
        "findingCount": findings["findingCount"],
        "anomalyCount": findings["anomalyCount"],
        "diagnosisCount": diagnoses["diagnosisCount"],
        "recommendationCount": recommendations["recommendationCount"],
        "highestSourceLevel": mappings[0]["highestVerifiedLevel"],
        "overallStatus": ("no_defect_reported" if findings["anomalyCount"] == 0
                          else "diagnosis_in_progress"),
    })
    set_section(report, "analysis_scope", "present", None, {
        "capture": capture,
        "tooling": "rdebug diagnostics " + REPORT_SCHEMA,
        "sourceAttribution": mappings,
        "highestLevel": mappings[0]["highestVerifiedLevel"],
    })
    set_section(report, "workload_overview", "present", None, {
        "resource": analysis.get("resource"),
        "summary": analysis.get("summary"),
        "accessCount": len(analysis.get("accesses", ())),
    })
    set_section(report, "evidence_coverage", "present", None, {
        "analysisStatus": analysis.get("analysisStatus"),
        "unresolved": analysis.get("causal", {}).get("unresolved", []),
        "limitations": findings["limitations"],
    })
    set_section(report, "findings", "present", None, findings)
    set_section(report, "diagnosis",
                "present" if diagnoses["diagnoses"] else "insufficient_evidence",
                None if diagnoses["diagnoses"] else
                "no anomaly triggered a diagnosis",
                {"chains": diagnoses["diagnoses"], "count": diagnoses["diagnosisCount"]})
    set_section(report, "impact_analysis", "present", None, {
        "affectedResources": sorted({rid for f in findings["findings"]
                                     for rid in f.get("affectedResources", ())}),
        "affectedEvents": sorted({eid for f in findings["findings"]
                                  for eid in f.get("affectedEvents", ())}),
        "claim": "event-order scope; no content-flow conclusion",
    })
    set_section(report, "recommendations", "present", None, recommendations)
    set_section(report, "change_proposals",
                "present" if changes["changePlans"] else "insufficient_evidence",
                None if changes["changePlans"] else
                "no actionable change was proposed", changes)
    set_section(report, "verification_plan", "present", None, verification)
    limitations = list(findings["limitations"]) + [
        {"category": "source_attribution", "status": "unknown",
         "reason": reason} for reason in mappings[0]["limitations"]]
    set_section(report, "limitations", "present", None, {"items": limitations})
    set_section(report, "evidence_appendix", "present", None, {
        "evidenceRefs": sorted({ref["id"] for f in findings["findings"]
                                for ref in f.get("evidenceRefs", ())}),
        "mappingIds": [m["mappingId"] for m in mappings],
        "analysisStatus": analysis.get("analysisStatus"),
    })
    validate_report(report)
    return report
