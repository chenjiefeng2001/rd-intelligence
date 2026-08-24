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


if __name__ == "__main__":
    unittest.main()
