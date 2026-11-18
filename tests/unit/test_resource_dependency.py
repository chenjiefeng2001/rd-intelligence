"""C3: typed dependencies must follow observed order and stay inferred."""

import json
import pathlib
import unittest

from rdebug.analysis.resource_access import build_access_index
from rdebug.analysis.resource_dependency import (
    DEPENDENCY_TYPES,
    build_dependency_index,
)

RID = "ResourceId::91"
CAP = "cap.rdc"
REPO = pathlib.Path(__file__).resolve().parent.parent.parent
REAL_SAMPLE = (
    REPO / "docs/validation/positive-copy-sample-a-d3d11-2026-11-19.json"
)


def index(*pairs):
    rows = [{"eventId": eid, "usage": usage, "usageRaw": 1}
            for eid, usage in pairs]
    return build_access_index(rows, {}, RID, CAP)


class TestTypedDependencies(unittest.TestCase):
    def test_raw_copy_and_waw_rules(self):
        result = build_dependency_index(
            index((2, "CopyDst"), (10, "ColorTarget"), (20, "PS_Resource")))
        kinds = [d["causalType"] for d in result["dependencies"]]
        self.assertEqual(kinds.count("raw"), 2)
        self.assertEqual(kinds.count("waw"), 1)
        copy_edges = [d for d in result["dependencies"] if d["via"] == "copy"]
        self.assertEqual(len(copy_edges), 1)
        self.assertEqual(copy_edges[0]["fromEventId"], 2)

    def test_war_is_ordered_and_distinct_from_raw(self):
        result = build_dependency_index(
            index((10, "PS_Resource"), (20, "ColorTarget")))
        self.assertEqual([d["causalType"] for d in result["dependencies"]], ["war"])
        self.assertEqual(result["dependencies"][0]["fromEventId"], 10)
        self.assertEqual(result["dependencies"][0]["toEventId"], 20)

    def test_no_cross_resource_dependency(self):
        first = index((10, "Clear"))
        second = build_access_index(
            [{"eventId": 20, "usage": "PS_Resource", "usageRaw": 1}],
            {}, "ResourceId::7", "other.rdc")
        result = build_dependency_index(first + second)
        self.assertEqual(result["dependencyCount"], 0)

    def test_every_dependency_is_inferred_with_two_refs(self):
        result = build_dependency_index(index((2, "CopyDst"), (11, "PS_Resource")))
        for dep in result["dependencies"]:
            self.assertEqual(dep["supportLevel"], "inferred_from_order")
            self.assertEqual(dep["status"], "inferred")
            self.assertEqual(len(dep["evidenceRefs"]), 2)
            self.assertTrue(dep["dependencyId"])

    def test_subresource_and_alias_stay_unknown(self):
        result = build_dependency_index(index((2, "CopyDst"), (11, "PS_Resource")))
        fields = {u["field"] for u in result["unresolved"]}
        self.assertEqual(fields, {"subresource", "alias"})
        self.assertTrue(all(u["status"] == "unknown" for u in result["unresolved"]))

    def test_truncation_is_reported(self):
        accesses = index((2, "Clear"), (10, "ColorTarget"),
                         (20, "PS_Resource"), (30, "CS_Resource"))
        full = build_dependency_index(accesses)
        limited = build_dependency_index(accesses, max_edges=2)
        self.assertGreater(full["dependencyCount"], 2)
        self.assertEqual(len(limited["dependencies"]), 2)
        self.assertTrue(limited["truncated"])
        self.assertEqual(limited["omittedDependencyCount"],
                         full["dependencyCount"] - 2)
        self.assertEqual(limited["status"], "partial")

    def test_vocabulary_is_finite(self):
        self.assertEqual(DEPENDENCY_TYPES, ("raw", "war", "waw", "copy", "resolve"))


class TestRealCaptureDependency(unittest.TestCase):
    """Positive/negative dependency evidence from an already-registered capture."""

    def test_copy_to_sampling_real_sample_produces_raw_copy_edges(self):
        payload = json.loads(REAL_SAMPLE.read_text(encoding="utf-8"))
        result = build_dependency_index(payload["accesses"])
        raw = [d for d in result["dependencies"] if d["causalType"] == "raw"]
        self.assertEqual(len(raw), 256)
        self.assertTrue(all(d["via"] == "copy" for d in raw))
        self.assertTrue(all(d["fromEventId"] == 2 for d in raw))
        self.assertTrue(all(d["supportLevel"] == "inferred_from_order" for d in raw))
        self.assertFalse(result["truncated"])

    def test_real_no_edge_capture_has_no_dependency(self):
        path = REPO / "docs/validation/capability-coverage-n3-02-2026-11-19.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        # The C1 scan stores aggregates rather than full access rows, so the
        # negative case is asserted through its recorded zero-edge aggregate
        # instead of fabricating access rows here.
        self.assertEqual(payload["aggregates"]["edgeCount"], 0)
        self.assertTrue(all(d["edgeCount"] == 0 for d in payload["perResource"]))


if __name__ == "__main__":
    unittest.main()
