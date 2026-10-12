"""The real cold/warm run, as a positive control.

Runs gate 3 for real against the capture the gate spec names. It needs the
corpus capture and an importable renderdoc module, both of which the integration
gate declares and the unit gate does not.

It was the positive control for the project's real state and sat under
tests/unit, where a runner without those prerequisites could only skip it. Any
skip makes release_gate report UNKNOWN, so the unit gate could never be anything
else on such a runner. The unit controls that drive the comparison and verdict
logic directly stay where they were; this one runs the real thing, so it runs
with the gate that says so.
"""

import importlib.util
import json
import os
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _load():
    spec = importlib.util.spec_from_file_location(
        "cold_warm_gate", os.path.join(REPO_ROOT, "scripts", "cold_warm_gate.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G3 = _load()


class TestRealRun(unittest.TestCase):
    """Positive control on the state the project is actually in."""

    CAPTURE = os.path.join(REPO_ROOT, "tests", "workload", "corpus",
                           "w00001_frame11.rdc")

    def setUp(self):
        if not os.path.exists(self.CAPTURE):
            self.skipTest("capture not present")
        from rdebug.adapter.locator import find_module_dir

        if find_module_dir() is None:
            self.skipTest("renderdoc module not importable")

    def test_real_capture_passes_and_proves_the_boundary(self):
        verdict = G3.run(self.CAPTURE, warmup=2)
        self.assertEqual(verdict["outcome"], G3.PASS,
                         "differences: {}".format(json.dumps(verdict["cases"], default=str)[:600]))
        ev = verdict["evidence"]
        self.assertTrue(ev["same_worker_within_A"])
        self.assertTrue(ev["recycle_produced_new_worker"])
        self.assertNotEqual(ev["workers"]["A_cold"], ev["workers"]["B_cold"])

    def test_high_risk_shader_values_case_really_ran(self):
        verdict = G3.run(self.CAPTURE, warmup=1)
        case = verdict["cases"]["diff_pixel_shader_values"]
        self.assertIn(case["verdict"], (G3.PASS, G3.UNKNOWN, G3.REGRESSION))
        self.assertEqual(
            case["attempted"], 4,
            "the shader-values case must be attempted at all four collection "
            "points, not dropped",
        )
        self.assertGreater(
            case["available_at"], 0,
            "the shader-values case must have produced a payload somewhere; an "
            "unavailable-everywhere case is a different finding",
        )

    def test_every_case_reports_its_execution_accounting(self):
        """The report must be able to say what ran, not only that all passed."""
        verdict = G3.run(self.CAPTURE, warmup=1)
        for cid, case in verdict["cases"].items():
            self.assertIn("attempted", case, cid)
            self.assertIn("available_at", case, cid)
            self.assertEqual(case["attempted"], 4, cid)
            self.assertLessEqual(case["available_at"], case["attempted"], cid)


if __name__ == "__main__":
    unittest.main()
