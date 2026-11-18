import unittest

from rdebug.analysis.resource_flow import classify_usage, trace_resource
from rdebug.errors import QueryError
from rdebug.model import ResourceRef


class TestClassifyUsage(unittest.TestCase):
    def test_writes(self):
        for name in (
            "Clear",
            "ColorTarget",
            "DepthStencilTarget",
            "CopyDst",
            "CPUWrite",
            "PS_RWResource",
            "CS_RWResource",
            "ResolveDst",
        ):
            self.assertEqual(classify_usage(name), "write", name)

    def test_reads(self):
        for name in (
            "VertexBuffer",
            "IndexBuffer",
            "VS_Constants",
            "PS_Resource",
            "CS_Resource",
            "CopySrc",
            "Indirect",
            "InputTarget",
        ):
            self.assertEqual(classify_usage(name), "read", name)

    def test_other(self):
        for name in ("Unused", "Barrier", "", "Unknown"):
            self.assertEqual(classify_usage(name), "other", name)


class FakeSession:
    path = "cap.rdc"

    def __init__(self, rows):
        self._rows = rows

    def usage(self, rid):
        assert rid == "ResourceId::91"
        return self._rows

    def root_actions(self):
        class A:
            def __init__(self, eid, name, children=None):
                self.eventId = eid
                self.actionId = eid
                self.customName = name
                self.flags = 0
                self.numIndices = 0
                self.numInstances = 0
                self.children = children or []

        return [
            A(10, "ClearIt"),
            A(20, ""),
            A(30, "DrawIt"),
        ]

    def last_draw_event_id(self):
        return 30


ROWS = [
    {"eventId": 10, "usage": "Clear", "usageRaw": 33},
    {"eventId": 20, "usage": "PS_Resource", "usageRaw": 17},
    {"eventId": 30, "usage": "ColorTarget", "usageRaw": 32},
]


class TestTraceResource(unittest.TestCase):
    def test_writers_readers_split_and_evidence_invariant(self):
        result = trace_resource(FakeSession(ROWS), ResourceRef(id="ResourceId::91"))
        self.assertEqual([w["eventId"] for w in result["writers"]], [10, 30])
        self.assertEqual([r["eventId"] for r in result["readers"]], [20])
        self.assertEqual(result["summary"]["writerCount"], 2)
        self.assertEqual(result["summary"]["lastWriterEventId"], 30)

        for entry in result["writers"] + result["readers"]:
            self.assertEqual(len(entry["evidence"]), 1)
            ev = entry["evidence"][0]
            self.assertIn("id", ev)
            self.assertEqual(ev["eventId"], entry["eventId"])
            self.assertEqual(ev["resourceId"], "ResourceId::91")
            self.assertEqual(ev["source"], "ReplayController.GetUsage")

        self.assertEqual(result["writers"][0]["actionName"], "ClearIt")
        self.assertEqual(result["readers"][0]["actionName"], "")

    def test_other_hidden_by_default(self):
        rows = ROWS + [{"eventId": 40, "usage": "Barrier", "usageRaw": 38}]
        result = trace_resource(FakeSession(rows), "ResourceId::91")
        self.assertEqual(result["other"], [])
        self.assertEqual(result["summary"]["otherCount"], 1)
        result2 = trace_resource(FakeSession(rows), "ResourceId::91", include_other=True)
        self.assertEqual([o["eventId"] for o in result2["other"]], [40])

    def test_requires_resource(self):
        with self.assertRaises(QueryError):
            trace_resource(FakeSession(ROWS), "")

    def test_resource_ref_accepts_str_and_dict(self):
        self.assertEqual(ResourceRef.parse("ResourceId::7").id, "ResourceId::7")
        self.assertEqual(ResourceRef.parse({"id": "ResourceId::7"}).id, "ResourceId::7")
        self.assertEqual(
            ResourceRef.parse({"resource": "ResourceId::7", "name": "tex"}).name, "tex"
        )
        self.assertIs(ResourceRef.parse(ResourceRef(id="x")).id, "x")


class TestTraceResourceV2IsAdditive(unittest.TestCase):
    """The v2 fields are extra; no legacy key changes its name or value."""

    def test_legacy_shape_is_byte_identical_to_v1(self):
        result = trace_resource(FakeSession(ROWS), ResourceRef(id="ResourceId::91"))
        self.assertEqual(
            result["resource"], {"id": "ResourceId::91", "name": ""})
        self.assertEqual(result["contextEventId"], 30)
        self.assertEqual([w["eventId"] for w in result["writers"]], [10, 30])
        self.assertEqual([r["eventId"] for r in result["readers"]], [20])
        self.assertEqual(result["other"], [])
        self.assertEqual(
            result["summary"],
            {
                "usageCount": 3,
                "writerCount": 2,
                "readerCount": 1,
                "otherCount": 0,
                "firstWriterEventId": 10,
                "lastWriterEventId": 30,
                "lastReaderEventId": 20,
                "unknownCount": 0,
                "versionCount": 2,
            },
        )
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(result["evidence"][0]["operation"], "trace_resource")

    def test_v2_fields_are_present_and_honest(self):
        result = trace_resource(FakeSession(ROWS), ResourceRef(id="ResourceId::91"))
        self.assertEqual(result["schemaVersion"], "trace_resource/2")
        self.assertEqual(result["analysisStatus"], "partial")
        self.assertEqual([a["eventId"] for a in result["accesses"]], [10, 20, 30])
        # Writer at event 30 follows the only reader (20), so only event 10
        # can be its cause. Event order is observed; coverage is not.
        self.assertEqual(len(result["causal"]["edges"]), 1)
        self.assertEqual(result["causal"]["edges"][0]["fromEventId"], 10)
        self.assertEqual(result["causal"]["edges"][0]["status"], "inferred")
        self.assertTrue(any(u["field"] == "coverage"
                            for u in result["causal"]["unresolved"]))
        self.assertIsNone(result["lifetime"]["creationEventId"])

    def test_include_other_still_controls_both_lists(self):
        rows = ROWS + [{"eventId": 40, "usage": "Barrier", "usageRaw": 38}]
        hidden = trace_resource(FakeSession(rows), "ResourceId::91")
        shown = trace_resource(FakeSession(rows), "ResourceId::91",
                               include_other=True)
        self.assertEqual(hidden["other"], [])
        self.assertEqual(hidden["summary"]["otherCount"], 1)
        self.assertEqual([o["eventId"] for o in shown["other"]], [40])
        self.assertNotIn(40, [a["eventId"] for a in hidden["accesses"]])
        self.assertIn(40, [a["eventId"] for a in shown["accesses"]])


class TestR3EndToEndOutput(unittest.TestCase):
    """The R3 relation model must survive the public trace_resource path."""

    def test_causal_edges_and_lifetime_endpoints_are_exposed(self):
        rows = [
            {"eventId": 10, "usage": "Clear", "usageRaw": 1},
            {"eventId": 20, "usage": "PS_Resource", "usageRaw": 2},
        ]
        result = trace_resource(FakeSession(rows), ResourceRef(id="ResourceId::91"))
        edge = result["causal"]["edges"][0]
        self.assertEqual(edge["causalType"], "writer_to_reader")
        self.assertEqual(edge["supportLevel"], "inferred_from_order")
        self.assertEqual(len(edge["evidenceRefs"]), 2)
        self.assertEqual(edge["status"], "inferred")

        lifetime = result["lifetime"]
        self.assertEqual(lifetime["endpoints"]["creation"]["status"], "unknown")
        self.assertEqual(lifetime["endpoints"]["release"]["status"], "unknown")
        self.assertEqual(lifetime["interval"]["status"], "unknown")
        self.assertEqual(lifetime["lifetimeStatus"], "unknown")

    def test_legacy_summary_and_context_are_unchanged(self):
        result = trace_resource(FakeSession(ROWS), ResourceRef(id="ResourceId::91"))
        self.assertEqual(result["contextEventId"], 30)
        self.assertEqual(result["summary"]["writerCount"], 2)
        self.assertNotIn("firstReaderEventId", result["summary"])
        self.assertEqual(len(result["evidence"]), 1)


if __name__ == "__main__":
    unittest.main()
