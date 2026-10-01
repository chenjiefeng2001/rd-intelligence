"""Defect-version controls for integration shutdown exit accounting.

Written against the defect, not against a fix, so they are expected to fail on
the code as it stands. The first control asserts the exact shape of the defect:
a runner that reports clean results and then fails to exit cleanly is recorded
as PASS.

The synthetic runners exist because the real crash needs a GPU, a RenderDoc
build and 154 seconds. What is under test is the classifier, and it has to be
testable without those. Each runner prints a canonical unittest summary to
stderr and exits with a chosen code: the same two-channel shape as the real
thing, with result text on one channel and process status on the other.

Precedence is pinned by the authorization and is why several of these exist. A
genuine content failure also exits non-zero, so any rule of the form
"non-zero exit implies infrastructure" would hide every real regression.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _load():
    spec = importlib.util.spec_from_file_location(
        "release_gate_under_test",
        os.path.join(REPO_ROOT, "scripts", "release_gate.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load()

OK_SUMMARY = (
    "----------------------------------------------------------------------\n"
    "Ran 3 tests in 0.010s\n"
    "\n"
    "OK\n"
)

FAILED_SUMMARY = (
    "----------------------------------------------------------------------\n"
    "FAIL: test_thing (synthetic.TestThing.test_thing)\n"
    "----------------------------------------------------------------------\n"
    "Ran 3 tests in 0.010s\n"
    "\n"
    "FAILED (failures=1)\n"
)

ERROR_SUMMARY = (
    "----------------------------------------------------------------------\n"
    "ERROR: test_thing (synthetic.TestThing.test_thing)\n"
    "----------------------------------------------------------------------\n"
    "Ran 3 tests in 0.010s\n"
    "\n"
    "FAILED (errors=1)\n"
)

SKIPPED_SUMMARY = (
    "----------------------------------------------------------------------\n"
    "Ran 3 tests in 0.010s\n"
    "\n"
    "OK (skipped=2)\n"
)

NO_SUMMARY = "the runner printed nothing a parser could read\n"


class SyntheticRunner:
    """A gate command with a scripted result text and a scripted exit code."""

    def __init__(self, summary, exit_code):
        self.tmp = tempfile.mkdtemp(prefix="exitacct_")
        self.script = os.path.join(self.tmp, "runner.py")
        payload = json.dumps({"summary": summary, "code": exit_code})
        with open(self.script, "w", encoding="utf-8") as fh:
            fh.write(
                "import json, sys\n"
                f"spec = json.loads({payload!r})\n"
                "sys.stderr.write(spec['summary'])\n"
                "sys.stderr.flush()\n"
                "sys.exit(spec['code'])\n"
            )

    def gate(self, gate_id="synthetic", **extra):
        gate = {"id": gate_id, "state": "IMPLEMENTED", "runner": "unittest",
                "required_execution": True, "blocking": True,
                "command": [sys.executable, self.script]}
        gate.update(extra)
        return gate

    def run(self, **gate_extra):
        return G.run_gate(self.gate(**gate_extra), REPO_ROOT, env={})

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ExitAccountingBase(unittest.TestCase):
    def runner(self, summary, exit_code):
        r = SyntheticRunner(summary, exit_code)
        self.addCleanup(r.cleanup)
        return r


class TestTheDefectItself(ExitAccountingBase):
    """The rows that must exist before any fix is credible."""

    def test_clean_results_with_nonzero_exit_is_not_a_pass(self):
        # The observed integration gate: every test passed, and the interpreter
        # died on the way out. It is recorded as PASS today.
        rec = self.runner(OK_SUMMARY, 3221225477).run()
        self.assertNotEqual(
            rec["outcome"], G.PASS,
            "a run that did not exit cleanly cannot be a pass; the process "
            "failed after the results were written")
        self.assertEqual(rec["outcome"], G.INFRA)

    def test_the_two_facts_are_both_retained(self):
        # INFRASTRUCTURE_FAILURE must not be readable as "the tests failed".
        rec = self.runner(OK_SUMMARY, 3221225477).run()
        self.assertEqual(rec["outcome"], G.INFRA)
        self.assertEqual(rec.get("tests_executed"), 3)
        self.assertEqual(rec.get("tests_failed"), 0)
        self.assertEqual(rec.get("tests_errors"), 0)
        self.assertEqual(rec.get("test_result"), "OK")
        self.assertEqual(rec.get("process_exit_code"), 3221225477)
        self.assertIs(rec.get("execution_clean"), False)

    def test_the_reason_names_both_facts(self):
        rec = self.runner(OK_SUMMARY, 3221225477).run()
        reason = rec["detail"].lower()
        self.assertIn("test", reason, "the reason must report the test result")
        self.assertIn("exit", reason, "the reason must report the process exit")

    def test_execution_clean_is_derived_from_the_exit_code(self):
        # Two names for one number drift unless one is derived from the other.
        for code, expected in ((0, True), (1, False), (3221225477, False)):
            rec = self.runner(OK_SUMMARY, code).run()
            self.assertEqual(rec["execution_clean"], expected,
                             f"exit {code} must derive execution_clean")
            self.assertEqual(rec["process_exit_code"], code)


class TestTestResultIsNotTranslated(ExitAccountingBase):
    """test_result carries the runner's own word, not the four-state verdict.

    The authorization's illustrative row shows 	est_result: PASS. Emitting the
    four-state word instead would put the same two words in two different
    vocabularies in one row: 	est_result: PASS beside
    outcome: INFRASTRUCTURE_FAILURE reads as self-contradictory at a glance,
    and invites a consumer to treat the test result as the gate verdict.

    So it is reported as the runner wrote it, OK, which is exactly what
    _parse_unittest matched out of the child's stderr. Nothing is translated,
    nothing is invented, and the field cannot be mistaken for outcome.
    """

    def test_test_result_is_the_word_the_runner_printed(self):
        self.assertEqual(self.runner(OK_SUMMARY, 0).run()["test_result"], "OK")
        self.assertEqual(self.runner(FAILED_SUMMARY, 1).run()["test_result"],
                         "FAILED")

    def test_test_result_is_not_one_of_the_four_states(self):
        four = {G.PASS, G.REGRESSION, G.UNKNOWN, G.INFRA}
        for summary, code in ((OK_SUMMARY, 0), (FAILED_SUMMARY, 1),
                              (SKIPPED_SUMMARY, 0)):
            rec = self.runner(summary, code).run()
            self.assertNotIn(rec["test_result"], four,
                             "test_result must not be readable as the verdict")


class TestAgainstRealUnittestRuns(ExitAccountingBase):
    """Run a real unittest and classify its real output.

    The synthetic summaries above are a fidelity risk, and that risk was not
    theoretical. Two attempts to verify the fix with a hand-built failing test
    both produced INFRASTRUCTURE_FAILURE, and both times the classifier was
    right and the harness was wrong: an empty environment, and then a missing
    `unittest.main()` entry point, meant the module genuinely failed to load.
    A hand-written "FAILED (failures=1)" string would have hidden that entirely.

    So the precedence rule is also pinned against real runs.
    """

    def _real(self, body, **gate_extra):
        tmp = tempfile.mkdtemp(prefix="realacct_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "test_case.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        gate = {"id": "real", "state": "IMPLEMENTED", "runner": "unittest",
                "required_execution": True, "blocking": True,
                "command": [sys.executable, path], "min_executed": 1}
        gate.update(gate_extra)
        # The real environment, not {}. An empty one breaks the child and turns
        # a content question into a discovery question.
        return G.run_gate(gate, REPO_ROOT, env=dict(os.environ))

    FAILING = ("import unittest\n\n"
               "class T(unittest.TestCase):\n"
               "    def test_genuine_failure(self):\n"
               "        self.assertEqual(1, 2)\n\n"
               'if __name__ == "__main__":\n'
               "    unittest.main()\n")

    PASSING = ("import unittest\n\n"
               "class T(unittest.TestCase):\n"
               "    def test_ok(self):\n"
               "        pass\n\n\n"
               'if __name__ == "__main__":\n'
               "    unittest.main()\n")

    def test_real_failing_test_is_a_regression(self):
        rec = self._real(self.FAILING)
        self.assertEqual(rec["tests_failed"], 1)
        self.assertEqual(rec["test_result"], "FAILED")
        self.assertEqual(rec["outcome"], G.REGRESSION)
        self.assertNotEqual(rec["outcome"], G.INFRA)

    def test_real_passing_test_is_a_pass(self):
        rec = self._real(self.PASSING)
        self.assertEqual(rec["test_result"], "OK")
        self.assertEqual(rec["process_exit_code"], 0)
        self.assertEqual(rec["outcome"], G.PASS)

    def test_a_real_loader_failure_is_infrastructure_not_regression(self):
        # The case that made the classifier look wrong twice. A module that
        # cannot be imported is a harness problem; reporting it as INFRA was
        # correct both times.
        rec = self._real("import a_module_that_does_not_exist\n\n"
                         'if __name__ == "__main__":\n'
                         "    unittest.main()\n")
        self.assertEqual(rec["outcome"], G.INFRA)
        self.assertNotEqual(rec["outcome"], G.REGRESSION)

    def test_real_regression_overall_still_exits_two(self):
        rec = self._real(self.FAILING)
        result = G.overall({"gates": []}, [rec])
        self.assertEqual(result["status"], G.FAIL_REGRESSION)
        self.assertEqual(result["exit_code"], 2)


class TestContentOutranksProcessExit(ExitAccountingBase):
    """The mirror error, pinned shut.

    A real failure exits non-zero too, measured at exit 1 with
    'FAILED (failures=1)'. Treating that as infrastructure would hide it.
    """

    def test_real_failure_with_nonzero_exit_is_a_regression(self):
        rec = self.runner(FAILED_SUMMARY, 1).run()
        self.assertEqual(rec["outcome"], G.REGRESSION)
        self.assertEqual(rec["tests_failed"], 1)

    def test_real_failure_with_zero_exit_is_still_a_regression(self):
        # Constructible and worth pinning: a runner that reports a failure and
        # then exits 0 must not be laundered into PASS by the new rule.
        rec = self.runner(FAILED_SUMMARY, 0).run()
        self.assertEqual(rec["outcome"], G.REGRESSION)
        self.assertNotEqual(rec["outcome"], G.PASS)

    def test_the_unclean_exit_is_recorded_next_to_a_regression(self):
        rec = self.runner(FAILED_SUMMARY, 3221225477).run()
        self.assertEqual(rec["outcome"], G.REGRESSION,
                         "content conclusion stands; the crash does not "
                         "outrank a real failure")
        self.assertEqual(rec["process_exit_code"], 3221225477)
        self.assertIs(rec["execution_clean"], False)

    def test_an_error_with_nonzero_exit_is_a_regression(self):
        rec = self.runner(ERROR_SUMMARY, 1).run()
        self.assertEqual(rec["outcome"], G.REGRESSION)
        self.assertEqual(rec["tests_errors"], 1)

    def test_no_nonzero_exit_can_ever_be_a_pass(self):
        for summary in (OK_SUMMARY, SKIPPED_SUMMARY):
            for code in (1, 2, 3, 4, 3221225477, 255):
                rec = self.runner(summary, code).run()
                self.assertNotEqual(
                    rec["outcome"], G.PASS,
                    f"exit {code} must not be laundered into PASS")


class TestUnchangedVerdicts(ExitAccountingBase):
    """The fix must not move anything that was already honest."""

    def test_clean_results_with_zero_exit_is_still_a_pass(self):
        rec = self.runner(OK_SUMMARY, 0).run()
        self.assertEqual(rec["outcome"], G.PASS)
        self.assertIs(rec["execution_clean"], True)

    def test_unparseable_output_is_infrastructure(self):
        rec = self.runner(NO_SUMMARY, 0).run()
        self.assertEqual(rec["outcome"], G.INFRA)

    def test_unparseable_output_with_nonzero_exit_is_still_infrastructure(self):
        rec = self.runner(NO_SUMMARY, 3221225477).run()
        self.assertEqual(rec["outcome"], G.INFRA)
        self.assertIs(rec["execution_clean"], False)

    def test_zero_executed_is_infrastructure_not_pass(self):
        summary = ("----------------------------------------------------------------------\n"
                   "Ran 0 tests in 0.000s\n"
                   "\n"
                   "OK\n")
        rec = self.runner(summary, 0).run()
        self.assertEqual(rec["outcome"], G.INFRA)

    def test_below_floor_is_infrastructure(self):
        rec = self.runner(OK_SUMMARY, 0).run(min_executed=55)
        self.assertEqual(rec["outcome"], G.INFRA)

    def test_discovery_anomaly_is_infrastructure(self):
        summary = ("----------------------------------------------------------------------\n"
                   "ERROR: unittest.loader._FailedTest.test_broken\n"
                   "----------------------------------------------------------------------\n"
                   "Ran 3 tests in 0.000s\n"
                   "\n"
                   "FAILED (errors=1)\n")
        rec = self.runner(summary, 1).run()
        self.assertEqual(rec["outcome"], G.INFRA)
        self.assertNotEqual(rec["outcome"], G.REGRESSION)

    def test_tests_executed_excludes_skips_not_total(self):
        # Found by mutation: reporting total instead of executed was invisible
        # because every other control used a run with skipped=0, where the two
        # are equal by construction. Here total=3 and skipped=2.
        rec = self.runner(SKIPPED_SUMMARY, 0).run()
        self.assertEqual(rec["total"], 3)
        self.assertEqual(rec["skipped"], 2)
        self.assertEqual(rec["executed"], 1)
        self.assertEqual(rec["tests_executed"], 1,
                         "tests_executed counts checks that ran, not tests "
                         "discovered; reporting total overstates it by the "
                         "number skipped")

    def test_skipped_is_unknown(self):
        rec = self.runner(SKIPPED_SUMMARY, 0).run()
        self.assertEqual(rec["outcome"], G.UNKNOWN)

    def test_exit_code_runner_kind_is_untouched(self):
        # The subprocess gates already treat a non-zero exit as decisive. That
        # behaviour is correct and must not change.
        r = SyntheticRunner("some audit output\n", 1)
        self.addCleanup(r.cleanup)
        gate = r.gate()
        gate["runner"] = "exit_code"
        rec = G.run_gate(gate, REPO_ROOT, env={})
        self.assertEqual(rec["outcome"], G.REGRESSION)

    def test_every_unittest_row_carries_both_facts(self):
        for summary, code in ((OK_SUMMARY, 0), (OK_SUMMARY, 3221225477),
                              (FAILED_SUMMARY, 1), (SKIPPED_SUMMARY, 0),
                              (NO_SUMMARY, 0)):
            rec = self.runner(summary, code).run()
            for field in ("process_exit_code", "execution_clean"):
                self.assertIn(field, rec,
                              f"{field} missing from a {code} row")


class TestOverallConsequence(unittest.TestCase):
    """The pinned overall consequence, asserted rather than assumed."""

    def test_infrastructure_outranks_unknown(self):
        records = [{"gate": "unit", "outcome": G.PASS, "state": "IMPLEMENTED",
                    "required_execution": True, "executed": 298},
                   {"gate": "integration", "outcome": G.INFRA,
                    "state": "IMPLEMENTED", "required_execution": True,
                    "executed": 63},
                   {"gate": "benchmark_archive", "outcome": G.UNKNOWN,
                    "state": "PROCESS_ONLY", "required_execution": False,
                    "executed": 0}]
        result = G.overall({"gates": []}, records)
        self.assertEqual(result["status"], G.BLOCKED_INFRA)
        self.assertEqual(result["exit_code"], 3)

    def test_regression_still_outranks_everything(self):
        records = [{"gate": "integration", "outcome": G.INFRA,
                    "state": "IMPLEMENTED", "required_execution": True,
                    "executed": 63},
                   {"gate": "unit", "outcome": G.REGRESSION,
                    "state": "IMPLEMENTED", "required_execution": True,
                    "executed": 298}]
        result = G.overall({"gates": []}, records)
        self.assertEqual(result["status"], G.FAIL_REGRESSION)
        self.assertEqual(result["exit_code"], 2)
