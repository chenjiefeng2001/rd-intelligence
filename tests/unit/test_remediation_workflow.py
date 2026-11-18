"""D5-D7: recommendations, reports and before/after closure."""

import json
import pathlib
import unittest

from rdebug.diagnostics.change_planner import build_change_plans
from rdebug.diagnostics.pipeline import run_diagnostic_pipeline
from rdebug.diagnostics.recommendation_engine import build_recommendations
from rdebug.diagnostics.recommendation_model import (
    ACTION_TYPES,
    RECOMMENDATION_STATUSES,
    recommendation,
    validate_recommendation,
)
from rdebug.diagnostics.report_model import SECTIONS
from rdebug.diagnostics.report_validator import validate_report_quality
from rdebug.diagnostics.resolution import evaluate_resolution
from rdebug.diagnostics.verification_planner import build_verification_plans

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
POSITIVE = REPO / "docs/validation/positive-copy-sample-a-d3d11-2026-11-19.json"
NEGATIVE = REPO / "docs/validation/capability-coverage-n3-02-2026-11-19.json"


def anomaly_inputs(status, level="S0"):
    finding = {
        "findingId": "finding-anomaly-1", "kind": "anomaly",
        "category": "lifetime_order_conflict",
        "status": "inferred", "severity": "high", "priority": "P1",
        "summary": "lifecycle conflict", "affectedResources": ["ResourceId::47"],
        "affectedEvents": [99],
        "evidenceRefs": [{"id": "ev1"}],
    }
    diagnosis = {"diagnoses": [{"conclusion": {
        "conclusionId": "conclusion-1", "status": status,
        "hypothesisRefs": ["hypothesis-1"], "factRefs": ["fact-1"],
    }}]}
    mapping = {
        "highestVerifiedLevel": level, "mappingId": "source-map-1",
        "sourceLocation": ({"file": "renderer.cpp", "function": "Render", "line": 42}
                           if level in ("S3", "S4") else {}),
        "limitations": [],
    }
    return {"findings": [finding], "findingCount": 1, "anomalyCount": 1}, diagnosis, [mapping]


class TestRecommendationModel(unittest.TestCase):
    def test_vocabularies(self):
        self.assertEqual(ACTION_TYPES, ("code_change", "api_state_correction",
                                        "instrumentation", "capture_workload",
                                        "no_change"))
        self.assertEqual(RECOMMENDATION_STATUSES,
                         ("insufficient_evidence", "actionable", "blocked"))

    def test_actionable_change_needs_evidence(self):
        with self.assertRaises(ValueError):
            recommendation([], [], "code_change", "actionable", "why")

    def test_location_must_be_attribution_verified(self):
        item = recommendation(["finding-1"], [], "code_change", "actionable", "why",
                              evidence_refs=[{"id": "e1"}],
                              source_locations=[{"file": "x.cpp"}],
                              verification_steps=["replay"])
        with self.assertRaises(ValueError):
            validate_recommendation(item)


class TestEvidenceGates(unittest.TestCase):
    def test_no_finding_produces_no_change(self):
        out = build_recommendations({"findings": [], "findingCount": 0},
                                    {"diagnoses": []})
        self.assertEqual(out["recommendations"][0]["actionType"], "no_change")

    def test_observation_never_produces_a_code_change(self):
        analysis = json.loads(POSITIVE.read_text(encoding="utf-8"))
        from rdebug.diagnostics.diagnosis_engine import build_diagnoses
        from rdebug.diagnostics.finding_builder import build_findings
        findings = build_findings(analysis)
        result = build_recommendations(findings, build_diagnoses(findings),
                                       [{"highestVerifiedLevel": "S0", "limitations": []}])
        self.assertTrue(all(r["actionType"] == "no_change"
                            for r in result["recommendations"]))

    def test_unestablished_diagnosis_gets_instrumentation(self):
        findings, diagnosis, mappings = anomaly_inputs("not_established")
        out = build_recommendations(findings, diagnosis, mappings)
        item = out["recommendations"][0]
        self.assertEqual(item["actionType"], "instrumentation")
        self.assertEqual(item["status"], "insufficient_evidence")

    def test_provisional_diagnosis_gets_capture_workload(self):
        findings, diagnosis, mappings = anomaly_inputs("provisional")
        out = build_recommendations(findings, diagnosis, mappings)
        self.assertEqual(out["recommendations"][0]["actionType"], "capture_workload")

    def test_established_s0_cannot_produce_source_location(self):
        findings, diagnosis, mappings = anomaly_inputs("established", "S0")
        out = build_recommendations(findings, diagnosis, mappings)
        item = out["recommendations"][0]
        self.assertEqual(item["actionType"], "api_state_correction")
        self.assertEqual(item["sourceLocations"], [])

    def test_established_s3_allows_file_level_change(self):
        findings, diagnosis, mappings = anomaly_inputs("established", "S3")
        out = build_recommendations(findings, diagnosis, mappings)
        item = out["recommendations"][0]
        self.assertEqual(item["actionType"], "code_change")
        self.assertEqual(item["sourceLocations"][0]["file"], "renderer.cpp")
        self.assertIsNone(item["sourceLocations"][0]["line"])


class TestPlanners(unittest.TestCase):
    def test_change_and_verification_plans_link_to_recommendation(self):
        findings, diagnosis, mappings = anomaly_inputs("established", "S4")
        recs = build_recommendations(findings, diagnosis, mappings)
        changes = build_change_plans(recs, mappings)
        checks = build_verification_plans(recs, changes, findings)
        self.assertEqual(changes["changePlanCount"], 1)
        self.assertEqual(changes["changePlans"][0]["scope"]["line"], 42)
        self.assertEqual(checks["plans"][0]["recommendationRef"],
                         recs["recommendations"][0]["recommendationId"])
        self.assertTrue(any("lifetime" in step
                            for step in checks["plans"][0]["steps"]))


class TestReportAndPipeline(unittest.TestCase):
    def test_real_positive_report_is_complete_and_consistent(self):
        analysis = json.loads(POSITIVE.read_text(encoding="utf-8"))
        result = run_diagnostic_pipeline(analysis, capture="a-d3d11-fixture.rdc")
        report = result["report"]
        self.assertEqual(set(report["sections"]), set(SECTIONS))
        self.assertEqual(result["quality"]["status"], "PASS")
        summary = report["sections"]["executive_summary"]["content"]
        self.assertEqual(summary["anomalyCount"], 0)
        self.assertEqual(summary["diagnosisCount"], 0)
        self.assertEqual(summary["highestSourceLevel"], "S0")
        self.assertTrue(all(r["actionType"] == "no_change" for r in
                            report["sections"]["recommendations"]["content"]
                            ["recommendations"]))

    def test_negative_report_has_no_change_recommendation(self):
        analysis = json.loads(NEGATIVE.read_text(encoding="utf-8"))
        report = run_diagnostic_pipeline(analysis)["report"]
        self.assertEqual(report["sections"]["findings"]["content"]["findingCount"], 0)
        self.assertEqual(report["sections"]["diagnosis"]["status"],
                         "insufficient_evidence")

    def test_markdown_is_rendered_only_from_json(self):
        analysis = json.loads(POSITIVE.read_text(encoding="utf-8"))
        result = run_diagnostic_pipeline(analysis)
        report = result["report"]
        markdown = result["markdown"]
        self.assertIn(r"schema: `rdebug-diagnostic-report/1`", markdown)
        for fid in [f["findingId"] for f in
                    report["sections"]["findings"]["content"]["findings"]]:
            self.assertIn(fid, markdown)
        self.assertNotIn("renderer.cpp", markdown)

    def test_validator_rejects_markdown_identity_mismatch(self):
        analysis = json.loads(POSITIVE.read_text(encoding="utf-8"))
        result = run_diagnostic_pipeline(analysis)
        with self.assertRaises(ValueError):
            validate_report_quality(result["report"], result["markdown"] +
                                    "\nfinding-deadbeef0000\n")


class TestBeforeAfter(unittest.TestCase):
    def test_missing_verification_evidence_is_inconclusive(self):
        analysis = json.loads(POSITIVE.read_text(encoding="utf-8"))
        before = run_diagnostic_pipeline(analysis)["report"]
        after = json.loads(json.dumps(before))
        after["sections"]["findings"]["content"]["findings"] = []
        outcome = evaluate_resolution(before, after)
        self.assertEqual(outcome["comparisons"][0]["status"],
                         "verification_inconclusive")

    def test_explicit_passing_evidence_can_resolve(self):
        analysis = json.loads(POSITIVE.read_text(encoding="utf-8"))
        before = run_diagnostic_pipeline(analysis)["report"]
        finding_id = before["sections"]["findings"]["content"]["findings"][0]["findingId"]
        after = json.loads(json.dumps(before))
        after["sections"]["findings"]["content"]["findings"] = []
        outcome = evaluate_resolution(before, after, {finding_id: {"passed": True}})
        self.assertEqual(outcome["comparisons"][0]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
