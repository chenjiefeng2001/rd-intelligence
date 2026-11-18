"""D3: facts, hypotheses, alternatives and conclusions stay separate."""

import unittest

from rdebug.diagnostics.diagnosis_engine import (
    build_diagnoses,
    build_diagnosis,
)
from rdebug.diagnostics.diagnosis_model import (
    CONCLUSION_STATUSES,
    DIAGNOSIS_RELATIONS,
    FACT_STATUSES,
    HYPOTHESIS_STATUSES,
    chain,
    conclusion,
    fact,
    hypothesis,
    validate_chain,
)


class TestDiagnosisModel(unittest.TestCase):
    def test_vocabularies_are_separate(self):
        self.assertEqual(FACT_STATUSES, ("observed", "inferred", "unverified"))
        self.assertNotIn("observed", CONCLUSION_STATUSES)
        self.assertNotIn("established", HYPOTHESIS_STATUSES)
        self.assertIn("challenged_by", DIAGNOSIS_RELATIONS)

    def test_fact_requires_evidence(self):
        with self.assertRaises(ValueError):
            fact("unsupported claim", "inferred", [])
        f = fact("CopyDst precedes reads", "inferred", [{"id": "ev1"}])
        self.assertTrue(f["factId"].startswith("fact-"))
        self.assertEqual(f["evidenceStatus"], "inferred")

    def test_conclusion_cannot_carry_probability(self):
        c = conclusion("provisional", ["hypothesis-x"], ["fact-x"], "reason")
        self.assertIsNone(c["probabilisticConfidence"])
        with self.assertRaises(ValueError):
            conclusion("established", ["h"], ["f"], "")

    def test_chain_validation_enforces_traceability(self):
        f = fact("observed ordering", "inferred", [{"id": "ev1"}])
        h = hypothesis("a cause", status="supported")
        c = conclusion("provisional", [h["hypothesisId"]], [f["factId"]], "reason")
        item = chain("finding-1", [f], [h], [], [
            {"type": "explained_by", "from": "finding-1", "to": h["hypothesisId"]}],
            c)
        self.assertTrue(validate_chain(item))
        bad = conclusion("provisional", ["hypothesis-missing"], [f["factId"]], "r")
        with self.assertRaises(ValueError):
            validate_chain(chain("finding-1", [f], [h], [], [], bad))


class TestDiagnosisEngine(unittest.TestCase):
    def test_observation_produces_no_diagnosis(self):
        finding = {
            "findingId": "finding-obs", "kind": "observation",
            "category": "copy_sampling_dependency",
            "evidenceRefs": [{"id": "ev1"}],
        }
        self.assertIsNone(build_diagnosis(finding))
        result = build_diagnoses({"findings": [finding]})
        self.assertEqual(result["diagnosisCount"], 0)
        self.assertTrue(result["observationOnly"])

    def test_zero_findings_produce_no_diagnosis(self):
        result = build_diagnoses({"findings": []})
        self.assertEqual(result["diagnosisCount"], 0)
        self.assertEqual(result["status"], "not_established")

    def test_anomaly_produces_provisional_chain(self):
        finding = {
            "findingId": "finding-anomaly", "kind": "anomaly",
            "category": "subresource_mismatch",
            "evidenceRefs": [{"id": "ev1"}, {"id": "ev2"}],
        }
        item = build_diagnosis(finding)
        self.assertIsNotNone(item)
        self.assertTrue(item["facts"])
        self.assertEqual(item["conclusion"]["status"], "provisional")
        self.assertTrue(item["conclusion"]["hypothesisRefs"])
        self.assertTrue(validate_chain(item))

    def test_alternatives_have_discriminating_checks(self):
        finding = {
            "findingId": "finding-anomaly", "kind": "anomaly",
            "category": "lifetime_order_conflict",
            "evidenceRefs": [{"id": "ev1"}],
        }
        item = build_diagnosis(finding)
        alts = [h for h in item["hypotheses"]
                if h["hypothesisId"] in item["conclusion"]["alternativeRefs"]]
        self.assertGreaterEqual(len(alts), 1)
        for alt in alts:
            self.assertTrue(alt["discriminatingChecks"])
            self.assertTrue(alt["missingEvidence"])

    def test_unknown_rule_is_not_promoted(self):
        finding = {
            "findingId": "finding-x", "kind": "anomaly",
            "category": "unknown_category", "evidenceRefs": [{"id": "ev1"}],
        }
        item = build_diagnosis(finding)
        self.assertEqual(item["conclusion"]["status"], "not_established")
        self.assertEqual(item["conclusion"]["hypothesisRefs"], [])


if __name__ == "__main__":
    unittest.main()
