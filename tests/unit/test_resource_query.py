"""R5.3: query results preserve every status and never claim completeness."""

import unittest

from rdebug.analysis.resource_access import build_access_index
from rdebug.analysis.resource_explain import relation_id
from rdebug.analysis.resource_flow import trace_resource
from rdebug.analysis.resource_query import (
    query_accesses,
    query_by_status,
    query_explanation,
    query_lifetime,
    query_relations,
    query_relations_stream,
    summarize_query_relations,
)

RID = "ResourceId::91"
ROWS = [
    {"eventId": 10, "usage": "Clear", "usageRaw": 1},
    {"eventId": 20, "usage": "ColorTarget", "usageRaw": 2},
    {"eventId": 30, "usage": "PS_Resource", "usageRaw": 3},
    {"eventId": 40, "usage": "CS_Resource", "usageRaw": 4},
]


class FakeSession:
    path = "cap.rdc"

    def usage(self, rid):
        return ROWS

    def root_actions(self):
        return []

    def last_draw_event_id(self):
        return 40


def result():
    return trace_resource(FakeSession(), RID)


class TestQueryDoesNotRewriteStatus(unittest.TestCase):
    def test_access_filter_preserves_status(self):
        r = result()
        out = query_accesses(r, access_type="clear")
        self.assertEqual(out["matched"], 1)
        self.assertEqual(out["accesses"][0]["status"], "observed")
        self.assertTrue(out["partialBySelection"])
        self.assertEqual(out["analysisStatus"], r["analysisStatus"])

    def test_unknown_evidence_stays_unknown_after_filter(self):
        r = result()
        r["accesses"][0]["status"] = "unknown"
        out = query_by_status(r, evidence_status="unknown")
        self.assertEqual(out["matched"], 1)
        self.assertEqual(out["accesses"][0]["status"], "unknown")
        self.assertTrue(out["partialBySelection"])

    def test_relation_filter_keeps_inferred_support(self):
        out = query_relations(result(), support_level="inferred_from_order")
        self.assertEqual(out["matched"], 4)
        for edge in out["relations"]:
            self.assertEqual(edge["supportLevel"], "inferred_from_order")
            self.assertEqual(edge["status"], "inferred")
        self.assertFalse(out["truncatedSource"])

    def test_truncated_source_is_visible_in_query(self):
        r = result()
        r["causal"]["truncated"] = True
        self.assertTrue(query_relations(r)["truncatedSource"])

    def test_lifetime_query_reports_missing_resource_as_unknown(self):
        out = query_lifetime(result(), resource="ResourceId::999")
        self.assertEqual(out["matched"], 0)
        self.assertEqual(out["status"], "unknown")
        self.assertIsNone(out["lifetime"])

    def test_explanation_query_by_id_and_endpoints(self):
        r = result()
        first = r["causal"]["edges"][0]
        by_id = query_explanation(r, relation_id_value=relation_id(first))
        by_events = query_explanation(r, from_event_id=first["fromEventId"],
                                      to_event_id=first["toEventId"])
        self.assertEqual(by_id["matched"], 1)
        self.assertEqual(by_events["matched"], 1)
        self.assertEqual(by_id["explanation"]["relationId"],
                         by_events["explanation"]["relationId"])
        self.assertFalse(by_id["explanation"]["canConcludeContentFlow"])

    def test_missing_relation_is_unknown_not_empty_success(self):
        out = query_explanation(result(), relation_id_value="0" * 12)
        self.assertEqual(out["matched"], 0)
        self.assertEqual(out["status"], "unknown")
        self.assertEqual(out["reason"], "relation_not_found")

    def test_analysis_status_filter_does_not_promote_a_partial_result(self):
        r = result()
        out = query_by_status(r, analysis_status="complete")
        self.assertEqual(out["matched"], 0)
        self.assertTrue(out["partialBySelection"])
        self.assertEqual(out["analysisStatus"], r["analysisStatus"])


class TestPushedDownQuery(unittest.TestCase):
    """R6.4: filtering must not materialize the whole graph, nor lose edges."""

    def test_stream_matches_filtered_full_edges(self):
        r = result()
        accesses = build_access_index(ROWS, {}, RID, "cap.rdc")
        first = r["causal"]["edges"][0]
        full = query_relations(r, from_event_id=first["fromEventId"])
        streamed = list(query_relations_stream(
            accesses, from_event_min=first["fromEventId"],
            from_event_max=first["fromEventId"]))
        self.assertEqual(
            [(e["fromEventId"], e["toEventId"]) for e in streamed],
            [(e["fromEventId"], e["toEventId"]) for e in full["relations"]])
        for item in streamed:
            self.assertNotIn("evidence", item)
            self.assertEqual(item["supportLevel"], "inferred_from_order")

    def test_stream_truncation_stays_explicit(self):
        accesses = build_access_index(ROWS, {}, RID, "cap.rdc")
        stats = {}
        edges = list(query_relations_stream(accesses, stats=stats, max_edges=1))
        self.assertEqual(len(edges), 1)
        self.assertEqual(stats["emitted"], 1)
        self.assertGreater(stats["omitted"], 0)

    def test_summary_counts_match_materialized_edges(self):
        r = result()
        summary = summarize_query_relations(
            build_access_index(ROWS, {}, RID, "cap.rdc"))
        self.assertEqual(summary["relationCount"],
                         len(r["causal"]["edges"]))
        self.assertEqual(summary["status"], "inferred")

    def test_summary_selection_marks_partial(self):
        accesses = build_access_index(ROWS, {}, RID, "cap.rdc")
        selected = summarize_query_relations(accesses, resource=RID)
        missing = summarize_query_relations(accesses, resource="ResourceId::999")
        self.assertFalse(selected["partialBySelection"])
        self.assertTrue(missing["partialBySelection"])
        self.assertEqual(missing["relationCount"], 0)

    def test_event_range_filter_is_applied_before_generation(self):
        accesses = build_access_index(ROWS, {}, RID, "cap.rdc")
        streamed = list(query_relations_stream(accesses, to_event_max=30))
        self.assertTrue(streamed)
        self.assertTrue(all(e["toEventId"] <= 30 for e in streamed))


if __name__ == "__main__":
    unittest.main()
