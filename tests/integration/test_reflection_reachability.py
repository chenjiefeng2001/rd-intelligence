"""Reachability guard for the reflection path frozen under section 2.11.

The O2 freeze recorded a limitation rather than hiding it: the comment in
front of the reflection catch is pinned by nothing, so it can rot, and the
fact that makes the catch's classification honest -- reflection fields are
real observed facts on a real capture -- was only ever measured by hand in
a probe.

This test pins that fact. It asserts, on a real capture, that a pixel
written by the pixel stage produces a shader node whose reflection fields
are populated. If reachability ever breaks, or if a change reintroduces a
path that yields the catch's shape, the entryPoint would come back empty
and this fails. It is a guard on the frozen evidence, not new scope: it
changes no production code and asserts no behaviour that is not already
required by DESIGN_SPEC sections 2.5 and 2.11.
"""

import os
import unittest

from rdebug.adapter.locator import find_module_dir

CAPTURE_ENV = "RDEBUG_INTEGRATION_CAPTURE"
SPIRAL = 5


def _ready():
    return bool(os.environ.get(CAPTURE_ENV)) and find_module_dir() is not None


@unittest.skipUnless(
    _ready(),
    f"set {CAPTURE_ENV} to a .rdc file and make the renderdoc python module "
    "importable (RDEBUG_RENDERDOC_PATH) to run integration tests",
)
class TestReflectionPathReachability(unittest.TestCase):
    """Pins docs/S2-REFLECTION-EVIDENCE.md section 1 on a real capture."""

    @classmethod
    def setUpClass(cls):
        from rdebug.adapter.core import CaptureSession

        cls.session = CaptureSession(os.environ[CAPTURE_ENV])
        cls.session.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    def _fragment_shader_node(self):
        """The shader node for the first fragment-written pixel near centre.

        The centre of a triangle workload is inside the rasterised area.
        The corner pixels of a triangle fixture are not: they are covered
        only by a clear, whose fragmentCandidate is false, which correctly
        suppresses the shader node. That distinction is why the earlier
        probe concluded the path was unreachable.
        """
        from rdebug.analysis.common import choose_output_target
        from rdebug.analysis.pixel_trace import trace_pixel

        s = self.session
        draws = [r["eventId"] for r in s.action_rows() if r.get("isDraw")]
        self.assertTrue(draws, "capture has no draw events")
        eid = draws[-1]
        target = choose_output_target(s, eid)
        tex = next(t for t in s.textures() if t["id"] == target)
        cx, cy = tex["width"] // 2, tex["height"] // 2
        for r in range(SPIRAL + 1):
            for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)):
                x, y = cx + dx, cy + dy
                if not (0 <= x < tex["width"] and 0 <= y < tex["height"]):
                    continue
                graph = trace_pixel(s, x, y, target=target, context_eid=eid)
                nodes = [n for n in graph["nodes"] if n["kind"] == "shader"]
                if nodes:
                    return x, y, nodes[0]["attrs"]
        self.fail(
            f"no fragment-written pixel found within {SPIRAL} of "
            f"({cx},{cy}); the reflection path may have become unreachable"
        )

    def test_fragment_pixel_reaches_the_reflection_path(self):
        _, _, attrs = self._fragment_shader_node()
        self.assertEqual(attrs.get("stage"), "Pixel")
        self.assertIn("resource", attrs)

    def test_reflection_fields_are_populated_observed_facts(self):
        """The anti-rot guard: these must not degrade to the catch's shape.

        A reflection entry that lost its fields is indistinguishable from
        the defensive catch's output, which section 2.11.4 records as
        unimplemented. Pinning the populated form on a real capture is what
        keeps that gap honest instead of silent.
        """
        x, y, attrs = self._fragment_shader_node()
        self.assertIn(
            "entryPoint", attrs,
            f"pixel ({x},{y}) reached the shader node without an "
            "entryPoint, which is the shape the catch produces",
        )
        self.assertNotEqual(
            str(attrs.get("entryPoint")).strip(), "",
            "entryPoint must be a real observed fact, not an empty default",
        )
        self.assertIn(
            "debuggable", attrs,
            "debuggable must be reported, not defaulted away",
        )
        self.assertIsInstance(
            attrs.get("debuggable"), bool,
            "debuggable must be an observed boolean",
        )


if __name__ == "__main__":
    unittest.main()
