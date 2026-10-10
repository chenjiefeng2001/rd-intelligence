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


class TestTwoGatesFailForDifferentReasons(unittest.TestCase):
    """One report, two INFRASTRUCTURE_FAILURE rows, and why that is ambiguous.

    Run 37914566151 produced exactly this shape. `unit` executed no test at all
    because its lint precondition could not run, so it carries a lint
    sub-record, executed=0, and no process exit code -- the gate's process
    genuinely never started. `transport` did execute, ran 19 tests, and tripped
    its declared floor of 40, so it carries a real exit code and an error count.

    Both rows read INFRASTRUCTURE_FAILURE. Nothing in the outcome column tells
    them apart, so the entire diagnosis rests on per-gate state surviving
    unmixed. If a future build_report change merged the rows, dropped the lint
    sub-record, or copied an error count onto a gate whose suite never ran, the
    report would attribute a lint failure to a suite that executed -- a claim
    about the code manufactured by a reporting change, which is the class of
    defect these controls exist to catch.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gate_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _rows(self):
        # unit: the probe fails, so run_lint returns before the gate command is
        # ever spawned. probe_command has to differ from command, or
        # release_gate skips the probe and the lint would actually run.
        unit = _gate(self.tmp, "unit", UNITTEST_OK, min_executed=1)
        unit["lint"] = {
            "command": ["python", "-c", "print('lint ran')"],
            "probe_command": ["python", "-c", "raise SystemExit(3)"],
        }
        # transport: the suite genuinely runs and comes up short of its floor.
        transport = _gate(
            self.tmp, "transport",
            "Ran 19 tests in 3.0s\n\nFAILED (failures=0, errors=15, skipped=0)\n",
            min_executed=40)
        results = RG.run_all({"gates": [unit, transport]}, self.tmp, env={})
        return {r["gate"]: r for r in results}

    def test_both_are_infrastructure_and_that_is_all_they_share(self):
        rows = self._rows()
        self.assertEqual(rows["unit"]["outcome"], RG.INFRA)
        self.assertEqual(rows["transport"]["outcome"], RG.INFRA)

    def test_the_gate_that_never_ran_keeps_the_lint_diagnosis(self):
        unit = self._rows()["unit"]
        self.assertEqual(unit["executed"], 0)
        # No exit code is invented for a process that was never started.
        self.assertIsNone(unit["process_exit_code"])
        self.assertIsNotNone(unit["lint"])
        self.assertIn("could not run", unit["lint"]["detail"])
        # The suite never ran, so it has no result to report. A count on this
        # row would be fabricated evidence about tests that did not execute.
        self.assertNotIn("tests_errors", unit)
        self.assertNotIn("tests_failed", unit)

    def test_the_gate_that_ran_keeps_its_own_failure_evidence(self):
        transport = self._rows()["transport"]
        self.assertEqual(transport["executed"], 19)
        self.assertIn("I1", transport["detail"])
        self.assertIsInstance(transport["process_exit_code"], int)
        self.assertEqual(transport["tests_errors"], 15)
        # No lint was a precondition of this gate, so it must not carry one.
        self.assertNotIn("lint", transport)

    def test_neither_row_can_be_read_as_the_other(self):
        rows = self._rows()
        unit, transport = rows["unit"], rows["transport"]
        self.assertNotEqual(unit["executed"], transport["executed"])
        self.assertNotEqual(unit["detail"], transport["detail"])
        self.assertNotEqual(unit["process_exit_code"],
                            transport["process_exit_code"])
        # The lint diagnosis belongs to exactly one row, not to the report.
        self.assertIn("lint", unit)
        self.assertNotIn("lint", transport)


class TestG2DiscoveryAnomaly(unittest.TestCase):
    """G2: a module that cannot be imported is not a content regression."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gate_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    # The three shapes below are the ones measured against a real unittest
    # run. The discovery id is what unittest actually prints, including the
    # parenthesised part; an earlier probe truncated at the space and missed
    # precisely the token that distinguishes them.
    DISCOVERY = (
        "ERROR: test_broken (unittest.loader._FailedTest.test_broken)\n"
        "----------------------------------------------------------------------\n"
        "ImportError: Failed to import test module: test_broken\n"
        "Traceback (most recent call last):\n"
        '  File "unittest\\loader.py", line 396, in _find_test_path\n'
        "ModuleNotFoundError: No module named 'nonexistent_module_xyz'\n"
        "\nRan 2 tests in 0.001s\n\nFAILED (errors=1)\n"
    )
    REAL_FAIL = (
        "FAIL: test_r (test_realfail.R.test_r)\n"
        "----------------------------------------------------------------------\n"
        "Traceback (most recent call last):\n"
        "AssertionError: 1 != 2\n"
        "\nRan 4 tests in 0.001s\n\nFAILED (failures=1, errors=0)\n"
    )
    REAL_ERROR = (
        "ERROR: test_e (test_realerr.E.test_e)\n"
        "----------------------------------------------------------------------\n"
        "Traceback (most recent call last):\n"
        "ValueError: boom\n"
        "\nRan 4 tests in 0.001s\n\nFAILED (failures=0, errors=1)\n"
    )

    def test_discovery_failure_is_infrastructure_not_regression(self):
        g = _gate(self.tmp, "s", self.DISCOVERY, min_executed=1)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("G2", r["detail"])
        self.assertNotEqual(r["outcome"], RG.REGRESSION)

    def test_discovery_anomaly_is_recorded(self):
        g = _gate(self.tmp, "s", self.DISCOVERY, min_executed=1)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertTrue(r["discovery_anomalies"])
        self.assertIn("_FailedTest", r["discovery_anomalies"][0])

    def test_real_failure_is_still_regression(self):
        """False-positive control: the rule must not be broad enough to swallow
        a genuine content failure."""
        g = _gate(self.tmp, "s", self.REAL_FAIL, min_executed=1)
        self.assertEqual(RG.run_gate(g, self.tmp, env={})["outcome"],
                         RG.REGRESSION)

    def test_real_in_test_error_is_still_regression(self):
        """A traceback that mentions neither loader nor _FailedTest is content."""
        g = _gate(self.tmp, "s", self.REAL_ERROR, min_executed=1)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.REGRESSION)
        self.assertEqual(r["discovery_anomalies"], [])

    def test_discovery_and_real_failure_together_is_infrastructure(self):
        """The infrastructure problem is reported as such, not hidden."""
        g = _gate(self.tmp, "s", self.DISCOVERY + self.REAL_FAIL,
                  min_executed=1)
        r = RG.run_gate(g, self.tmp, env={})
        self.assertEqual(r["outcome"], RG.INFRA)
        self.assertIn("test_broken", r["detail"])

    def test_discriminator_is_narrow(self):
        """Only the synthetic id matches; ordinary module paths do not."""
        for ident in ("test_mod.C.test_a", "tests.unit.test_x", "test_a"):
            self.assertNotIn(RG.DISCOVERY_MARKER, ident)
        self.assertIn(
            RG.DISCOVERY_MARKER,
            "unittest.loader._FailedTest.test_broken",
        )


class TestG1FourStateAggregate(unittest.TestCase):
    """G1: the overall verdict keeps four states with distinct exit codes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gate_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _spec(self, gates):
        return {"gates": gates}

    def _res(self, gate, outcome, executed=1, state="IMPLEMENTED"):
        return {"gate": gate, "outcome": outcome, "executed": executed,
                "state": state, "required_execution": True, "attempted": True,
                "detail": ""}

    def test_regression_outranks_everything(self):
        spec = self._spec([])
        report = RG.overall(spec, [
            self._res("a", RG.INFRA), self._res("b", RG.UNKNOWN),
            self._res("c", RG.REGRESSION),
        ])
        self.assertEqual(report["status"], RG.FAIL_REGRESSION)
        self.assertEqual(report["exit_code"], 2)

    def test_infrastructure_outranks_unknown(self):
        report = RG.overall(self._spec([]), [
            self._res("a", RG.UNKNOWN), self._res("b", RG.INFRA),
        ])
        self.assertEqual(report["status"], RG.BLOCKED_INFRA)
        self.assertEqual(report["exit_code"], 3)

    def test_unknown_alone_is_needs_review(self):
        report = RG.overall(self._spec([]), [
            self._res("a", RG.PASS), self._res("b", RG.UNKNOWN),
        ])
        self.assertEqual(report["status"], RG.NEEDS_REVIEW)
        self.assertEqual(report["exit_code"], 4)

    def test_all_pass_with_everything_implemented_is_pass(self):
        report = RG.overall(self._spec([]), [
            self._res("a", RG.PASS, executed=10),
            self._res("b", RG.PASS, executed=5),
        ])
        self.assertEqual(report["status"], RG.PASS_OVERALL)
        self.assertEqual(report["exit_code"], 0)

    def test_not_implemented_gate_prevents_pass(self):
        spec = self._spec([{
            "id": "gate3", "spec_gate": "4.3", "state": "NOT_IMPLEMENTED",
            "required_execution": True, "blocking": False, "command": None,
            "contributes": RG.UNKNOWN, "rationale": "not written",
        }])
        report = RG.overall(spec, [self._res("a", RG.PASS, executed=10)])
        self.assertNotEqual(report["status"], RG.PASS_OVERALL)
        self.assertEqual(report["status"], RG.NEEDS_REVIEW)
        names = [r["gate"] for r in report["gates"]]
        self.assertIn("gate3", names, "an unimplemented gate must be visible")

    def test_unimplemented_gate_reports_unknown_not_pass(self):
        spec = self._spec([{
            "id": "gate3", "spec_gate": "4.3", "state": "NOT_IMPLEMENTED",
            "required_execution": True, "blocking": False, "command": None,
            "contributes": RG.UNKNOWN, "rationale": "not written",
        }])
        report = RG.overall(spec, [self._res("a", RG.PASS, executed=10)])
        row = next(r for r in report["gates"] if r["gate"] == "gate3")
        self.assertEqual(row["outcome"], RG.UNKNOWN)
        self.assertEqual(row["executed"], 0)
        self.assertFalse(row["attempted"])

    def test_required_gate_that_ran_nothing_is_not_pass(self):
        spec = self._spec([])
        report = RG.overall(spec, [self._res("a", RG.PASS, executed=0)])
        self.assertNotEqual(report["status"], RG.PASS_OVERALL)

    def test_exit_codes_are_one_to_one(self):
        seen = {}
        for outcomes, expected in [
            ([RG.REGRESSION], RG.FAIL_REGRESSION),
            ([RG.INFRA], RG.BLOCKED_INFRA),
            ([RG.UNKNOWN], RG.NEEDS_REVIEW),
            ([RG.PASS], RG.PASS_OVERALL),
        ]:
            res = [self._res(f"g{i}", o) for i, o in enumerate(outcomes)]
            report = RG.overall(self._spec([]), res)
            self.assertEqual(report["status"], expected)
            seen[report["status"]] = report["exit_code"]
        self.assertEqual(len(set(seen.values())), len(seen),
                         "G1: two states share an exit code")

    def test_real_spec_today_is_needs_review(self):
        """Acceptance: gate 3 and gate 4 must keep the result off PASS."""
        spec = RG.load_spec(GATE_SPEC)
        passing = [
            self._res(g["id"], RG.PASS, executed=max(g.get("min_executed") or 1, 1))
            for g in spec["gates"] if g.get("state", "IMPLEMENTED") == "IMPLEMENTED"
        ]
        report = RG.overall(spec, passing)
        self.assertEqual(report["status"], RG.NEEDS_REVIEW)
        self.assertIn("cold_warm_equivalence", report["reasons"][0] + "".join(report["reasons"]))
        self.assertIn("benchmark_archive", "".join(report["reasons"]))

    def test_report_is_machine_readable(self):
        report = RG.overall(self._spec([]), [self._res("a", RG.PASS, executed=3)])
        for key in ("status", "exit_code", "reasons", "gates"):
            self.assertIn(key, report)
        for key in ("gate", "outcome", "state", "required_execution",
                    "attempted", "executed", "detail"):
            self.assertIn(key, report["gates"][0])
        json.dumps(report, default=str)
    """The shipped gate spec must itself satisfy the contract it encodes."""

    def test_schema_and_gates(self):
        spec = RG.load_spec(GATE_SPEC)
        self.assertEqual(spec["schema"], "rdebug-release-gates/6")
        self.assertTrue(spec["gates"])

    def test_every_gate_declares_a_rationale(self):
        spec = RG.load_spec(GATE_SPEC)
        for g in spec["gates"]:
            self.assertTrue(g.get("rationale"), g["id"])
            if g.get("state", "IMPLEMENTED") == "IMPLEMENTED":
                self.assertIn(g.get("runner"),
                              ("unittest", "exit_code", "verdict_json"))
                self.assertTrue(g.get("command"), g["id"])

    def test_unimplemented_gates_have_no_command(self):
        """Nothing may be smuggled in as a stand-in for gate 3 or gate 4.

        A temporary check, a virtual check or the D6 benchmark would all show
        up here as a command on a gate that is declared unimplemented. The
        authorisation explicitly forbids any of the three, so the shape
        itself has to rule them out rather than a reviewer's diligence.
        """
        spec = RG.load_spec(GATE_SPEC)
        for g in spec["gates"]:
            if g.get("state", "IMPLEMENTED") == "IMPLEMENTED":
                continue
            self.assertIsNone(
                g.get("command"),
                "{} is declared {} and must carry no command".format(g["id"], g["state"]),
            )
            self.assertEqual(
                g.get("contributes"), RG.UNKNOWN,
                "{} must contribute UNKNOWN so it cannot be counted as a pass".format(g["id"]),
            )

    def test_gate_three_is_implemented_and_gate_four_is_not(self):
        """Gate 3 was implemented; gate 4 still has nothing executable.

        This control previously pinned gate 3 as NOT_IMPLEMENTED. Its purpose
        was to stop a temporary or virtual check standing in for gate 3, and
        it now serves the same purpose from the other side: gate 3 must be a
        real command with a real verdict, and gate 4 must stay visible as
        PROCESS_ONLY so the aggregate cannot reach PASS.
        """
        spec = RG.load_spec(GATE_SPEC)
        by_spec = {g.get("spec_gate"): g for g in spec["gates"]}
        self.assertEqual(by_spec["4.3"]["state"], "IMPLEMENTED")
        self.assertTrue(by_spec["4.3"].get("command"),
                        "gate 3 must be a real command, not a placeholder")
        self.assertEqual(by_spec["4.3"].get("runner"), "verdict_json",
                         "gate 3 carries its own four-state verdict")
        self.assertIn("cold_warm_gate.py",
                      " ".join(by_spec["4.3"]["command"]))
        self.assertEqual(by_spec["4.4"]["state"], "PROCESS_ONLY")
        self.assertIsNone(by_spec["4.4"].get("command"),
                          "gate 4 still has no executable check")

    def test_gate_three_capture_is_keyed_by_gate_id(self):
        """The capture table must use the gate id, or substitution silently
        leaves the placeholder in the command and the gate cannot open it."""
        with open(GATE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        caps = spec.get("captures") or {}
        self.assertIn("cold_warm_equivalence", caps)
        self.assertTrue(os.path.isfile(
            os.path.join(REPO_ROOT, caps["cold_warm_equivalence"])
        ))

    def test_every_exit_code_is_distinct(self):
        with open(GATE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        codes = spec["exit_codes"]
        self.assertEqual(len(set(codes.values())), len(codes),
                         "G1: a shared exit code would collapse the states")
        self.assertEqual(codes["PASS"], 0)
        self.assertNotEqual(codes["FAIL_REGRESSION"], 0)
        self.assertNotEqual(codes["BLOCKED_INFRA"], codes["FAIL_REGRESSION"])
        self.assertNotEqual(codes["NEEDS_REVIEW"], codes["FAIL_REGRESSION"])
        self.assertNotEqual(codes["NEEDS_REVIEW"], codes["PASS"])

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
            if not g.get("command"):
                continue
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
