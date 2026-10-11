"""Test doubles shared across the transport suite.

FakeSession lives here rather than in test_transport.py because it is not part
of the MCP transport. It stood in a module that imports `rdebug_mcp.server`, so
every suite that borrowed it -- the IDE controls, the observability controls --
was made to import the MCP SDK in order to test something that has nothing to
do with MCP. On a runner without the optional `mcp` extra installed, that
incidental coupling took four modules down at import time, and the gate could
report a count without naming the suites that had failed to load.

Nothing in this module imports the MCP SDK or rdebug_mcp. A suite that genuinely
exercises the transport still imports server itself and still needs the extra;
that dependency is real and stays visible. This one was not.
"""

from capture_support import CAPTURE

from rdebug import errors
from rdebug.model import PixelHistoryResult


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
