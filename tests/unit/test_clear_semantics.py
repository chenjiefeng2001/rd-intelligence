import unittest

from rdebug.analysis.pixel_diff import _fragment
from rdebug.analysis.pixel_trace import build_graph
from rdebug.model import PixelHistoryResult
from rdebug.query.events import event_semantics

DRAW_FLAG = 0x0002
CLEAR_FLAGS = (0x100000, 0x200000)
DISPATCH_FLAGS = (0x0004, 0x0008)


def semantics(flags):
    return event_semantics(
        flags,
        draw_flag=DRAW_FLAG,
        clear_flags=CLEAR_FLAGS,
        dispatch_flags=DISPATCH_FLAGS,
    )


def mod(eid, passed=True, r=0.5):
    return {
        "eventId": eid,
        "primitiveID": 0,
        "fragIndex": 0,
        "passed": passed,
        "unboundPS": False,
        "directShaderWrite": False,
        "preMod": {"float": [0.0, 0.0, 0.0, 0.0], "depth": -1.0, "stencil": -1},
        "shaderOut": {"float": [r, 0.5, 0.5, 1.0], "depth": -1.0, "stencil": -1},
        "postMod": {"float": [r, 0.5, 0.5, 1.0], "depth": -1.0, "stencil": -1},
    }


def history(mods):
    return {
        "resource": "ResourceId::35",
        "contextEventId": max(m["eventId"] for m in mods),
        "x": 0,
        "y": 0,
        "mip": 0,
        "slice": 0,
        "sample": 0,
        "evidence": [],
        "modifications": mods,
    }


PIPE = {
    "shaders": {"Pixel": {"resource": "ResourceId::49", "entryPoint": "main"}},
    "descriptors": [
        {"stage": "Pixel", "type": "ReadOnlyResource", "index": 0,
         "resource": "ResourceId::47", "sampler": None}
    ],
    "indexBuffer": None,
}


class TestEventSemanticsPredicate(unittest.TestCase):
    def test_clear_invariants(self):
        for flag in CLEAR_FLAGS:
            s = semantics(flag)
            self.assertTrue(s["mayModifyPixel"])
            self.assertFalse(s["fragmentCandidate"])
            self.assertTrue(s["isClear"])

    def test_draw_is_fragment_candidate(self):
        s = semantics(DRAW_FLAG)
        self.assertTrue(s["mayModifyPixel"])
        self.assertTrue(s["fragmentCandidate"])

    def test_dispatch_not_fragment_candidate(self):
        s = semantics(0x0004 | DRAW_FLAG)
        self.assertTrue(s["isDispatch"])
        self.assertFalse(s["fragmentCandidate"])


class TestClearGraphInvariants(unittest.TestCase):
    def _graph(self, actions_index):
        return build_graph(
            {"x": 1, "y": 2},
            history([mod(1)]),
            {1: PIPE},
            actions=actions_index,
            target="ResourceId::35",
        )

    def test_clear_keeps_pixel_fact_but_no_shader_evidence(self):
        actions = {1: {"name": "Clear", "flags": CLEAR_FLAGS[0],
                       "isClear": True, "fragmentCandidate": False,
                       "mayModifyPixel": True}}
        graph = self._graph(actions)
        labels = [(e["from"], e["label"]) for e in graph["edges"]]
        self.assertIn(("draw:1", "writes"), labels)
        self.assertNotIn(("draw:1", "bound_ps"), labels)
        self.assertNotIn(("draw:1", "reads"), labels)
        self.assertNotIn("shader", {n["kind"] for n in graph["nodes"]})
        self.assertTrue(graph["nodes"][2]["attrs"]["clear"])

    def test_missing_semantics_preserves_legacy_behavior(self):
        graph = self._graph({1: {"name": "", "flags": 0}})
        labels = [e["label"] for e in graph["edges"]]
        self.assertIn("bound_ps", labels)

    def test_clear_still_counts_for_pixel_value(self):
        graph = self._graph({1: {"name": "Clear", "flags": CLEAR_FLAGS[0],
                                 "isClear": True, "fragmentCandidate": False}})
        self.assertEqual(graph["summary"]["modificationCount"], 1)
        self.assertIsNotNone(graph["summary"]["finalValue"])


class TestFragmentSelection(unittest.TestCase):
    def test_clear_excluded_from_fragment_candidates(self):
        hist = PixelHistoryResult.parse(history([mod(1), mod(8, r=0.7)]))
        actions = {
            1: {"fragmentCandidate": False},
            8: {"fragmentCandidate": True},
        }
        self.assertEqual(_fragment(hist, actions)["eventId"], 8)

    def test_clear_only_history_has_no_fragment(self):
        hist = PixelHistoryResult.parse(history([mod(1)]))
        actions = {1: {"fragmentCandidate": False}}
        self.assertIsNone(_fragment(hist, actions))

    def test_default_true_without_semantics(self):
        hist = PixelHistoryResult.parse(history([mod(1)]))
        self.assertEqual(_fragment(hist)["eventId"], 1)


if __name__ == "__main__":
    unittest.main()
