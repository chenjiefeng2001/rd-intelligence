import unittest

from rdebug.analysis.pixel_diff import compare_scalar, diff_pixel
from rdebug.errors import QueryError
from rdebug.model import DiffResult, PixelHistoryResult


class FakeAction:
    def __init__(self, eid, name):
        self.eventId = eid
        self.actionId = eid
        self.customName = name
        self.flags = 0
        self.numIndices = 3
        self.numInstances = 0
        self.children = []


def mod(eid, prim, passed=True, r=0.5, g=0.5, b=0.5):
    return {
        "eventId": eid,
        "primitiveID": prim,
        "fragIndex": 0,
        "passed": passed,
        "unboundPS": False,
        "directShaderWrite": False,
        "preMod": {"float": [0.0, 0.0, 0.0, 0.0], "depth": -1.0, "stencil": -1},
        "shaderOut": {"float": [r, g, b, 1.0], "depth": -1.0, "stencil": -1},
        "postMod": {"float": [r, g, b, 1.0], "depth": -1.0, "stencil": -1},
    }


def history(eid, prim, r=0.5, g=0.5, b=0.5, passed=True):
    return {
        "resource": "ResourceId::35",
        "contextEventId": eid,
        "x": 0,
        "y": 0,
        "mip": 0,
        "slice": 0,
        "sample": 0,
        "evidence": [{"id": "h" * 12, "eventId": eid, "operation": "pixel_history"}],
        "modifications": [mod(eid, prim, passed=passed, r=r, g=g, b=b)],
    }


def pipeline(shader="ResourceId::49", reads=("ResourceId::47",)):
    return {
        "eventId": 8,
        "outputTargets": [{"slot": 0, "resource": "ResourceId::35",
                           "firstMip": 0, "firstSlice": 0}],
        "depthTarget": None,
        "shaders": {"Pixel": {"resource": shader, "entryPoint": "main",
                              "debuggable": True}},
        "descriptors": [
            {"stage": "Pixel", "type": "ReadOnlyResource", "index": 0,
             "resource": rid, "sampler": None}
            for rid in reads
        ],
        "indexBuffer": None,
    }


class FakeSession:
    path = "cap.rdc"

    def __init__(self, history_by_point, pipelines_by_eid, usage_by_rid):
        self.history_calls = []
        self._hist = history_by_point
        self._pipes = pipelines_by_eid
        self._usage = usage_by_rid

    def pixel_history(self, rid, x, y, mip=0, slice_=0, sample=0,
                      comp_type=None, context_eid=None):
        self.history_calls.append((x, y))
        return PixelHistoryResult.parse(self._hist[(x, y)])

    def pipeline(self, event_id=None):
        return self._pipes[event_id]

    def root_actions(self):
        eids = sorted({m["eventId"] for h in self._hist.values()
                       for m in h["modifications"]}
                      | {e for rows in self._usage.values() for e, _ in rows})
        return [FakeAction(e, f"A{e}") for e in eids]

    def usage(self, rid):
        return [
            {"eventId": e, "usage": u, "usageRaw": 0} for e, u in self._usage[rid]
        ]

    def debug_pixel(self, x, y, primitive=None, sample=None, view=None,
                    eid=None, max_steps=4096):
        raise QueryError("debug not available in fake")

    def last_draw_event_id(self):
        return 8


USAGE = {
    "ResourceId::47": [(2, "CopyDst"), (8, "PS_Resource")],
    "ResourceId::91": [(4, "CopyDst"), (8, "PS_Resource")],
}


def make_session(hist_a, hist_b, pipe_a=None, pipe_b=None):
    pipes = {8: pipe_a or pipeline()}
    if pipe_b is not None or 9 in hist_b.get("modifications", []) or True:
        pipes[9] = pipe_b or pipeline()
    pipes[1] = pipe_a or pipeline()
    return FakeSession(hist_a | hist_b, pipes, USAGE)


class TestCompareScalar(unittest.TestCase):
    def test_states(self):
        self.assertEqual(compare_scalar(None, None), "unknown")
        self.assertEqual(compare_scalar(None, 1), "unknown")
        self.assertEqual(compare_scalar(1, 1), "same")
        self.assertEqual(compare_scalar([1.0], [1.0]), "same")
        self.assertEqual(compare_scalar(1, 2), "different")


class TestDiffPixel(unittest.TestCase):
    def test_case_a_identical(self):
        s = make_session({(10, 10): history(8, 0)}, {(20, 10): history(8, 0)})
        result = diff_pixel(s, (10, 10), (20, 10))
        self.assertEqual(result.comparison, "same")
        self.assertTrue(result.equal)
        self.assertIsNone(result.first_divergence)

    def test_case_b_different_fragment(self):
        s = make_session({(10, 10): history(8, 0)}, {(20, 10): history(9, 1)})
        result = diff_pixel(s, (10, 10), (20, 10))
        self.assertEqual(result.comparison, "different")
        self.assertEqual(result.first_divergence["layer"], "fragment")
        for side in ("good", "bad"):
            self.assertTrue(result.first_divergence[side]["evidence"]
                            or result.first_divergence[side]["value"])

    def test_case_c_same_shader_different_input(self):
        s = make_session(
            {(10, 10): history(8, 0)},
            {(20, 10): history(9, 0)},
            pipe_a=pipeline(reads=("ResourceId::47",)),
            pipe_b=pipeline(reads=("ResourceId::91",)),
        )
        result = diff_pixel(s, (10, 10), (20, 10))
        self.assertEqual(result.comparison, "different")
        self.assertEqual(result.first_divergence["layer"], "input_bindings")
        self.assertEqual(result.first_divergence["good"]["value"], ["ResourceId::47"])
        self.assertEqual(result.first_divergence["bad"]["value"], ["ResourceId::91"])

    def test_case_d_same_resource_content_divergence_is_unknown_deep(self):
        s = make_session(
            {(10, 10): history(8, 0)},
            {(20, 10): history(8, 0, r=0.6)},
            pipe_a=pipeline(reads=("ResourceId::47",)),
            pipe_b=pipeline(reads=("ResourceId::47",)),
        )
        result = diff_pixel(s, (10, 10), (20, 10))
        statuses = {ly["layer"]: ly["status"] for ly in result.payload["layers"]}
        self.assertEqual(statuses["resource_provenance"], "same")
        self.assertEqual(statuses["input_bindings"], "same")
        self.assertEqual(statuses["shader_input_values"], "unknown")
        self.assertEqual(result.first_divergence["layer"], "pixel_value")
        self.assertEqual(result.comparison, "different")

    def test_unknown_when_one_side_missing_fragment(self):
        s = make_session(
            {(10, 10): history(8, 0)},
            {(20, 10): history(8, 3, passed=False)},
        )
        result = diff_pixel(s, (10, 10), (20, 10))
        statuses = {ly["layer"]: ly["status"] for ly in result.payload["layers"]}
        self.assertEqual(statuses["fragment"], "different")
        self.assertEqual(statuses["pixel_value"], "unknown")

    def test_shader_values_unknown_note_by_default(self):
        s = make_session({(10, 10): history(8, 0)}, {(20, 10): history(8, 0)})
        result = diff_pixel(s, (10, 10), (20, 10))
        entry = next(
            ly
            for ly in result.payload["layers"]
            if ly["layer"] == "shader_input_values"
        )
        self.assertEqual(entry["status"], "unknown")
        self.assertIn("note", entry)

    def test_history_reuse(self):
        s = make_session({(10, 10): history(8, 0)}, {(20, 10): history(8, 0)})
        h = PixelHistoryResult.parse(history(8, 0))
        diff_pixel(s, (10, 10), (20, 10), history_a=h, history_b=h)
        self.assertEqual(s.history_calls, [])

    def test_diff_result_parse_roundtrip(self):
        s = make_session({(10, 10): history(8, 0)}, {(20, 10): history(9, 1)})
        raw = diff_pixel(s, (10, 10), (20, 10)).to_dict()
        parsed = DiffResult.parse(raw)
        self.assertEqual(parsed.comparison, "different")
        with self.assertRaises(TypeError):
            DiffResult.parse({"comparison": "maybe", "layers": [], "a": {}, "b": {},
                              "evidence": []})


if __name__ == "__main__":
    unittest.main()
