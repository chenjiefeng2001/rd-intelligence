"""D2: a normal dependency must not be reported as a problem."""

import json
import pathlib
import unittest

from rdebug.diagnostics.finding_builder import (
    RULES,
    build_findings,
    validate_findings,
)

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
POSITIVE = REPO / "docs/validation/positive-copy-sample-a-d3d11-2026-11-19.json"
NEGATIVE = REPO / "docs/validation/capability-coverage-n3-02-2026-11-19.json"


class TestFindingRules(unittest.TestCase):
    def test_every_rule_declares_its_boundaries(self):
        for name, rule in RULES.items():
            self.assertIn("trigger", rule, name)
            self.assertIn("required_evidence", rule, name)
            self.assertIn("exclusions", rule, name)
            self.assertIn("alternatives", rule, name)
            self.assertTrue(rule["allowed"], name)
            self.assertTrue(rule["disallowed"], name)

    def test_normal_copy_sampling_is_an_observation_not_an_anomaly(self):
        payload = json.loads(POSITIVE.read_text(encoding="utf-8"))
        result = build_findings(payload)
        self.assertEqual(result["anomalyCount"], 0)
        self.assertEqual(result["findingCount"], 1)
        finding = result["findings"][0]
        self.assertEqual(finding["kind"], "observation")
        self.assertEqual(finding["severity"], "info")
        self.assertEqual(finding["status"], "inferred")
        self.assertTrue(finding["evidenceRefs"])
        self.assertIn("inferred_copy_to_sampling_dependency",
                      finding["allowedConclusions"])
        self.assertIn("confirmed_content_propagation",
                      finding["disallowedConclusions"])
        self.assertTrue(validate_findings(result))

    def test_negative_sample_produces_no_finding(self):
        payload = json.loads(NEGATIVE.read_text(encoding="utf-8"))
        result = build_findings(payload)
        self.assertEqual(result["findingCount"], 0)
        self.assertEqual(result["status"], "not_established")
        self.assertTrue(any(item["category"] == "findings"
                        for item in result["limitations"]))

    def test_lifetime_conflict_becomes_an_anomaly_with_evidence(self):
        analysis = {
            "resource": {"id": "ResourceId::7"},
            "writers": [], "readers": [], "accesses": [
                {"eventId": 20, "evidence": [{"id": "ev20"}]}],
            "lifetime": {
                "lifetimeStatus": "order_conflict",
                "endpoints": {"creation": {"eventId": 99,
                                           "evidenceRefs": [{"id": "ev99"}]}},
            },
            "causal": {"unresolved": []},
        }
        result = build_findings(analysis)
        anomaly = [f for f in result["findings"] if f["kind"] == "anomaly"]
        self.assertEqual(result["anomalyCount"], 1)
        self.assertIn({"id": "ev99"}, anomaly[0]["evidenceRefs"])
        self.assertTrue(validate_findings(result))

    def test_observed_subresource_mismatch_becomes_an_anomaly(self):
        analysis = {
            "resource": {"id": "ResourceId::7"},
            "writers": [], "readers": [], "accesses": [],
            "lifetime": {"lifetimeStatus": "unknown", "endpoints": {}},
            "causal": {"unresolved": []},
        }
        comparisons = [{
            "status": "observed", "sameSubresource": False,
            "events": [2, 11], "evidenceRefs": [{"id": "e1"}, {"id": "e2"}],
        }]
        result = build_findings(analysis, comparisons)
        self.assertEqual(result["anomalyCount"], 1)
        self.assertEqual(result["findings"][0]["category"], "subresource_mismatch")

    def test_unknown_subresource_does_not_become_a_finding(self):
        analysis = {
            "resource": {"id": "ResourceId::7"},
            "writers": [], "readers": [], "accesses": [],
            "lifetime": {"lifetimeStatus": "unknown", "endpoints": {}},
            "causal": {"unresolved": []},
        }
        comparisons = [{"status": "unknown", "reason": "subresource_not_observed"}]
        result = build_findings(analysis, comparisons)
        self.assertEqual(result["findingCount"], 0)

    def test_finding_without_evidence_is_rejected(self):
        result = {
            "findings": [{
                "findingId": "finding-x", "status": "inferred",
                "severity": "info", "priority": "P3",
                "evidenceRefs": [], "disallowedConclusions": ["x"],
            }]
        }
        with self.assertRaises(ValueError):
            validate_findings(result)

    def test_finding_id_is_stable(self):
        payload = json.loads(POSITIVE.read_text(encoding="utf-8"))
        first = build_findings(payload)["findings"][0]["findingId"]
        second = build_findings(payload)["findings"][0]["findingId"]
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("finding-"))


if __name__ == "__main__":
    unittest.main()
