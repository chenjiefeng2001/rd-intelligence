"""unit gate verdict invariants for the environment prerequisite.

A regression pin, not a defect reproduction.

There is no defect here. The gate already refuses to report PASS when it
verified nothing, and this file exists so that stays true. U1 was chosen over
changing accounting or semantics precisely because the measured behaviour is
sound: 475 executed with 3 skipped gives UNKNOWN, 478 executed gives PASS, and
neither an absent environment nor a fully skipped suite can yield PASS.

Every case below runs a real unittest process through the real `run_gate`, so
the counts, the exit status and the classification are all produced by the
implementation rather than asserted about it.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

PASS_AND_SKIP = """
import unittest


class Probe(unittest.TestCase):
    def test_one_runs(self):
        self.assertTrue(True)

    @unittest.skip("environment unavailable")
    def test_two_skipped(self):
        self.fail("must not run")
"""

ALL_SKIPPED = """
import unittest


class Probe(unittest.TestCase):
    @unittest.skip("environment unavailable")
    def test_one_skipped(self):
        self.fail("must not run")

    @unittest.skip("environment unavailable")
    def test_two_skipped(self):
        self.fail("must not run")
"""

ALL_PASS = """
import unittest


class Probe(unittest.TestCase):
    def test_one_runs(self):
        self.assertTrue(True)

    def test_two_runs(self):
        self.assertTrue(True)
"""

ONE_FAILING = """
import unittest


class Probe(unittest.TestCase):
    def test_one_fails(self):
        self.fail("content difference")
"""


def _release_gate():
    spec = importlib.util.spec_from_file_location(
        "rg_unit_invariants", os.path.join(REPO_ROOT, "scripts",
                                          "release_gate.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestUnitVerdictInvariants(unittest.TestCase):
    """The classification table, exercised end to end."""

    def setUp(self):
        self.rg = _release_gate()

    def _classify(self, module_body, min_executed=None):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "test_probe.py"), "w",
                      encoding="utf-8") as fh:
                fh.write(module_body)
            gate = {
                "id": "probe",
                "runner": "unittest",
                "required_execution": True,
                "command": [sys.executable, "-m", "unittest", "discover",
                            "-s", tmp, "-t", tmp],
            }
            if min_executed is not None:
                gate["min_executed"] = min_executed
            # The gate still decides against the real repo; only the
            # evidence it leaves behind goes to the scratch dir.
            return self.rg.run_gate(gate, REPO_ROOT, env=dict(os.environ),
                                    evidence_root=tmp)

    def test_nothing_executed_can_never_be_a_pass(self):
        """FLOW: all tests skipped -> executed 0 -> INFRASTRUCTURE_FAILURE.

        This is the invariant U1 pins. A gate that verified nothing is not a
        pass, and the check must precede any path that could reach PASS.
        """
        record = self._classify(ALL_SKIPPED)
        self.assertEqual(record["outcome"], self.rg.INFRA)
        self.assertNotEqual(record["outcome"], self.rg.PASS)
        self.assertEqual(record["executed"], 0)

    def test_a_skipped_part_gives_unknown_not_a_pass(self):
        """FLOW: one executed, one skipped -> UNKNOWN.

        This is the measured unit gate shape: 475 executed and 3 skipped. The
        skipped part gets no content conclusion, and the run is still blocking.
        """
        record = self._classify(PASS_AND_SKIP)
        self.assertEqual(record["outcome"], self.rg.UNKNOWN)
        self.assertEqual(record["executed"], 1)
        self.assertEqual(record["skipped"], 1)
        self.assertIn(self.rg.UNKNOWN, self.rg.BLOCKING)
        self.assertIn("no content conclusion", record["detail"])

    def test_a_complete_run_passes(self):
        """The positive case is reachable, so the guards are not blanket."""
        record = self._classify(ALL_PASS)
        self.assertEqual(record["outcome"], self.rg.PASS)
        self.assertEqual(record["executed"], 2)
        self.assertEqual(record["skipped"], 0)

    def test_a_content_failure_is_a_regression(self):
        """Environment unavailability must not absorb real failures."""
        record = self._classify(ONE_FAILING)
        self.assertEqual(record["outcome"], self.rg.REGRESSION)

    def test_the_declared_floor_is_fail_closed(self):
        """FLOW: executed below min_executed -> INFRASTRUCTURE_FAILURE.

        The unit gate declares a floor; a suite that runs fewer tests than
        declared is treated as unmet rather than quietly passing.
        """
        record = self._classify(PASS_AND_SKIP, min_executed=5)
        self.assertEqual(record["outcome"], self.rg.INFRA)
        self.assertIn("floor", record["detail"])


class TestUnitGateDeclaresItsFloor(unittest.TestCase):
    """The floor is a declared part of the unit gate's contract."""

    def test_the_spec_still_declares_min_executed(self):
        with open(os.path.join(REPO_ROOT, "release-gates.json"),
                  encoding="utf-8") as fh:
            spec = json.load(fh)
        unit = next(g for g in spec["gates"] if g["id"] == "unit")
        self.assertEqual(unit.get("min_executed"), 100)
        self.assertTrue(unit.get("required_execution"))


if __name__ == "__main__":
    unittest.main()
