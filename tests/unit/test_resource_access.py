"""Resource Trace v2 scenarios (R2).

All scenarios are pure logic over usage rows; no GPU, no native RenderDoc
module and no new capture corpus is required. The adapter does not expose
subresource/region/coverage, so those must stay explicitly unknown rather
than being inferred from an empty observation.
"""

import unittest

from rdebug.analysis.resource_access import (
    analysis_status,
    build_access_index,
    build_causal_graph,
    build_lifetime,
    build_versions,
    classify_access,
    legacy_kind,
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


if __name__ == "__main__":
    unittest.main()
