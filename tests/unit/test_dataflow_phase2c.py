import json
import unittest

from rdebug.analysis.pixel_trace import trace_pixel
from rdebug.analysis.shader_trace import debug_pixel
from rdebug.model import PixelHistoryResult


class FakeAction:
    def __init__(self, eid, name, children=None):
        self.eventId = eid
        self.actionId = eid
        self.customName = name
        self.flags = 0
        self.numIndices = 3
        self.numInstances = 0
        self.children = children or []


HISTORY = {
    "resource": "ResourceId::35",
    "contextEventId": 8,
    "x": 5,
    "y": 6,
    "mip": 0,
    "slice": 0,
    "sample": 0,
    "evidence": [{"id": "a" * 12, "eventId": 8, "operation": "pixel_history"}],
    "modifications": [
        {
            "eventId": 8,
            "primitiveID": 0,
            "fragIndex": 0,
            "passed": True,
            "unboundPS": False,
            "directShaderWrite": False,
            "preMod": {"float": [0.0, 0.0, 0.0, 0.0], "depth": -1.0, "stencil": -1},
            "shaderOut": {"float": [0.2, 0.4, 0.6, 1.0], "depth": -1.0, "stencil": -1},
            "postMod": {"float": [0.2, 0.4, 0.6, 1.0], "depth": -1.0, "stencil": -1},
        }
    ],
}

PIPELINES = {
    8: {
        "eventId": 8,
        "outputTargets": [{"slot": 0, "resource": "ResourceId::35",
                           "firstMip": 0, "firstSlice": 0}],
        "depthTarget": None,
        "shaders": {"Pixel": {"resource": "ResourceId::49", "entryPoint": "main",
                              "debuggable": True}},
        "descriptors": [
            {"stage": "Pixel", "type": "ReadOnlyResource", "index": 0,
             "resource": "ResourceId::91", "sampler": None}
        ],
        "indexBuffer": None,
    }
}

USAGE = {
    "ResourceId::91": [
        {"eventId": 3, "usage": "Clear", "usageRaw": 0},
        {"eventId": 8, "usage": "PS_Resource", "usageRaw": 0},
    ]
}


class FakeSession:
    path = "cap.rdc"

    def __init__(self, usage=None):
        self.history_calls = 0
        self.pipeline_calls = []
        self._usage = usage if usage is not None else USAGE

    def pixel_history(self, rid, x, y, mip=0, slice_=0, sample=0,
                      comp_type=None, context_eid=None):
        self.history_calls += 1
        return PixelHistoryResult.parse(HISTORY)

    def pipeline(self, event_id=None):
        self.pipeline_calls.append(event_id)
        return PIPELINES[event_id]

    def root_actions(self):
        return [FakeAction(3, "ClearIt"), FakeAction(8, "Shade")]

    def usage(self, rid):
        return self._usage[rid]

    def debug_pixel(self, x, y, primitive=None, sample=None, view=None,
                    eid=None, max_steps=4096):
        self.debug_calls = getattr(self, "debug_calls", 0) + 1
        return {
            "stage": "Pixel",
            "entryPoint": "main",
            "shaderResource": "ResourceId::49",
            "pipelineObject": "ResourceId::1",
            "files": [],
            "disassembly": "ret",
            "steps": [
                {"stepIndex": 0, "nextInstruction": 0, "events": 0,
                 "callstack": [], "changes": []}
            ],
            "instInfo": [
                {"instruction": 0, "disassemblyLine": 1, "fileIndex": -1,
                 "lineStart": 0, "lineEnd": 0, "colStart": 0, "colEnd": 0}
            ],
            "inputs": [],
            "constantBlocks": [],
            "truncated": False,
        }

    def last_draw_event_id(self):
        return 8


class TestPixelHistoryResult(unittest.TestCase):
    def test_parse_accepts_dict_and_instance(self):
        p = PixelHistoryResult.parse(HISTORY)
        self.assertIs(p.payload, HISTORY)
        self.assertIs(PixelHistoryResult.parse(p), p)

    def test_parse_rejects_malformed(self):
        with self.assertRaises(TypeError):
            PixelHistoryResult.parse({"resource": "x"})
        with self.assertRaises(TypeError):
            PixelHistoryResult.parse(42)


class TestSharedHistoryInvariants(unittest.TestCase):
    def test_history_computed_once_without_shared(self):
        s = FakeSession()
        trace_pixel(s, 5, 6)
        self.assertEqual(s.history_calls, 1)

    def test_shared_history_skips_recompute_and_is_equivalent(self):
        s1 = FakeSession()
        g1 = trace_pixel(s1, 5, 6)

        s2 = FakeSession()
        g2 = trace_pixel(s2, 5, 6, history=HISTORY)

        self.assertEqual(s2.history_calls, 0)
        self.assertEqual(json.dumps(g1, sort_keys=True), json.dumps(g2, sort_keys=True))

    def test_debug_pixel_reuses_history(self):
        s = FakeSession()
        result = debug_pixel(s, 5, 6, history=HISTORY)
        self.assertEqual(s.history_calls, 0)
        self.assertEqual(result["eventId"], 8)
        self.assertEqual(result["primitive"], 0)

    def test_reads_expanded_one_level_with_evidence(self):
        s = FakeSession()
        graph = trace_pixel(s, 5, 6)

        flows = graph["resourceFlows"]
        self.assertIn("ResourceId::91", flows)
        self.assertEqual(flows["ResourceId::91"]["summary"]["writerCount"], 1)

        written_by = [e for e in graph["edges"] if e["label"] == "written_by"]
        self.assertEqual(len(written_by), 1)
        edge = written_by[0]
        self.assertEqual(edge["from"], "resource:ResourceId::91")
        self.assertEqual(edge["to"], "draw:3")
        ev = edge["evidence"][0]
        self.assertEqual(ev["resourceId"], "ResourceId::91")
        self.assertEqual(ev["eventId"], 3)
        self.assertEqual(ev["source"], "ReplayController.GetUsage")

        writer_nodes = [n for n in graph["nodes"] if n["id"] == "draw:3"]
        self.assertEqual(writer_nodes[0]["attrs"]["role"], "writer")

        self.assertEqual(sorted(set(s.pipeline_calls)), [8])

    def test_writer_not_recursed(self):
        s = FakeSession()
        graph = trace_pixel(s, 5, 6)
        flows = graph["resourceFlows"]
        self.assertEqual(list(flows.keys()), ["ResourceId::91"])
        writer_edges = [
            e
            for e in graph["edges"]
            if e["label"] == "reads" and e["from"].startswith("shader:3")
        ]
        self.assertEqual(writer_edges, [])

    def test_max_writers_cap(self):
        usage = {
            "ResourceId::91": [
                {"eventId": 100 + i, "usage": "Clear", "usageRaw": 0} for i in range(12)
            ]
            + USAGE["ResourceId::91"]
        }
        s = FakeSession(usage=usage)
        graph = trace_pixel(s, 5, 6, max_writers_per_resource=8)
        flow = graph["resourceFlows"]["ResourceId::91"]
        self.assertEqual(flow["summary"]["writersShown"], 8)
        self.assertTrue(flow["summary"]["writersTruncated"])
        written_by = [e for e in graph["edges"] if e["label"] == "written_by"]
        self.assertEqual(len(written_by), 8)


class TestDebugPixelRawPath(unittest.TestCase):
    def test_debug_pixel_without_history_computes_once(self):
        s = FakeSession()
        debug_pixel(s, 5, 6)
        self.assertEqual(s.history_calls, 1)


if __name__ == "__main__":
    unittest.main()
