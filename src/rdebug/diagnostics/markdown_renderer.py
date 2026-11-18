"""D6.2: render Markdown strictly from the JSON report object.

No prose is invented here: every line maps to a field of the authoritative
report. A conclusion absent from JSON cannot appear in Markdown.
"""

from .report_model import SECTIONS

TITLES = {
    "executive_summary": "Executive Summary",
    "analysis_scope": "Analysis Scope",
    "workload_overview": "Workload Overview",
    "evidence_coverage": "Evidence Coverage",
    "findings": "Findings",
    "diagnosis": "Diagnosis",
    "impact_analysis": "Impact Analysis",
    "recommendations": "Recommendations",
    "change_proposals": "Change Proposals",
    "verification_plan": "Verification Plan",
    "limitations": "Limitations",
    "evidence_appendix": "Evidence Appendix",
}


def _status_line(value):
    reason = value.get("reason") or ""
    return f"status: `{value['status']}`" + (f" — {reason}" if reason else "")


def _render_section(name, value):
    lines = [f"## {TITLES[name]}", "", _status_line(value), ""]
    content = value.get("content", {})
    if not content:
        return lines
    if name == "findings":
        for finding in content.get("findings", ()):
            lines.append(f"### {finding['findingId']}")
            lines.append("")
            lines.append(f"- kind: `{finding['kind']}`; status: `{finding['status']}`; "
                         f"severity: `{finding['severity']}`; priority: `{finding['priority']}`")
            lines.append(f"- summary: {finding['summary']}")
            refs = ", ".join(r["id"] for r in finding["evidenceRefs"]) or "none"
            lines.append(f"- evidence: {refs}")
            lines.append(f"- disallowed: {', '.join(finding['disallowedConclusions'])}")
            lines.append("")
    elif name == "recommendations":
        for item in content.get("recommendations", ()):
            lines.append(f"### {item['recommendationId']}")
            lines.append("")
            lines.append(f"- action: `{item['actionType']}`; status: `{item['status']}`")
            lines.append(f"- rationale: {item['rationale']}")
            lines.append(f"- findings: {', '.join(item['findingRefs']) or 'none'}")
            lines.append("")
    elif name in ("diagnosis", "change_proposals", "verification_plan",
                 "limitations", "evidence_appendix", "executive_summary"):
        lines.append("```json")
        lines.append(_compact(content))
        lines.append("```")
        lines.append("")
    else:
        lines.append("```json")
        lines.append(_compact(content))
        lines.append("```")
        lines.append("")
    return lines


def _compact(value):
    import json
    return json.dumps(value, ensure_ascii=False, indent=2)


def render_markdown(report):
    """Render all twelve sections in fixed order from the same report object."""
    lines = [
        "# Diagnostic Report",
        "",
        f"schema: `{report['schema']}`",
        "",
    ]
    repro = report.get("reproducibility", {})
    lines.append(f"capture: `{repro.get('capture')}`  ")
    lines.append(f"capture sha256: `{repro.get('captureSha256')}`  ")
    lines.append(f"analysis revision: `{repro.get('analysisRevision')}`")
    lines.append("")
    for name in SECTIONS:
        lines.extend(_render_section(name, report["sections"][name]))
    return "\n".join(lines) + "\n"
