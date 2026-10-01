"""Defect-version controls for termination classification.

These are written against the defect, so they fail today: `tests/workload/
termination.py` does not exist, and `test_workload_reliability.py` classifies
with `code < 0`, which cannot fire on Windows.

Scope note, because it matters for what these controls can prove. This file
holds the *pure* truth table and lives in the unit gate, so the classification
rules are enforced on every run without needing a compiler or a subprocess.
The companion `tests/workload/test_termination_evidence.py` exercises the
*evidence* layer against real processes and is not gate-enforced; a control at
the bottom of this file asserts that file still exists and still covers the
required cases.

One rule is load-bearing and easy to undo: `native_termination_suspected` is a
statement about evidence, not an attribution. Measured on Windows, a genuine
access violation and a deliberate `sys.exit(3221225477)` produce byte-identical
return codes with no stderr either way. Nothing downstream may collapse that
class into "crashed".
"""

import importlib
import os
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

EVIDENCE_MODULE = os.path.join(REPO_ROOT, "tests", "workload",
                               "test_termination_evidence.py")
REQUIRED_EVIDENCE_CASES = (
    "test_real_clean_exit",
    "test_real_explicit_nonzero_exit_is_not_a_signal",
    "test_real_python_traceback",
    "test_real_native_access_violation",
    "test_deliberate_ntstatus_exit_is_not_called_a_crash",
    "test_real_timeout_is_recorded",
)


def _termination():
    return importlib.import_module("tests.workload.termination")


class TerminationTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.T = _termination()

    def observe(self, **kwargs):
        return self.T.observe(**kwargs)


class TestExecutionResultIsPreserved(TerminationTestBase):
    """The raw value is never rewritten. Derived views are additions."""

    def test_raw_returncode_is_kept_verbatim(self):
        for rc in (0, 1, 7, -6, -11, 3221225477, 3221226505):
            obs = self.observe(returncode=rc, stderr="", platform="nt")
            self.assertEqual(obs["execution_result"]["process_returncode"], rc)
            self.assertIs(obs["execution_result"]["returncode_present"], True)

    def test_absent_returncode_is_representable(self):
        # Measured: subprocess.TimeoutExpired has no .returncode at all.
        obs = self.observe(returncode=None, stderr="", platform="nt")
        self.assertIsNone(obs["execution_result"]["process_returncode"])
        self.assertIs(obs["execution_result"]["returncode_present"], False)

    def test_evidence_carries_sentinel_and_traceback(self):
        obs = self.observe(returncode=0, stdout="SCENARIO_OK", stderr="",
                           sentinel="SCENARIO_OK", platform="nt")
        self.assertIs(obs["evidence"]["completion_sentinel_present"], True)
        self.assertIs(obs["evidence"]["traceback_present"], False)


class TestWindowsClassification(TerminationTestBase):

    def test_zero_is_normal_exit(self):
        obs = self.observe(returncode=0, stderr="", platform="nt")
        self.assertEqual(obs["termination_observation"]["class"],
                         self.T.NORMAL_EXIT)

    def test_ordinary_nonzero_is_nonzero_exit_not_a_signal(self):
        # taskkill /F measures as plain 1 on Windows, so a low code must not be
        # promoted into a termination class.
        obs = self.observe(returncode=1, stderr="", platform="nt")
        self.assertEqual(obs["termination_observation"]["class"],
                         self.T.NONZERO_EXIT)
        obs = self.observe(returncode=7, stderr="", platform="nt")
        self.assertEqual(obs["termination_observation"]["class"],
                         self.T.NONZERO_EXIT)

    def test_traceback_is_python_failure(self):
        obs = self.observe(returncode=1, platform="nt",
                           stderr="Traceback (most recent call last):\n  x\n")
        self.assertEqual(obs["termination_observation"]["class"],
                         self.T.PYTHON_FAILURE)

    def test_ntstatus_error_range_is_native_termination_suspected(self):
        for rc, label in ((3221225477, "0xC0000005 access violation"),
                          (3221226505, "0xC0000409 abort"),
                          (3221225848, "0xC00001D8 illegal instruction")):
            obs = self.observe(returncode=rc, stderr="", platform="nt")
            self.assertEqual(obs["termination_observation"]["class"],
                             self.T.NATIVE_TERMINATION_SUSPECTED, label)
            self.assertEqual(obs["evidence"]["ntstatus"], rc)

    def test_windows_warning_status_is_not_an_error(self):
        # 0x8xxxxxxx is a warning severity and must not be classified as an
        # abnormal termination.
        obs = self.observe(returncode=0x80000003, stderr="", platform="nt")
        self.assertNotEqual(obs["termination_observation"]["class"],
                            self.T.NATIVE_TERMINATION_SUSPECTED)

    def test_deliberate_ntstatus_exit_is_suspected_not_a_crash(self):
        """The ambiguity, pinned rather than hidden.

        A program that calls sys.exit(3221225477) is indistinguishable from a
        real access violation on Windows. The class name must therefore say
        "suspected", and nothing in the observation may assert that a crash
        happened.
        """
        obs = self.observe(returncode=3221225477, stderr="", platform="nt")
        self.assertEqual(obs["termination_observation"]["class"],
                         self.T.NATIVE_TERMINATION_SUSPECTED)
        blob = repr(obs).lower()
        for forbidden in ("crashed", "\"crash\"", "is_crash", "crash=true"):
            self.assertNotIn(forbidden, blob,
                             "the observation must not claim a crash; the "
                             "return code cannot establish one")


class TestPosixClassification(TerminationTestBase):

    def test_negative_returncode_is_signal_termination(self):
        for rc, sig in ((-11, 11), (-6, 6), (-9, 9)):
            obs = self.observe(returncode=rc, stderr="", platform="posix")
            self.assertEqual(obs["termination_observation"]["class"],
                             self.T.SIGNAL_TERMINATION, f"rc={rc}")
            self.assertEqual(obs["evidence"]["signal_number"], sig)
            self.assertEqual(obs["evidence"]["signal_number"], -rc,
                             "signal number is -returncode, not WTERMSIG")

    def test_positive_returncode_is_never_a_signal(self):
        # os.WIFSIGNALED(7) is True after an ordinary sys.exit(7), and
        # WTERMSIG(-9) measures 119. Both were measured; neither may be used.
        for rc in (1, 2, 5, 7):
            obs = self.observe(returncode=rc, stderr="", platform="posix")
            self.assertNotEqual(obs["termination_observation"]["class"],
                                self.T.SIGNAL_TERMINATION,
                                f"rc={rc} must not be read as a signal")
            self.assertIsNone(obs["evidence"]["signal_number"])

    def test_traceback_beats_plain_nonzero(self):
        obs = self.observe(returncode=1, platform="posix",
                           stderr="Traceback (most recent call last):\n")
        self.assertEqual(obs["termination_observation"]["class"],
                         self.T.PYTHON_FAILURE)

    def test_ntstatus_view_is_windows_only(self):
        obs = self.observe(returncode=-11, stderr="", platform="posix")
        self.assertIsNone(obs["evidence"]["ntstatus"])


class TestSharedClasses(TerminationTestBase):

    def test_timeout_is_its_own_class(self):
        obs = self.observe(returncode=None, stderr="", platform="nt")
        self.assertEqual(obs["termination_observation"]["class"],
                         self.T.TIMEOUT)
        self.assertIs(obs["execution_result"]["returncode_present"], False)

    def test_unknown_platform_is_indeterminate_not_normal(self):
        obs = self.observe(returncode=0, stderr="", platform="plan9")
        self.assertEqual(obs["termination_observation"]["class"],
                         self.T.INDETERMINATE)

    def test_every_class_is_declared(self):
        for name in ("NORMAL_EXIT", "PYTHON_FAILURE", "NONZERO_EXIT",
                     "SIGNAL_TERMINATION", "NATIVE_TERMINATION_SUSPECTED",
                     "TIMEOUT", "INDETERMINATE"):
            self.assertTrue(hasattr(self.T, name), name)
            self.assertIsInstance(getattr(self.T, name), str)

    def test_classifier_does_not_use_wifsignaled_or_wtermsig(self):
        import ast
        import inspect

        # Executable form only. The module docstring names both helpers in
        # order to explain why they are forbidden, and a text search flags that
        # explanation as a violation -- the same over-broad check that once
        # flagged the cold/warm capture path for containing "tests/workload".
        tree = ast.parse(inspect.getsource(self.T))
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Name):
                used.add(node.id)
        for banned in ("WIFSIGNALED", "WTERMSIG"):
            self.assertNotIn(
                banned, used,
                f"os.{banned} misreports: WIFSIGNALED(7) is True after "
                "sys.exit(7) and WTERMSIG(-9) is 119. Measured on WSL Ubuntu.")


class TestEvidenceLayerIsStillExercised(TerminationTestBase):
    """This file cannot prove the evidence layer, so something must.

    The truth table above is pure. Whether the harness actually feeds it real
    process results is only established by the companion module, which is not
    in any gate. These controls keep it from being quietly deleted.
    """

    def test_evidence_module_exists(self):
        self.assertTrue(os.path.isfile(EVIDENCE_MODULE),
                        f"missing {EVIDENCE_MODULE}; the classification truth "
                        "table is pure and proves nothing about real processes")

    def test_evidence_module_still_covers_every_required_case(self):
        with open(EVIDENCE_MODULE, encoding="utf-8") as handle:
            source = handle.read()
        for case in REQUIRED_EVIDENCE_CASES:
            self.assertIn(f"def {case}(", source,
                          f"the real-subprocess control {case} is gone")

    def test_reliability_report_stays_flat_for_its_consumer(self):
        # scripts/workload_run.py does all(v == 0 for v in REPORT["reliability"])
        # so a nested dict there silently turns the workload gate False.
        from tests.workload import harness

        for key, value in harness.REPORT["reliability"].items():
            self.assertIsInstance(value, int,
                                  f"reliability[{key!r}] is {type(value).__name__}; "
                                  "workload_run.py compares every value to 0")


class TestHarnessWiringIsEvidenceBased(TerminationTestBase):
    """The classifier existing is not the same as the harness using it.

    The defect was in the harness, not only in a rule: it classified with
    `code < 0` and let TimeoutExpired escape. Controls over the classifier alone
    would have stayed green through both, so these drive the recording path
    with a stubbed `run_isolated` and check what lands in the report.
    """

    def setUp(self):
        from tests.workload import harness
        from tests.workload import test_workload_reliability as reliability

        self.harness = harness
        self.reliability = reliability
        self._saved = {k: (dict(v) if isinstance(v, dict) else
                           (list(v) if isinstance(v, list) else v))
                       for k, v in harness.REPORT.items()}
        self._original = reliability.run_isolated
        self.addCleanup(self._restore)

    def _restore(self):
        self.reliability.run_isolated = self._original
        self.harness.REPORT.update(self._saved)

    def _drive(self, observation, returncode, stderr="", stdout=""):
        self.reliability.run_isolated = lambda scenario, **kw: {
            "returncode": returncode, "stdout": stdout, "stderr": stderr,
            "observation": observation, "timed_out": returncode is None,
        }
        case = self.reliability.TestReliabilityScenarios("test_error_injection")
        return case._run("stubbed")

    def _observation(self, **kwargs):
        return self.T.observe(**kwargs)

    def test_native_status_is_recorded_as_a_crash_evidence_class(self):
        obs = self._observation(returncode=0xC0000005, stderr="", platform="nt")
        with self.assertRaises(AssertionError):
            self._drive(obs, 0xC0000005)
        # Pre-fix this was `code < 0`, which is False here, so nothing was
        # recorded at all and the suite reported zero crashes on Windows.
        self.assertEqual(self.harness.REPORT["reliability"]["crashes"], 1)
        self.assertEqual(
            self.harness.REPORT["terminations"]
            [self.T.NATIVE_TERMINATION_SUSPECTED], 1)

    def test_traceback_is_recorded_as_unhandled_exception(self):
        obs = self._observation(returncode=1, platform="nt",
                                stderr="Traceback (most recent call last):\n")
        with self.assertRaises(AssertionError):
            self._drive(obs, 1, stderr="Traceback (most recent call last):\n")
        self.assertEqual(
            self.harness.REPORT["reliability"]["unhandledExceptions"], 1)
        self.assertEqual(self.harness.REPORT["terminations"]
                         [self.T.PYTHON_FAILURE], 1)

    def test_timeout_is_recorded_rather_than_raised(self):
        obs = self.T.observe_from_timeout(
            __import__("subprocess").TimeoutExpired(cmd="x", timeout=1))
        with self.assertRaises(AssertionError):
            self._drive(obs, None)
        self.assertEqual(self.harness.REPORT["terminations"][self.T.TIMEOUT], 1)
        self.assertEqual(
            self.harness.REPORT["terminationEvidence"][0]["execution_result"]
            ["returncode_present"], False)

    def test_deliberate_ntstatus_exit_is_recorded_without_a_crash_claim(self):
        obs = self._observation(returncode=0xC0000005, stderr="", platform="nt")
        with self.assertRaises(AssertionError):
            self._drive(obs, 0xC0000005)
        recorded = self.harness.REPORT["terminationEvidence"][0]
        self.assertFalse(self.T.is_crash(recorded))
        self.assertNotIn("crashed", repr(recorded).lower())

    def test_a_real_timeout_in_run_isolated_does_not_escape(self):
        # End-to-end through the real harness. A timeout this short cannot
        # finish, so the child is killed and the observation must still come
        # back rather than propagating TimeoutExpired out of the test.
        result = self.harness.run_isolated("error_injection", timeout=0.001)
        self.assertIsNone(result["returncode"])
        self.assertIs(result["timed_out"], True)
        self.assertEqual(result["observation"]["termination_observation"]["class"],
                         self.T.TIMEOUT)

    def test_reliability_stays_flat_while_terminations_nests(self):
        self.assertIsInstance(self.harness.REPORT["terminations"], dict)
        for key, value in self.harness.REPORT["reliability"].items():
            self.assertIsInstance(value, int)

    def test_workload_run_gate_expression_still_holds(self):
        # scripts/workload_run.py:51-52 is
        #   all(v == 0 for k, v in harness.REPORT["reliability"].items())
        # A nested dict in there compares unequal to 0 and silently turns the
        # workload gate False, which reads as a workload failure rather than as
        # a report shape change.
        from tests.workload import harness

        expr = all(v == 0 for _k, v in harness.REPORT["reliability"].items())
        self.assertTrue(expr,
                        "the expression workload_run.py evaluates is already "
                        "False, so its gate is broken before anything runs")


if __name__ == "__main__":
    unittest.main()
