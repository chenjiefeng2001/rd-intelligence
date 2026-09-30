"""Contract controls for the CI gate verdict (DESIGN_SPEC section 4.1).

Written before the fix, per the approved sequence, so the controls could be
shown to fail against the defective implementation.

The defect: ci.check derived its verdict from "no failures were recorded"
rather than from "sufficient verification ran", so a degenerate baseline
produced status=pass with passedChecks=0. It compared the capture file hash
and nothing else. A completely empty baseline happened to fail, but only
because the expected hash was None, and the hash check is explicitly meant
to be skippable, so ignore_capture_hash=True made even that pass.

The FakeSession and SPEC fixtures are reused from test_ci_gate so both files
exercise the same fake replay surface. No RenderDoc dependency: the verdict
rules are about the baseline, not about replay.
"""

import unittest

from rdebug import ci
from tests.unit.test_ci_gate import _DUMMY, SPEC, FakeSession


def _baseline(session=None, spec=SPEC):
    return ci.record(session or FakeSession(), spec)


class TestCIGateVerdictPositive(unittest.TestCase):
    """At least one check ran and everything passed -> pass, both versions."""

    def test_spec_baseline_is_pass(self):
        report = ci.check(FakeSession(), _baseline())
        self.assertEqual(report["status"], "pass")
        self.assertGreater(report["passedChecks"], 0)
        self.assertEqual(report["failures"], [])

    def test_passed_checks_reflects_actual_execution(self):
        """Counted per executed check, not derived from an expected item list."""
        one = ci.check(FakeSession(), _baseline(spec={"pixels": [[320, 240]],
                                                      "pairs": []}))
        three = ci.check(FakeSession(), _baseline(spec={
            "pixels": [[320, 240], [10, 10], [400, 400]], "pairs": []}))
        self.assertEqual(three["passedChecks"], 3 * one["passedChecks"])
        self.assertGreater(three["passedChecks"], one["passedChecks"])


class TestCIGateVerdictRegression(unittest.TestCase):
    """Checks ran and one failed -> regression. Positive control, both versions.

    Recorded so the fix cannot be mistaken for a general weakening: the gate
    must keep catching real drift after the change.
    """

    def test_value_drift_is_regression(self):
        report = ci.check(FakeSession(r=0.9), _baseline())
        self.assertEqual(report["status"], "regression")
        self.assertTrue(report["failures"])

    def test_event_id_drift_is_regression(self):
        baseline = _baseline()
        for entry in baseline["pixels"].values():
            entry["fragmentEventId"] = 4242
        report = ci.check(FakeSession(), baseline)
        self.assertEqual(report["status"], "regression")

    def test_pair_regression_is_regression(self):
        baseline = _baseline()
        # A sentinel that cannot be a real verdict, so this is a genuine
        # mismatch rather than a value the fake happens to already produce.
        for entry in baseline["pairs"].values():
            entry["comparison"] = "not-a-real-verdict"
        report = ci.check(FakeSession(), baseline)
        self.assertEqual(report["status"], "regression")


class TestCIGateZeroChecksMustNotPass(unittest.TestCase):
    """The controls that detect the defect. These fail before the fix."""

    def _assert_not_pass(self, report, why):
        self.assertNotEqual(
            report["status"], "pass",
            f"{why}: pass was returned without any content verification",
        )

    def test_missing_pixels_key_is_not_pass(self):
        baseline = _baseline()
        truncated = dict(baseline)
        truncated.pop("pixels")
        truncated.pop("pairs")
        self._assert_not_pass(ci.check(FakeSession(), truncated),
                              "baseline with neither pixels nor pairs")

    def test_remaining_pairs_still_count_as_content_checks(self):
        """Precision control: the counter is per executed check, not per baseline.

        Dropping only the pixels leaves the pairs, which are real content
        checks that genuinely pass. So pass is the correct verdict here, and
        a fix that reported unknown here would be over-strict rather than
        correct.
        """
        baseline = _baseline()
        pairs_only = dict(baseline)
        pairs_only.pop("pixels")
        report = ci.check(FakeSession(), pairs_only)
        self.assertEqual(
            report["status"], "pass",
            "the pair checks ran and passed, so this is a verified pass",
        )
        self.assertGreater(report["passedChecks"], 0)

    def test_empty_pixels_dict_is_not_pass(self):
        baseline = _baseline()
        emptied = dict(baseline)
        emptied["pixels"] = {}
        emptied["pairs"] = {}
        self._assert_not_pass(ci.check(FakeSession(), emptied),
                              "baseline with no pixels and no pairs")

    def test_hash_only_baseline_is_not_pass(self):
        """A matching capture hash is integrity, not content verification."""
        self._assert_not_pass(
            ci.check(FakeSession(), {"captureSha256": ci.capture_hash(_DUMMY)}),
            "baseline carrying only a capture hash, which verifies file "
            "identity and no rendering result",
        )

    def test_ignore_capture_hash_does_not_license_an_empty_pass(self):
        self._assert_not_pass(
            ci.check(FakeSession(), {}, ignore_capture_hash=True),
            "empty baseline with the hash check disabled",
        )

    def test_zero_checks_reports_unknown(self):
        """Section 4.1.3: reuse the existing section 2.5 vocabulary."""
        report = ci.check(FakeSession(), {"captureSha256": ci.capture_hash(_DUMMY)})
        self.assertEqual(
            report["status"], "unknown",
            "zero executed content checks must yield unknown, reusing the "
            "section 2.5 vocabulary instead of introducing a new status",
        )

    def test_passed_checks_is_zero_when_nothing_ran(self):
        baseline = _baseline()
        emptied = dict(baseline)
        emptied["pixels"] = {}
        emptied["pairs"] = {}
        report = ci.check(FakeSession(), emptied)
        self.assertEqual(report["passedChecks"], 0)
        self.assertNotEqual(report["status"], "pass")


class TestCIGateIgnoreHashFalsePositiveControl(unittest.TestCase):
    """The easiest thing to get wrong here.

    Disabling the hash check must not stop content checks from running, and
    must not reduce the executed count to zero. Getting this wrong would
    turn a genuine pass into an unverified state, which is a regression of
    its own.
    """

    def test_content_checks_still_execute_when_hash_disabled(self):
        report = ci.check(FakeSession(), _baseline(), ignore_capture_hash=True)
        self.assertEqual(
            report["status"], "pass",
            "a real baseline must still pass when only the hash check is "
            "skipped; the hash is a precondition, not the verification",
        )
        self.assertGreater(
            report["passedChecks"], 0,
            "disabling the hash check must not reduce executed content checks "
            "to zero",
        )

    def test_executed_count_is_unchanged_by_disabling_the_hash(self):
        enabled = ci.check(FakeSession(), _baseline())
        disabled = ci.check(FakeSession(), _baseline(), ignore_capture_hash=True)
        self.assertEqual(
            enabled["passedChecks"], disabled["passedChecks"],
            "the hash check is not a content check, so skipping it must not "
            "change how much content verification ran",
        )

    def test_content_regression_still_caught_when_hash_disabled(self):
        report = ci.check(FakeSession(r=0.9), _baseline(),
                          ignore_capture_hash=True)
        self.assertEqual(report["status"], "regression")


class TestCIGateEmptyBaselineIsNotStructuralProtection(unittest.TestCase):
    """An empty baseline must fail for the Contract reason, not by accident."""

    def test_empty_baseline_reports_a_failure(self):
        report = ci.check(FakeSession(), {})
        self.assertNotEqual(report["status"], "pass")
        self.assertTrue(
            report["failures"],
            "an empty baseline with no hash must still report a failure "
            "rather than passing by having nothing to compare",
        )


if __name__ == "__main__":
    unittest.main()
