"""R5.2: every inferred relation can be traced and explained on demand."""

import unittest

from rdebug.analysis.resource_access import build_access_index, build_causal_graph
from rdebug.analysis.resource_explain import (
    RULES,
    explain_relation,
    explain_relations,
    relation_id,
)

RID = "ResourceId::91"
CAP = "cap.rdc"
ROWS = [
    {"eventId": 10, "usage": "Clear", "usageRaw": 1},
    {"eventId": 20, "usage": "ColorTarget", "usageRaw": 2},
    {"eventId": 30, "usage": "PS_Resource", "usageRaw": 3},
]


def graph():
    accesses = build_access_index(ROWS, {}, RID, CAP)
    return build_causal_graph(accesses, [], RID, CAP)


class TestTraceableExplanation(unittest.TestCase):
    def test_relation_id_is_stable_and_order_independent(self):
        edge = graph()["edges"][0]
        first = relation_id(edge)
        self.assertEqual(first, relation_id(dict(reversed(list(edge.items())))))
        self.assertEqual(len(first), 12)

    def test_explanation_names_rule_evidence_and_limitations(self):
        edge = graph()["edges"][0]
        explanation = explain_relation(edge)
        self.assertEqual(explanation["rule"], RULES["writer_to_reader"])
        self.assertEqual(explanation["relationId"], relation_id(edge))
        self.assertEqual(explanation["evidenceRefs"], edge["evidenceRefs"])
        self.assertIn("resource_content_flow_not_observed",
                      explanation["limitations"])
        self.assertFalse(explanation["canConcludeContentFlow"])

    def test_order_only_never_concludes_content_flow(self):
        for edge in graph()["edges"]:
            explanation = explain_relation(edge)
            self.assertEqual(explanation["supportLevel"], "inferred_from_order")
            self.assertEqual(explanation["status"], "inferred")
            self.assertFalse(explanation["canConcludeContentFlow"])

    def test_overwrite_explanation_is_unknown(self):
        explanation = explain_relation(graph()["overwrites"][0])
        self.assertEqual(explanation["supportLevel"], "unknown")
        self.assertEqual(explanation["status"], "unknown")
        self.assertEqual(explanation["rule"], RULES["overwrite"])
        self.assertIn("coverage_not_observed", explanation["limitations"])

    def test_direct_relation_can_conclude_content_flow(self):
        direct = {
            "causalType": "writer_to_reader",
            "fromEventId": 1, "toEventId": 2,
            "supportLevel": "direct",
            "observationStatus": "observed",
            "evidenceRefs": [{"id": "ev1"}],
            "status": "observed",
        }
        explanation = explain_relation(direct)
        self.assertTrue(explanation["canConcludeContentFlow"])
        self.assertEqual(explanation["status"], "observed")

    def test_batch_form_preserves_order(self):
        edges = graph()["edges"]
        self.assertEqual([e["relationId"] for e in explain_relations(edges)],
                         [relation_id(e) for e in edges])

    def test_invalid_vocabulary_is_rejected(self):
        with self.assertRaises(ValueError):
            explain_relation({"causalType": "magic", "supportLevel": "direct"})
        with self.assertRaises(ValueError):
            explain_relation({"causalType": "writer_to_reader",
                              "supportLevel": "probably"})


if __name__ == "__main__":
    unittest.main()
