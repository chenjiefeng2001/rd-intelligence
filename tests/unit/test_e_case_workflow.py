"""E stage: real engineered-defect case evidence and closure controls."""

import json
import pathlib
import unittest

from rdebug.diagnostics.content_oracle import compare_shader_outputs
from rdebug.diagnostics.diagnosis_engine import build_diagnoses
from rdebug.diagnostics.finding_builder import build_findings
from rdebug.diagnostics.resolution import evaluate_resolution

CASE = pathlib.Path(__file__).resolve().parent.parent.parent / "e-cases/copy_content"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestIndependentOracle(unittest.TestCase):
    def test_baseline_defect_differs_and_fix_matches(self):
        baseline = _load(CASE / "before/pixel_history.json")
        defect = _load(CASE / "after/pixel_history.json")
        fixed = _load(CASE / "after_fix/pixel_history.json")
        bad = compare_shader_outputs(baseline, defect, 11)
        good = compare_shader_outputs(baseline, fixed, 11)
        self.assertEqual(bad["status"], "different")
        self.assertEqual(good["status"], "same")
        self.assertEqual(good["maxDifference"], 0.0)
        self.assertTrue(bad["evidenceRefs"])

    def test_missing_shader_output_is_unknown(self):
        result = compare_shader_outputs({}, {}, 11)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("reason", result)


class TestRealDefectDiagnosis(unittest.TestCase):
    def test_oracle_creates_an_anomaly_and_established_diagnosis(self):
        analysis = _load(CASE / "after/trace_resource.json")
        baseline = _load(CASE / "before/pixel_history.json")
        defect = _load(CASE / "after/pixel_history.json")
        oracle = compare_shader_outputs(baseline, defect, 11)
        findings = build_findings(analysis, content_comparison=oracle)
        self.assertEqual(findings["anomalyCount"], 1)
        diagnoses = build_diagnoses(findings, {
            "establishedByOracle": True, "sourceLevel": "S4"})
        self.assertEqual(diagnoses["diagnoses"][0]["conclusion"]["status"],
                         "established")

    def test_same_oracle_creates_no_anomaly(self):
        analysis = _load(CASE / "after_fix/trace_resource.json")
        baseline = _load(CASE / "before/pixel_history.json")
        fixed = _load(CASE / "after_fix/pixel_history.json")
        oracle = compare_shader_outputs(baseline, fixed, 11)
        findings = build_findings(analysis, content_comparison=oracle)
        self.assertEqual(findings["anomalyCount"], 0)


class TestBinaryAndSourceIdentity(unittest.TestCase):
    def test_pdb_identity_matches_executable_in_both_builds(self):
        for name in ("after", "after_fix"):
            identity = _load(CASE / name / "identity.json")
            self.assertTrue(identity["pdbMatchesExecutable"], name)
            self.assertEqual(identity["codeview"]["guid"], identity["pdb"]["guid"])
            self.assertEqual(identity["codeview"]["age"], identity["pdb"]["age"])

    def test_source_hash_is_recorded_for_s4(self):
        identity = _load(CASE / "after/identity.json")
        self.assertEqual(len(identity["source"]["sha256"]), 64)
        self.assertEqual(len(identity["capture"]["sha256"]), 64)


class TestBeforeAfterClosure(unittest.TestCase):
    def test_real_reports_resolve_only_with_passing_oracle(self):
        before = _load(CASE / "after/diagnostic-report.json")
        after = _load(CASE / "after_fix/diagnostic-report.json")
        oracle = compare_shader_outputs(
            _load(CASE / "before/pixel_history.json"),
            _load(CASE / "after_fix/pixel_history.json"), 11)
        anomaly_ids = [f["findingId"] for f in
                       before["sections"]["findings"]["content"]["findings"]
                       if f["kind"] == "anomaly"]
        evidence = {fid: {"passed": oracle["status"] == "same"}
                    for fid in anomaly_ids}
        outcome = evaluate_resolution(before, after, evidence, kinds=("anomaly",))
        self.assertEqual(outcome["status"], "resolved")
        self.assertEqual(outcome["resolvedCount"], 1)

        inconclusive = evaluate_resolution(before, after, {}, kinds=("anomaly",))
        self.assertEqual(inconclusive["comparisons"][0]["status"],
                         "verification_inconclusive")


if __name__ == "__main__":
    unittest.main()
