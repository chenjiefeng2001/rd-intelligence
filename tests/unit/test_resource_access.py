"""Resource Trace v2 scenarios (R2).

All scenarios are pure logic over usage rows; no GPU, no native RenderDoc
module and no new capture corpus is required. The adapter does not expose
subresource/region/coverage, so those must stay explicitly unknown rather
than being inferred from an empty observation.
"""

import unittest

from rdebug.analysis.resource_access import (
    ACCESS_ROLES,
    CAUSAL_TYPES,
    INFORMATION_STATUSES,
    SUPPORT_LEVELS,
    analysis_status,
    build_access_index,
    build_causal_graph,
    build_lifetime,
    build_versions,
    classify_access,
    group_accesses_by_resource,
    iter_writer_reader_edges,
    legacy_kind,
    relation,
)

CAPTURE = "cap.rdc"
RID = "ResourceId::91"


def index(rows, names=None):
    actions = {eid: {"name": name} for eid, name in (names or {}).items()}
    return build_access_index(rows, actions, RID, CAPTURE)


def rows(*pairs):
    return [
        {"eventId": eid, "usage": usage, "usageRaw": 1}
        for eid, usage in pairs
    ]


class TestClassificationIsBackwardCompatible(unittest.TestCase):
    def test_legacy_kind_matches_pre_v2_mapping(self):
        cases = {
            "Clear": ("clear", "write"),
            "ColorTarget": ("write", "write"),
            "PS_RWResource": ("readwrite", "write"),
            "CopyDst": ("copy", "write"),
            "CopySrc": ("copy", "read"),
            "VS_Constants": ("read", "read"),
            "CS_Resource": ("read", "read"),
            "VertexBuffer": ("read", "read"),
            "Unused": ("unknown", "other"),
            "": ("unknown", "other"),
        }
        for name, expected in cases.items():
            self.assertEqual((classify_access(name), legacy_kind(name)), expected, name)


class TestEightScenarios(unittest.TestCase):
    def test_1_single_writer_single_reader(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource")))
        versions = build_versions(accesses, RID, CAPTURE)
        graph = build_causal_graph(accesses, versions, RID, CAPTURE)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["fromEventId"], 10)
        self.assertEqual(graph["edges"][0]["toEventId"], 20)
        self.assertEqual(graph["edges"][0]["status"], "inferred")
        self.assertTrue(any(u["field"] == "coverage" for u in graph["unresolved"]))

    def test_2_multiple_writers_in_event_order(self):
        accesses = index(rows((30, "ColorTarget"), (10, "Clear"), (20, "CopyDst"),
                               (40, "ColorTarget"), (50, "PS_Resource")))
        self.assertEqual([a["eventId"] for a in accesses], [10, 20, 30, 40, 50])
        versions = build_versions(accesses, RID, CAPTURE)
        self.assertEqual([v["eventId"] for v in versions], [10, 20, 30, 40])
        self.assertEqual([v["version"] for v in versions], [1, 2, 3, 4])
        graph = build_causal_graph(accesses, versions, RID, CAPTURE)
        self.assertEqual(len(graph["overwrites"]), 3)
        self.assertEqual(graph["overwrites"][0]["supersededEventId"], 10)
        self.assertEqual(graph["overwrites"][0]["status"], "unknown")

    def test_3_copy_then_read(self):
        accesses = index(rows((10, "CopyDst"), (20, "CopySrc")))
        self.assertEqual(accesses[0]["accessType"], "copy")
        self.assertEqual(accesses[1]["legacyKind"], "read")
        graph = build_causal_graph(accesses, build_versions(accesses, RID, CAPTURE),
                                   RID, CAPTURE)
        self.assertEqual(graph["edges"][0]["kind"], "writer_to_reader")
        self.assertTrue(any(u["field"] == "region" for u in graph["unresolved"]))

    def test_4_clear_then_read(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource")))
        self.assertEqual(accesses[0]["accessType"], "clear")
        self.assertEqual(build_versions(accesses, RID, CAPTURE)[0]["eventId"], 10)
        self.assertTrue(any(u["field"] == "subresource" for u in
                            build_causal_graph(accesses, [], RID, CAPTURE)["unresolved"]))

    def test_5_partial_buffer_write_is_not_a_new_version_claim(self):
        accesses = index(rows((10, "CPUWrite"), (20, "CPUWrite")))
        versions = build_versions(accesses, RID, CAPTURE)
        self.assertEqual(len(versions), 2)
        for version in versions:
            self.assertEqual(version["coverage"], "unknown")
            self.assertEqual(version["status"], "inferred")

    def test_6_mip_layer_is_unknown_not_merged(self):
        accesses = index(rows((10, "ColorTarget"), (20, "ColorTarget")))
        for entry in accesses:
            self.assertIsNone(entry["subresource"])
        versions = build_versions(accesses, RID, CAPTURE)
        self.assertEqual(len(versions), 2)
        # No claim that the two writes touched the same subresource.
        self.assertTrue(all(v["status"] == "inferred" for v in versions))

    def test_7_multiple_readers_share_one_writer(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource"), (30, "CS_Resource")))
        graph = build_causal_graph(accesses, build_versions(accesses, RID, CAPTURE),
                                   RID, CAPTURE)
        self.assertEqual([e["toEventId"] for e in graph["edges"]], [20, 30])
        self.assertEqual({e["fromEventId"] for e in graph["edges"]}, {10})

    def test_8_superseded_writer_is_still_visible(self):
        accesses = index(rows((10, "Clear"), (20, "ColorTarget"), (30, "PS_Resource")))
        versions = build_versions(accesses, RID, CAPTURE)
        self.assertEqual([v["eventId"] for v in versions], [10, 20])
        graph = build_causal_graph(accesses, versions, RID, CAPTURE)
        self.assertEqual(graph["overwrites"][0]["supersededEventId"], 10)
        self.assertEqual(graph["edges"][0]["fromEventId"], 10)


class TestNegativeControls(unittest.TestCase):
    def test_malformed_row_is_kept_as_unknown(self):
        accesses = index([{"eventId": 10}, {"eventId": 20, "usage": "Clear"}])
        self.assertEqual(len(accesses), 2)
        bad = next(a for a in accesses if a["eventId"] is None)
        self.assertEqual(bad["status"], "unknown")
        self.assertEqual(bad["evidence"][0]["status"], "unknown")

    def test_unrecognised_usage_is_unknown_and_hidden_as_other(self):
        accesses = index(rows((10, "BrandNewUsage")))
        self.assertEqual(accesses[0]["accessType"], "unknown")
        self.assertEqual(accesses[0]["legacyKind"], "other")
        self.assertEqual(analysis_status(accesses, {"unresolved": [1]}), "partial")

    def test_empty_access_never_reports_complete(self):
        self.assertEqual(analysis_status([], {"unresolved": []}), "unknown")

    def test_lifetime_reports_creation_as_unknown(self):
        lifetime = build_lifetime(index(rows((10, "Clear"), (20, "PS_Resource"))))
        self.assertIsNone(lifetime["creationEventId"])
        self.assertEqual(lifetime["status"], "partial")
        self.assertEqual(lifetime["writeCount"], 1)
        self.assertEqual(lifetime["readCount"], 1)


class TestRelationModel(unittest.TestCase):
    """R3.1: finite vocabularies and a typed relation builder."""

    def test_enumerations_are_finite_and_non_probabilistic(self):
        self.assertEqual(INFORMATION_STATUSES,
                         ("observed", "inferred", "unknown"))
        self.assertEqual(SUPPORT_LEVELS,
                         ("direct", "inferred_from_order", "unknown"))
        self.assertIn("writer_to_reader", CAUSAL_TYPES)
        self.assertEqual(set(ACCESS_ROLES), {"read", "write", "readwrite", "other"})

    def test_relation_carries_its_evidence_boundary(self):
        r = relation("writer_to_reader", 10, 20, [{"id": "abc"}],
                     "inferred_from_order", "event order only",
                     "observed")
        self.assertEqual(r["evidenceRefs"], [{"id": "abc"}])
        self.assertEqual(r["supportLevel"], "inferred_from_order")
        self.assertEqual(r["observationStatus"], "observed")
        self.assertEqual(r["status"], "inferred")
        self.assertEqual(r["reason"], "event order only")

    def test_direct_relation_is_observed_and_unknown_is_not_a_verdict(self):
        direct = relation("writer_to_reader", 1, 2, [], "direct", "explicit", "observed")
        unknown = relation("writer_to_reader", 1, 2, [], "unknown", "no data", "unknown")
        self.assertEqual(direct["status"], "observed")
        self.assertEqual(unknown["status"], "unknown")

    def test_invalid_vocabulary_is_rejected(self):
        with self.assertRaises(ValueError):
            relation("writer_to_reader", 1, 2, [], "high_confidence", "x", "observed")
        with self.assertRaises(ValueError):
            relation("content_propagation", 1, 2, [], "direct", "x", "observed")
        with self.assertRaises(ValueError):
            relation("writer_to_reader", 1, 2, [], "direct", "x", "probably")


class TestCausalBoundary(unittest.TestCase):
    """R3.2: event order alone must never become an observed data dependency."""

    def test_order_only_edges_are_not_observed_or_direct(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource")))
        graph = build_causal_graph(accesses, build_versions(accesses, RID, CAPTURE),
                                   RID, CAPTURE)
        self.assertTrue(graph["edges"])
        for edge in graph["edges"]:
            self.assertEqual(edge["status"], "inferred")
            self.assertEqual(edge["supportLevel"], "inferred_from_order")
            self.assertNotEqual(edge["supportLevel"], "direct")
            self.assertEqual(edge["causalType"], "writer_to_reader")
            self.assertIn("reason", edge)
            self.assertEqual(edge["observationStatus"], "observed")

    def test_edges_carry_evidence_refs_for_both_endpoints(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource")))
        edge = build_causal_graph(accesses, [], RID, CAPTURE)["edges"][0]
        self.assertEqual(len(edge["evidenceRefs"]), 2)
        self.assertEqual(len(edge["evidence"]), 1)  # R2 field unchanged
        for ref in edge["evidenceRefs"]:
            self.assertIn("id", ref)

    def test_overwrite_is_explicitly_unknown(self):
        accesses = index(rows((10, "Clear"), (20, "ColorTarget")))
        overwrite = build_causal_graph(accesses, [], RID, CAPTURE)["overwrites"][0]
        self.assertEqual(overwrite["supportLevel"], "unknown")
        self.assertEqual(overwrite["status"], "unknown")
        self.assertIn("coverage", overwrite["reason"])

    def test_row_order_does_not_change_an_inferred_edge(self):
        # Row arrival order is not an event-order fact. build_access_index
        # sorts by eventId, so shuffled input must produce the same edge,
        # still inferred -- never a deterministic content claim.
        forward = index(rows((20, "PS_Resource"), (10, "Clear")))
        reverse = index(rows((10, "Clear"), (20, "PS_Resource")))
        a = build_causal_graph(forward, [], RID, CAPTURE)["edges"]
        b = build_causal_graph(reverse, [], RID, CAPTURE)["edges"]
        self.assertEqual(a, b)
        self.assertEqual(a[0]["status"], "inferred")
        self.assertEqual(a[0]["supportLevel"], "inferred_from_order")

    def test_malformed_writer_produces_no_edge(self):
        accesses = index([{"eventId": 10}, {"eventId": 20, "usage": "PS_Resource"}])
        graph = build_causal_graph(accesses, [], RID, CAPTURE)
        self.assertEqual(graph["edges"], [])


class TestLifetimeBoundary(unittest.TestCase):
    """R3.3: missing lifecycle endpoints stay explicit, never inferred."""

    def test_no_lifecycle_events_keeps_r2_shape(self):
        lifetime = build_lifetime(index(rows((10, "Clear"), (20, "PS_Resource"))))
        self.assertEqual(lifetime["status"], "partial")
        self.assertIsNone(lifetime["creationEventId"])
        self.assertIsNone(lifetime["destructionEventId"])
        self.assertEqual(lifetime["endpoints"]["creation"]["status"], "unknown")
        self.assertEqual(lifetime["endpoints"]["creation"]["reason"],
                         "creation_event_not_observed")
        self.assertEqual(lifetime["endpoints"]["release"]["status"], "unknown")
        self.assertEqual(lifetime["interval"]["status"], "unknown")
        self.assertEqual(lifetime["lifetimeStatus"], "unknown")

    def test_creation_observed_release_missing(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource")))
        lifetime = build_lifetime(accesses, [{"eventId": 5, "kind": "create"}])
        self.assertEqual(lifetime["endpoints"]["creation"]["status"], "observed")
        self.assertEqual(lifetime["creationEventId"], 5)
        self.assertEqual(lifetime["endpoints"]["release"]["status"], "unknown")
        self.assertEqual(lifetime["interval"]["status"], "partial")
        self.assertEqual(lifetime["lifetimeStatus"], "partial")

    def test_release_observed_creation_missing(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource")))
        lifetime = build_lifetime(accesses, [{"eventId": 30, "kind": "release"}])
        self.assertEqual(lifetime["endpoints"]["creation"]["status"], "unknown")
        self.assertEqual(lifetime["endpoints"]["release"]["status"], "observed")
        self.assertEqual(lifetime["destructionEventId"], 30)
        self.assertEqual(lifetime["interval"]["status"], "partial")

    def test_both_endpoints_observed(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource")))
        lifetime = build_lifetime(accesses, [
            {"eventId": 5, "kind": "create", "evidence": [{"id": "c1"}]},
            {"eventId": 30, "kind": "release", "evidence": [{"id": "r1"}]},
        ])
        self.assertEqual(lifetime["interval"]["status"], "observed")
        self.assertEqual(lifetime["lifetimeStatus"], "observed")
        self.assertEqual(lifetime["endpoints"]["creation"]["evidenceRefs"], [{"id": "c1"}])
        self.assertEqual(lifetime["endpoints"]["release"]["evidenceRefs"], [{"id": "r1"}])

    def test_multiple_creates_are_separate_instances(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource"),
                              (40, "ColorTarget"), (50, "CS_Resource")))
        lifetime = build_lifetime(accesses, [
            {"eventId": 5, "kind": "create"},
            {"eventId": 30, "kind": "release"},
            {"eventId": 35, "kind": "create"},
            {"eventId": 60, "kind": "release"},
        ])
        self.assertEqual(lifetime["lifetimeStatus"], "multiple")
        self.assertEqual(len(lifetime["instances"]), 2)
        self.assertEqual(lifetime["instances"][0]["accessEventIds"], [10, 20])
        self.assertEqual(lifetime["instances"][1]["accessEventIds"], [40, 50])

    def test_order_conflict_is_not_silently_resolved(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource")))
        lifetime = build_lifetime(accesses, [{"eventId": 99, "kind": "create"}])
        self.assertEqual(lifetime["lifetimeStatus"], "order_conflict")
        self.assertEqual(lifetime["interval"]["status"], "order_conflict")
        self.assertEqual(lifetime["endpoints"]["creation"]["status"], "observed")

    def test_empty_access_window_is_unknown_not_complete(self):
        lifetime = build_lifetime([])
        self.assertEqual(lifetime["lifetimeStatus"], "unknown")
        self.assertEqual(lifetime["endpoints"]["firstAccess"]["status"], "unknown")
        self.assertEqual(lifetime["instances"][0]["accessEventIds"], [])


class TestScaledGraphIsSemanticallyEquivalent(unittest.TestCase):
    """R5.1: optimization must not drop or invent a single relation."""

    @staticmethod
    def _reference_pairs(accesses):
        writers = [a["eventId"] for a in accesses if a["legacyKind"] == "write"
                   and a["eventId"] is not None]
        readers = [a["eventId"] for a in accesses if a["legacyKind"] == "read"
                   and a["eventId"] is not None]
        return {(w, r) for w in writers for r in readers if w < r}

    def test_edges_match_the_original_enumeration(self):
        source = rows((10, "Clear"), (20, "PS_Resource"), (30, "ColorTarget"),
                      (40, "CS_Resource"), (50, "CopyDst"), (60, "PS_Resource"))
        accesses = index(source)
        graph = build_causal_graph(accesses, [], RID, CAPTURE)
        actual = {(e["fromEventId"], e["toEventId"]) for e in graph["edges"]}
        self.assertEqual(actual, self._reference_pairs(accesses))
        self.assertEqual(graph["truncated"], False)
        self.assertEqual(graph["omittedEdgeCount"], 0)

    def test_duplicate_rows_do_not_duplicate_edges(self):
        source = rows((10, "Clear"), (10, "Clear"), (20, "PS_Resource"),
                      (20, "PS_Resource"))
        graph = build_causal_graph(index(source), [], RID, CAPTURE)
        self.assertEqual(len(graph["edges"]), 1)

    def test_edges_never_cross_a_resource_boundary(self):
        first = index(rows((10, "Clear"), (20, "PS_Resource")))
        second = build_access_index(
            rows((30, "Clear"), (40, "PS_Resource")), {}, "ResourceId::7", "other.rdc")
        groups = group_accesses_by_resource(first + second)
        self.assertEqual(set(groups), {"ResourceId::91", "ResourceId::7"})
        graph = build_causal_graph(first + second, [], RID, CAPTURE)
        for edge in graph["edges"]:
            self.assertEqual(edge["resourceId"], edge["evidence"][0]["resourceId"])

    def test_lazy_iterator_matches_materialized_graph(self):
        accesses = index(rows((10, "Clear"), (20, "PS_Resource"),
                              (30, "ColorTarget"), (40, "CS_Resource")))
        lazy = [(e["fromEventId"], e["toEventId"])
                for e in iter_writer_reader_edges(accesses)]
        eager = [(e["fromEventId"], e["toEventId"])
                 for e in build_causal_graph(accesses, [], RID, CAPTURE)["edges"]]
        self.assertEqual(lazy, eager)

    def test_lightweight_stream_covers_exactly_the_same_relations(self):
        accesses = index(rows((10, "Clear"), (20, "ColorTarget"),
                              (30, "PS_Resource"), (40, "CS_Resource")))
        full = build_causal_graph(accesses, [], RID, CAPTURE)["edges"]
        light = list(iter_writer_reader_edges(accesses, lightweight=True))
        self.assertEqual(len(light), len(full))
        self.assertEqual(
            [(e["fromEventId"], e["toEventId"]) for e in light],
            [(e["fromEventId"], e["toEventId"]) for e in full])
        for item in light:
            self.assertNotIn("evidence", item)
            self.assertEqual(item["supportLevel"], "inferred_from_order")

    def test_truncation_is_reported_not_silent(self):
        accesses = index(rows((10, "Clear"), (20, "ColorTarget"),
                              (30, "PS_Resource"), (40, "CS_Resource")))
        full = build_causal_graph(accesses, [], RID, CAPTURE)
        limited = build_causal_graph(accesses, [], RID, CAPTURE, max_edges=2)
        self.assertEqual(len(full["edges"]), 4)
        self.assertEqual(len(limited["edges"]), 2)
        self.assertTrue(limited["truncated"])
        self.assertEqual(limited["omittedEdgeCount"], 2)
        self.assertEqual(limited["edgeLimit"], 2)
        self.assertEqual(limited["status"], "partial")
        self.assertEqual(analysis_status(accesses, limited), "partial")
        # Relation ids belong to the R5.2 explanation layer, not the edge.
        for edge in full["edges"]:
            self.assertNotIn("relationId", edge)


if __name__ == "__main__":
    unittest.main()
