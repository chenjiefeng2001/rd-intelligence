"""Controls for the release gate runner (I1 and I2).

The scenario these exist for is A2-1. With RenderDoc and the capture
environment variables absent, the integration suite skips about 60 of 63
tests, and the process exit code is non-zero only because one unguarded
test errors. Tidy that error up, which anyone might reasonably do, and the
suite reports OK with 60 skipped and exit 0. If a gate accepts that, the
gate has verified nothing while reporting success.

So the controls are built around fake gates that emit exactly the output
shapes unittest produces, including the misleading one. A real suite is not
needed to reproduce the failure mode, and not using one keeps these fast and
independent of whether a GPU is present.

Nothing here touches the frozen section 4.1 contract in ci.check, and no
control asserts anything about a pipeline, because wiring is not authorised.
"""

import importlib.util
import json
import os
import shutil
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
GATE_SPEC = os.path.join(REPO_ROOT, "release-gates.json")


def _load():
    spec = importlib.util.spec_from_file_location(
        "release_gate", os.path.join(REPO_ROOT, "scripts", "release_gate.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RG = _load()


def _fake_gate(tmp, name, body):
    """A gate whose command is a python -c that prints body and exits 0."""
    path = os.path.join(tmp, f"{name}.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "import sys\nsys.stderr.write(" + repr(body) + ")\nsys.exit(0)\n"
        )
    return path


UNITTEST_OK = "Ran 63 tests in 4.0s\n\nOK\n"
# The A2-1 shape: almost everything skipped, and unittest still says OK.
UNITTEST_OK_BUT_SKIPPED = "Ran 63 tests in 3.8s\n\nOK (skipped=60)\n"
UNITTEST_ALL_SKIPPED = "Ran 63 tests in 1.0s\n\nOK (skipped=63)\n"
UNITTEST_FAILURES = (
    "Ran 63 tests in 5.0s\n\n"
    "FAILED (failures=2, errors=0, skipped=0)\n"
)
UNITTEST_WITH_ERROR = (
    "Ran 63 tests in 3.8s\n\n"
    "FAILED (failures=0, errors=1, skipped=60)\n"
)
UNITTEST_BELOW_FLOOR = "Ran 12 tests in 1.0s\n\nOK\n"
UNITTEST_UNPARSEABLE = "some other output entirely\n"


def _gate(tmp, gid, body, min_executed=None, requires=None, exit_code=0):
    script = _fake_gate(tmp, gid, body)
    return {
        "id": gid,
        "command": ["python", script],
        "runner": "unittest",
        "min_executed": min_executed,
        "requires": requires or {},
        "_exit": exit_code,
    }


class TestI1ZeroExecutedIsNeverPass(unittest.TestCase):
    """I1: a gate that executed nothing is not a pass."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gate_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_all_tests_skipped_is_infrastructure_failure(self):
        g = _gate(self.tmp, "s", UNITTEST_ALL_SKIPPED, min_executed=None)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("I1", r["detail"])
        self.assertEqual(r["executed"], 0)

    def test_ok_with_sixty_skipped_is_not_a_pass(self):
        """The exact A2-1 output shape.

        unittest is happy, the exit code is 0, and 60 of 63 checks never ran.
        """
        g = _gate(self.tmp, "s", UNITTEST_OK_BUT_SKIPPED, min_executed=55)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertNotEqual(
            r["outcome"], RG.PASS,
            "63 tests with 60 skipped and exit 0 must not be a gate pass",
        )
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("I1", r["detail"])

    def test_zero_total_is_infrastructure_failure(self):
        g = _gate(self.tmp, "s", "Ran 0 tests in 0.0s\n\nOK\n", min_executed=None)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)

    def test_below_declared_floor_is_infrastructure_failure(self):
        g = _gate(self.tmp, "s", UNITTEST_BELOW_FLOOR, min_executed=55)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("floor", r["detail"])

    def test_unparseable_output_is_infrastructure_failure(self):
        g = _gate(self.tmp, "s", UNITTEST_UNPARSEABLE, min_executed=1)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("could not parse", r["detail"])


class TestI2MissingEnvironmentFailsClosed(unittest.TestCase):
    """I2: missing prerequisites never degrade into skip and pass."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gate_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_missing_env_is_infrastructure_failure(self):
        g = _gate(self.tmp, "s", UNITTEST_OK, min_executed=1,
                  requires={"env": ["SOME_UNSET_VAR"]})
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("SOME_UNSET_VAR", r["detail"])

    def test_missing_capture_is_infrastructure_failure(self):
        g = _gate(self.tmp, "s", UNITTEST_OK, min_executed=1,
                  requires={"capture": True})
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("capture", r["detail"])

    def test_prerequisites_checked_before_running(self):
        """A missing environment must not produce a skip storm at all."""
        g = _gate(self.tmp, "s", UNITTEST_OK_BUT_SKIPPED, min_executed=55,
                  requires={"env": ["SOME_UNSET_VAR"]})
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("missing prerequisites", r["detail"])
        self.assertEqual(r["executed"], 0)


class TestClassificationIsFourWay(unittest.TestCase):
    """Q3: the four outcomes stay distinct. No promotion between them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gate_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_all_executed_and_passing_is_pass(self):
        g = _gate(self.tmp, "s", UNITTEST_OK, min_executed=1)
        self.assertEqual(RG.run_gate(g, self.tmp, env={})["outcome"], RG.PASS)

    def test_content_failures_are_regression(self):
        g = _gate(self.tmp, "s", UNITTEST_FAILURES, min_executed=1)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.REGRESSION)

    def test_errors_are_regression_not_infrastructure(self):
        """An error inside a running suite is a content-side failure.

        This is the case the A2-1 write-up relied on incidentally. The gate
        must classify it deliberately rather than by accident.
        """
        g = _gate(self.tmp, "s", UNITTEST_WITH_ERROR, min_executed=1)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.REGRESSION)

    def test_partial_skips_are_unknown_not_pass(self):
        g = _gate(self.tmp, "s", UNITTEST_OK_BUT_SKIPPED, min_executed=1)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.UNKNOWN,
                         "some checks skipped means no conclusion for those")

    def test_infrastructure_failure_is_never_regression(self):
        g = _gate(self.tmp, "s", UNITTEST_OK, min_executed=1,
                  requires={"env": ["SOME_UNSET_VAR"]})
        self.assertNotEqual(RG.run_gate(g, self.tmp, env={})["outcome"],
                            RG.REGRESSION)

    def test_exit_code_gate_failure_is_regression(self):
        script = _fake_gate(self.tmp, "x", "audit failed\n")
        g = {"id": "a", "command": ["python", script], "runner": "exit_code",
             "min_executed": None, "requires": {}}
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.PASS)  # the fake exits 0
        g2 = dict(g, command=["python", "-c", "import sys; sys.exit(3)"])
        r2 = RG.run_gate(g2, self.tmp, env={})
        self.assertEqual(r2["outcome"], RG.REGRESSION)


class TestBlockingSemantics(unittest.TestCase):
    """Only PASS lets the run succeed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gate_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_unknown_blocks(self):
        self.assertIn(RG.UNKNOWN, RG.BLOCKING)

    def test_infrastructure_blocks(self):
        self.assertIn(RG.INFRA, RG.BLOCKING)

    def test_regression_blocks(self):
        self.assertIn(RG.REGRESSION, RG.BLOCKING)

    def test_pass_does_not_block(self):
        self.assertNotIn(RG.PASS, RG.BLOCKING)

    def test_mixed_run_reports_each_gate_separately(self):
        good = _gate(self.tmp, "good", UNITTEST_OK, min_executed=1)
        bad = _gate(self.tmp, "bad", UNITTEST_OK_BUT_SKIPPED, min_executed=55)
        spec = {"gates": [good, bad]}
        results = RG.run_all(spec, self.tmp, env={})
        outcomes = {r["gate"]: r["outcome"] for r in results}
        self.assertEqual(outcomes["good"], RG.PASS)
        self.assertEqual(outcomes["bad"], RG.INFRA)


class TestDeclaredSpec(unittest.TestCase):
    """The shipped gate spec must itself satisfy the contract it encodes."""

    def test_schema_and_gates(self):
        spec = RG.load_spec(GATE_SPEC)
        self.assertEqual(spec["schema"], "rdebug-release-gates/1")
        self.assertTrue(spec["gates"])

    def test_every_gate_declares_a_rationale(self):
        spec = RG.load_spec(GATE_SPEC)
        for g in spec["gates"]:
            self.assertTrue(g.get("rationale"), g["id"])
            self.assertIn(g.get("runner"), ("unittest", "exit_code"))

    def test_capture_gates_declare_their_environment(self):
        spec = RG.load_spec(GATE_SPEC)
        gate = next(g for g in spec["gates"] if g["id"] == "integration")
        self.assertIn("RDEBUG_RENDERDOC_PATH", gate["requires"]["env"])
        self.assertIn("RDEBUG_INTEGRATION_CAPTURE", gate["requires"]["env"])
        self.assertTrue(gate["requires"].get("module"))
        self.assertTrue(gate["requires"].get("capture"))
        self.assertIsNotNone(gate["min_executed"])

    def test_no_benchmark_is_a_release_gate(self):
        """I4: anything machine-dependent stays out of the gate set."""
        spec = RG.load_spec(GATE_SPEC)
        banned = ("bench", "smoke", "workload", "d4", "probe", "reasoning")
        for g in spec["gates"]:
            joined = " ".join(g["command"]).lower()
            for word in banned:
                self.assertNotIn(
                    word, joined,
                    "{} looks machine-dependent and must not gate a release".format(g["id"]),
                )

    def test_classification_vocabulary_is_declared(self):
        with open(GATE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        for key in (RG.PASS, RG.REGRESSION, RG.UNKNOWN, RG.INFRA):
            self.assertIn(key, spec["classification"])


if __name__ == "__main__":
    unittest.main()
