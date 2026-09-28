"""Regression tests: a failure to look must never be reported as agreement.

DESIGN_SPEC §2.5 requires the three-state discipline: `unknown` is neither
`same` nor `different`, and no layer may promote unknown to a definite
conclusion. Two code paths used to break that by turning a *failed*
enumeration into an empty list, which then compared equal to another empty
list and produced a fabricated "same":

  * CaptureSession.pipeline() swallowed a GetAllUsedDescriptors() failure
    as `used = []` -> build_graph emitted no reads edges -> diff-pixel
    compared [] against [] -> input_bindings and resource_provenance came
    out "same", and the overall verdict followed. One-sided failure was
    worse: it fabricated a divergence asserting the other side reads
    nothing.
  * mem_current() fell back to RSS when private bytes were momentarily
    unreadable, comparing RSS against a private-bytes baseline.

These run with no RenderDoc dependency.
"""

import unittest

from rdebug.analysis import pixel_diff
from rdebug.analysis.pixel_diff import compare_scalar, diff_pixel_flows
from rdebug.analysis.pixel_trace import build_graph


def _mod(eid, prim, passed, value):
    out = {"shaderOut": {"float": [value, value, value, 1.0],
                         "depth": -1.0, "stencil": -1},
           "postMod": {"float": [value, value, value, 1.0],
                       "depth": -1.0, "stencil": -1}}
    out.update({"eventId": eid, "primitiveID": prim, "passed": passed,
                "fragcoord": [0.5, 0.5, 0.5, 1.0]})
    return out


def _history():
    return {
        "resource": "ResourceId::35",
        "contextEventId": 8,
        "x": 0,
        "y": 0,
        "mip": 0,
        "slice": 0,
        "sample": 0,
        "evidence": [{"id": "h" * 12, "eventId": 8,
                      "operation": "pixel_history"}],
        "modifications": [_mod(1, 0, False, 0.0), _mod(8, 0, True, 0.5)],
    }


def _graph(reads_enumerable, reads):
    """Minimal graph shaped like build_graph's output."""
    edges = []
    for rid in reads:
        edges.append({"from": "shader:1:x", "to": f"resource:{rid}",
                      "label": "reads", "evidence": []})
    return {
        "nodes": [{"id": "pixel:0,0", "kind": "pixel", "attrs": {}}],
        "edges": edges,
        "summary": {"readsEnumerable": reads_enumerable,
                    "evidence": [], "modificationCount": 2,
                    "writeEventCount": 1, "finalValue": None,
                    "contextEventId": 1},
        "resourceFlows": {f"resource:{r}": {"writers": [],
                                          "readers": []}
                          for r in reads},
    }


class TestCompareScalarIsTheOnlyPlaceEmptinessIsDecided(unittest.TestCase):
    def test_empty_vs_empty_is_same_but_none_is_not(self):
        # Documents the exact hazard: [] == [] compares equal, so any layer
        # that must express "not observed" has to use None, not [].
        self.assertEqual(compare_scalar([], []), "same")
        self.assertEqual(compare_scalar(None, None), "unknown")
        self.assertEqual(compare_scalar(None, []), "unknown")
        self.assertEqual(compare_scalar([], None), "unknown")


class TestFailedEnumerationYieldsUnknownNotSame(unittest.TestCase):
    def _diff(self, readable_a, readable_b, reads_a=(), reads_b=()):
        return diff_pixel_flows(
            pixel_diff._extract_flow(_graph(readable_a, list(reads_a)),
                                     _history()),
            pixel_diff._extract_flow(_graph(readable_b, list(reads_b)),
                                     _history()),
            "a.rdc")

    def _layer(self, result, name):
        return next(e for e in result.payload["layers"] if e["layer"] == name)

    def test_both_sides_unreadable_is_unknown_not_same(self):
        # The regression: this used to be "same" on both affected layers.
        r = self._diff(False, False)
        self.assertEqual(self._layer(r, "input_bindings").get("status"), "unknown")
        self.assertEqual(self._layer(r, "resource_provenance").get("status"),
                         "unknown")

    def test_one_sided_unreadable_is_unknown_not_fabricated_divergence(self):
        # Used to be "different" with an empty value, i.e. a claim that the
        # readable side reads no resources at all.
        r = self._diff(True, False, reads_a=("ResourceId::7",))
        self.assertEqual(self._layer(r, "input_bindings").get("status"), "unknown")
        self.assertEqual(self._layer(r, "resource_provenance").get("status"),
                         "unknown")

    def test_unreadable_side_does_not_fabricate_a_divergence(self):
        r = self._diff(True, False, reads_a=("ResourceId::7",))
        self.assertNotEqual(r.payload["comparison"], "different")
        self.assertIsNone(r.payload.get("firstDivergence"))

    def test_readable_equal_sides_still_report_same(self):
        # The fix must not turn honest agreement into unknown.
        r = self._diff(True, True, reads_a=("ResourceId::7",),
                       reads_b=("ResourceId::7",))
        self.assertEqual(self._layer(r, "input_bindings").get("status"), "same")
        self.assertEqual(self._layer(r, "resource_provenance").get("status"), "same")

    def test_readable_different_sides_still_report_different(self):
        r = self._diff(True, True, reads_a=("ResourceId::7",),
                       reads_b=("ResourceId::9",))
        self.assertEqual(self._layer(r, "input_bindings").get("status"),
                         "different")

    def test_empty_read_set_is_still_honest_same(self):
        # No descriptors is a real observation, unlike a failed lookup.
        r = self._diff(True, True, reads_a=(), reads_b=())
        self.assertEqual(self._layer(r, "input_bindings").get("status"), "same")

    def test_unknown_layers_are_explained_not_silent(self):
        # A caller must be able to tell WHY a layer is unknown, otherwise
        # `unknown` is indistinguishable from "not implemented yet".
        r = self._diff(False, False)
        for name in ("input_bindings", "resource_provenance"):
            self.assertIn("note", self._layer(r, name))
            self.assertIn("enumerat", self._layer(r, name)["note"])

    def test_readable_layers_carry_no_spurious_note(self):
        r = self._diff(True, True, reads_a=("ResourceId::7",),
                       reads_b=("ResourceId::7",))
        self.assertNotIn("note", self._layer(r, "input_bindings"))


class TestGraphReportsEnumerationFailure(unittest.TestCase):
    def test_summary_marks_reads_enumerable(self):
        # build_graph must default to enumerable and flip to False when a
        # pipeline carried a descriptorsError.
        g = build_graph({"x": 0, "y": 0}, _history(),
                        pipelines={1: {"descriptors": [],
                                       "descriptorsError": "boom"}})
        self.assertFalse(g["summary"]["readsEnumerable"])

    def test_summary_defaults_to_enumerable(self):
        g = build_graph({"x": 0, "y": 0}, _history(),
                        pipelines={1: {"descriptors": []}})
        self.assertTrue(g["summary"]["readsEnumerable"])


class TestNoRssFallbackInTheMemoryGate(unittest.TestCase):
    def test_mem_current_never_calls_rss_bytes(self):
        # AST, not substring: the docstring legitimately names rss_bytes()
        # to explain why it is NOT used here.
        import ast
        import inspect
        import textwrap

        from rdebug.worker_manager import _Worker
        tree = ast.parse(textwrap.dedent(inspect.getsource(_Worker.mem_current)))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertNotIn(
            "rss_bytes", called,
            "mem_current feeds the private-memory-delta gate; an RSS "
            "fallback would compare RSS against a private-bytes baseline "
            "(DESIGN_SPEC §2.9)")

    def test_mem_current_returns_none_when_private_is_unreadable(self):
        from rdebug.worker_manager import _Worker
        w = _Worker.__new__(_Worker)
        w.proc = None

        def boom():
            return None

        w.private_bytes = boom
        w.rss_bytes = lambda: 123456  # must be ignored
        self.assertIsNone(w.mem_current())


if __name__ == "__main__":
    unittest.main()
