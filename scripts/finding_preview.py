"""D1/D2: preview report skeleton and findings from an archived analysis result.

Not the full report generator (D6). It only proves that a real analysis
payload produces an honest report structure and correctly typed findings.
"""

import argparse
import json

from rdebug.diagnostics.finding_builder import build_findings, validate_findings
from rdebug.diagnostics.report_model import (
    empty_report,
    set_section,
    validate_report,
)


def preview(analysis, capture=None):
    findings = build_findings(analysis)
    report = empty_report(capture=capture)
    set_section(
        report, "findings", "present", None,
        {"findings": findings["findings"], "findingCount": findings["findingCount"],
         "anomalyCount": findings["anomalyCount"]})
    set_section(
        report, "limitations", "present" if findings["limitations"] else "insufficient_evidence",
        None if findings["limitations"] else "no limitation was recorded",
        {"items": findings["limitations"]})
    set_section(
        report, "workload_overview", "present", None,
        {"resource": analysis.get("resource"),
         "summary": analysis.get("summary")})
    set_section(
        report, "evidence_coverage", "present", None,
        {"analysisStatus": analysis.get("analysisStatus"),
         "unresolved": analysis.get("causal", {}).get("unresolved", [])})
    set_section(
        report, "evidence_appendix", "present", None,
        {"evidenceRefs": findings["findings"][0]["evidenceRefs"]
         if findings["findings"] else []})
    validate_report(report)
    validate_findings(findings)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="finding-preview")
    ap.add_argument("analysis_json")
    ap.add_argument("--json", dest="json_path")
    args = ap.parse_args(argv)
    with open(args.analysis_json, encoding="utf-8") as fh:
        analysis = json.load(fh)
    text = json.dumps(preview(analysis), indent=2, ensure_ascii=False)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
