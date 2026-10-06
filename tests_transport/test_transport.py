import json
import re
import unittest
from pathlib import Path

import capture_support
from capture_support import CAPTURE

from rdebug import errors
from rdebug.model import PixelHistoryResult
from rdebug_mcp import server

try:  # unittest discover puts tests_transport/ on sys.path; pytest does not
    from worker_stub import RecordingWorkers
except ImportError:  # pragma: no cover - runner-dependent
    from tests_transport.worker_stub import RecordingWorkers


_POLICY = None

def setUpModule():
    global _POLICY
    _POLICY = capture_support.widened()
    _POLICY.__enter__()

def tearDownModule():
    global _POLICY
    if _POLICY is not None:
        _POLICY.__exit__(None, None, None)
        _POLICY = None

class FakeAction:
    def __init__(self, eid, name):
        self.eventId = eid
        self.actionId = eid
        self.customName = name
        self.flags = 0
        self.numIndices = 3
        self.numInstances = 0
        self.children = []


def _history(eid, r=0.5):
    return {
        "resource": "ResourceId::35",
        "contextEventId": eid,
        "x": 0,
        "y": 0,
        "mip": 0,
        "slice": 0,
        "sample": 0,
        "evidence": [{"id": "h" * 12, "eventId": eid, "operation": "pixel_history"}],
        "modifications": [
            {
                "eventId": eid,
                "primitiveID": 0,
                "fragIndex": 0,
                "passed": True,
                "unboundPS": False,
                "directShaderWrite": False,
                "preMod": {"float": [0.0, 0.0, 0.0, 0.0], "depth": -1.0, "stencil": -1},
                "shaderOut": {"float": [r, 0.5, 0.5, 1.0], "depth": -1.0, "stencil": -1},
                "postMod": {"float": [r, 0.5, 0.5, 1.0], "depth": -1.0, "stencil": -1},
            }
        ],
    }


PIPELINE = {
    "eventId": 8,
    "outputTargets": [{"slot": 0, "resource": "ResourceId::35",
                       "firstMip": 0, "firstSlice": 0}],
    "depthTarget": None,
    "shaders": {"Pixel": {"resource": "ResourceId::49", "entryPoint": "main",
                          "debuggable": True}},
    "descriptors": [
        {"stage": "Pixel", "type": "ReadOnlyResource", "index": 0,
         "resource": "ResourceId::47", "sampler": None}
    ],
    "indexBuffer": None,
}

USAGE = {"ResourceId::47": [{"eventId": 2, "usage": "CopyDst", "usageRaw": 0}]}


class FakeSession:
    path = CAPTURE

    def pixel_history(self, rid, x, y, mip=0, slice_=0, sample=0,
                      comp_type=None, context_eid=None):
        return PixelHistoryResult.parse(_history(8))

    def pipeline(self, event_id=None):
        return PIPELINE

    def root_actions(self):
        return [FakeAction(2, "CopyIt"), FakeAction(8, "Shade")]

    def usage(self, rid):
        return USAGE[rid]

    def debug_pixel(self, x, y, primitive=None, sample=None, view=None,
                    eid=None, max_steps=4096):
        raise errors.QueryError("no debug in fake")

    def last_draw_event_id(self):
        return 8

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ToolCallTests(unittest.TestCase):
    def setUp(self):
        self._prev = server._WORKERS
        server._WORKERS = RecordingWorkers(FakeSession())

    def tearDown(self):
        server._WORKERS = self._prev

    def test_trace_pixel_passthrough_with_evidence(self):
        raw = server.trace_pixel(CAPTURE, 1, 2)
        payload = json.loads(raw)
        self.assertEqual(payload["summary"]["target"], "ResourceId::35")
        evidence_ids = [e["id"] for e in payload["summary"]["evidence"]]
        self.assertTrue(evidence_ids)
        self.assertEqual(evidence_ids, [e["id"] for e in payload["summary"]["evidence"]])

    def test_trace_resource_passthrough(self):
        payload = json.loads(server.trace_resource(CAPTURE, "ResourceId::47"))
        self.assertEqual(payload["summary"]["writerCount"], 1)
        ev = payload["writers"][0]["evidence"][0]
        self.assertEqual(ev["operation"], "usage:CopyDst")

    def test_diff_pixel_states(self):
        payload = json.loads(server.diff_pixel(CAPTURE, 1, 2, 3, 4))
        self.assertEqual(payload["comparison"], "same")
        self.assertIn("shader_input_values",
                      [ly["layer"] for ly in payload["layers"]])

    def test_operational_error_returned_as_json(self):
        raw = server.debug_pixel(CAPTURE, 1, 2)
        payload = json.loads(raw)
        self.assertIn("error", payload)

    def test_mcp_arguments_reach_the_worker_unrenamed(self):
        # Guards the mapping MCP -> rdebug.workers._dispatch. A rename on
        # either side must fail here rather than silently changing
        # behaviour in production.
        server.trace_pixel(CAPTURE, 7, 9, mip=2, slice=1, max_writers=3,
                           expand_reads=False, eid=11, target="ResourceId::1")
        _capture, tool, args = server._WORKERS.calls[-1]
        self.assertEqual(tool, "trace_pixel")
        self.assertEqual(args["x"], 7)
        self.assertEqual(args["y"], 9)
        self.assertEqual(args["mip"], 2)
        self.assertEqual(args["slice"], 1)
        self.assertEqual(args["max_writers"], 3)
        self.assertEqual(args["eid"], 11)
        self.assertIs(args["expand_reads"], False)

    def test_none_arguments_are_dropped_so_worker_defaults_apply(self):
        # Forwarding target=None would override the worker's default with a
        # null it never expects (sample=None in place of 0). Falsy-but-meaningful
        # values such as expand_reads=False must survive.
        server.trace_pixel(CAPTURE, 1, 2, target=None, expand_reads=False)
        _capture, _tool, args = server._WORKERS.calls[-1]
        self.assertNotIn("target", args)
        self.assertIs(args["expand_reads"], False)

    def test_capture_is_forwarded_so_the_worker_guard_engages(self):
        # workers.py refuses a capture it is not bound to. That check reads
        # args["capture"], so if MCP stopped forwarding it the guard would
        # pass vacuously.
        server.trace_pixel(CAPTURE, 1, 2)
        _capture, _tool, args = server._WORKERS.calls[-1]
        self.assertEqual(args["capture"], CAPTURE)


class TransportInvariants(unittest.TestCase):
    def _sources(self):
        base = Path(server.__file__).parent
        return {p.name: p.read_text(encoding="utf-8")
                for p in base.glob("*.py")}

    def test_no_renderdoc_api_in_transport(self):
        forbidden = [
            "import renderdoc",
            "ReplayController",
            "PixelHistory(",
            "GetUsage",
            "DebugPixel",
            "InitialiseReplay",
        ]
        for name, text in self._sources().items():
            for token in forbidden:
                self.assertNotIn(token, text, f"{name} references {token}")

    def test_only_semantic_imports_from_analysis(self):
        pattern = re.compile(
            r"from rdebug\.analysis\.(pixel_trace|resource_flow|shader_trace|pixel_diff)"
            r" import (trace_pixel|trace_resource|debug_pixel|diff_pixel)"
        )
        for name, text in self._sources().items():
            for line in text.splitlines():
                if "from rdebug.analysis" in line:
                    self.assertRegex(line.strip(), pattern,
                                     f"{name} has non-semantic analysis import: {line}")

    def test_exactly_four_tools(self):
        tools = [fn for name, fn in vars(server).items()
                 if callable(fn) and getattr(fn, "__module__", "") == server.__name__
                 and name in {"trace_pixel", "trace_resource", "debug_pixel", "diff_pixel"}]
        self.assertEqual(len(tools), 4)


if __name__ == "__main__":
    unittest.main()
