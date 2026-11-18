"""D1: an independent, versioned diagnostic report model.

Evidence status (`observed|inferred|unknown`) stays in the evidence layer.
This model defines separate namespaces for section availability, finding
status, severity and priority, so an inferred relation is never silently
read as a low-severity problem and an unknown is never read as "no problem".

A report section is never omitted. When no data supports it, it carries an
explicit status and a reason instead of fabricated content.
"""

REPORT_SCHEMA = "rdebug-diagnostic-report/1"

SECTIONS = (
    "executive_summary",
    "analysis_scope",
    "workload_overview",
    "evidence_coverage",
    "findings",
    "diagnosis",
    "impact_analysis",
    "recommendations",
    "change_proposals",
    "verification_plan",
    "limitations",
    "evidence_appendix",
)

SECTION_STATUSES = (
    "present",
    "not_established",
    "unknown",
    "not_observed",
    "insufficient_evidence",
)
FINDING_STATUSES = ("confirmed", "inferred", "pending", "not_established")
SEVERITIES = ("critical", "high", "medium", "low", "info")
PRIORITIES = ("P0", "P1", "P2", "P3")


def section(status, reason, content=None):
    """Build one always-present report section."""
    if status not in SECTION_STATUSES:
        raise ValueError("invalid section status: " + str(status))
    if status == "present" and content is None:
        raise ValueError("a present section requires content")
    if status != "present" and not reason:
        raise ValueError("a non-present section requires a reason")
    return {
        "status": status,
        "reason": reason,
        "content": content if content is not None else {},
    }


def empty_report(capture=None, capture_sha256=None, analysis_revision=None):
    """Create a complete skeleton: every section exists with an honest status."""
    reason = "no evidence has been supplied for this section yet"
    return {
        "schema": REPORT_SCHEMA,
        "reproducibility": {
            "capture": capture,
            "captureSha256": capture_sha256,
            "analysisRevision": analysis_revision,
        },
        "sections": {name: section("insufficient_evidence", reason)
                     for name in SECTIONS},
    }


def set_section(report, name, status, reason, content=None):
    if name not in SECTIONS:
        raise ValueError("unknown report section: " + str(name))
    report["sections"][name] = section(status, reason, content)
    return report


def validate_report(report):
    """Check structural completeness; never infer missing content."""
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError("unsupported diagnostic report schema")
    sections = report.get("sections", {})
    if set(sections) != set(SECTIONS):
        missing = sorted(set(SECTIONS) - set(sections))
        extra = sorted(set(sections) - set(SECTIONS))
        raise ValueError(f"section set mismatch: missing={missing} extra={extra}")
    for name, value in sections.items():
        if value.get("status") not in SECTION_STATUSES:
            raise ValueError(f"{name}: invalid section status")
        if value["status"] != "present" and not value.get("reason"):
            raise ValueError(f"{name}: non-present section needs a reason")
    return True
