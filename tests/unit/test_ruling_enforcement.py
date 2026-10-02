"""F3 / F4 ruling enforcement -- defect version, written before the change.

Both rulings are decided (see docs/DOCUMENT-CLASSIFICATION-CONTRACT.md §9).
These controls exist so the implementation cannot drift from the ruling, and
so neither ruling can be quietly reversed by editing a constant.

F3 -- a prose `status:` line in the body is not schema metadata. The
classification controls must never read it. Today nothing says so, and the
ruling's one durable rule is exactly the kind that decays unless it is checked.

F4 -- status documents refresh on milestone cadence, and MAX_DRIFT is
calibrated to 19 from the measured interval distribution. The calibration is
recorded in the contract and read from there, so the number in the code cannot
diverge from the ruling. The understatement check is removed with the ruling,
because it encodes the per-commit cadence the ruling replaced.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
CONTRACT = os.path.join(REPO_ROOT, "docs",
                        "DOCUMENT-CLASSIFICATION-CONTRACT.md")
FREEZE = os.path.join(REPO_ROOT, "docs", "CURRENT-EVIDENCE-FREEZE.md")
STATUS = os.path.join(os.path.dirname(REPO_ROOT), "STATUS.md")

#: The measured refresh-interval distribution the calibration came from.
MEASURED = [1, 1, 1, 2, 1, 1, 3, 3, 3, 2, 2, 1, 19, 9, 1, 1, 3]


def _load(name, relpath):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(REPO_ROOT, relpath))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract():
    with open(CONTRACT, encoding="utf-8") as fh:
        return fh.read()


class TestF3ProseStatusIsNotSchema(unittest.TestCase):
    """The classification controls must not read body prose."""

    def _classification(self):
        return _load("dc", "tests/unit/test_document_classification.py")

    def test_the_parser_reads_front_matter_only(self):
        """FLOW: the parsed fields come from the metadata block and nowhere else.

        Asserted by feeding the real parser a document whose body contains a
        line that would parse as a declaration if the body were scanned.
        """
        import tempfile
        module = self._classification()
        with tempfile.TemporaryDirectory() as workdir:
            path = os.path.join(workdir, "doc.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("---\ndocument_role: contract\n"
                         "freshness_policy: point_in_time\n---\n\n"
                         "# Title\n\n"
                         "status: FROZEN\n"
                         "document_role: evidence_record\n"
                         "freshness_policy: living\n")
            with open(path, encoding="utf-8") as fh:
                fields, body = module._parse_front_matter(fh.read())
        self.assertEqual(fields["document_role"], "contract")
        self.assertEqual(fields["freshness_policy"], "point_in_time")
        self.assertIn("status: FROZEN", body,
                      "the prose line must land in the body, not the fields")
        self.assertNotIn("status", fields,
                         "a body line that reads like a declaration was parsed "
                         "as schema metadata. F3 ruled this out.")

    def test_no_control_reads_a_prose_status(self):
        """The ruling's durable rule, checked at the source level.

        A future control that helpfully cross-checks prose status would violate
        the ruling while looking like an improvement.
        """
        with open(os.path.join(REPO_ROOT, "tests", "unit",
                               "test_document_classification.py"),
                  encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotRegex(
            source, r'["\']status["\']',
            "the classification controls reference a 'status' key. F3 ruled "
            "that body prose status is not machine-readable metadata and must "
            "not be treated as such. If the status line is ever to be "
            "constrained, define a canonical schema key first.")

    def test_a_frozen_prose_status_does_not_block_classification(self):
        """Positive case: the ruled combination is accepted, not flagged."""
        import tempfile
        module = self._classification()
        with tempfile.TemporaryDirectory() as workdir:
            path = os.path.join(workdir, "doc.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("---\ndocument_role: contract\n"
                         "freshness_policy: point_in_time\n---\n\n"
                         "# Title\n\nstatus: FROZEN\n\n"
                         "Some frozen prose.\n")
            with open(path, encoding="utf-8") as fh:
                fields, _ = module._parse_front_matter(fh.read())
        case = module.TestDocumentClassificationSchema("setUpClass")
        case.docs = {path: (fields, "body")}
        # The role and policy controls must both pass for this document.
        case.test_document_role_is_declared_and_valid()
        case.test_freshness_policy_is_declared_and_valid()


class TestF4MilestoneCadence(unittest.TestCase):

    def _meta(self):
        return _load("mi", "tests/unit/test_meta_integrity.py")

    def test_max_drift_matches_the_ruling(self):
        """ARTIFACT: the constant is read from the ruling, not asserted twice.

        A literal here would be a second copy of the decision, free to drift.
        """
        contract = _contract()
        declared = re.search(r"MAX_DRIFT\s*=\s*(\d+)", contract)
        self.assertIsNotNone(declared,
                             "the contract records no MAX_DRIFT calibration, so "
                             "there is nothing for the code to agree with")
        self.assertIn(
            self._meta().MAX_DRIFT, (int(declared.group(1)),),
            "MAX_DRIFT in the controls disagrees with the calibration recorded "
            "in the contract. One of them has moved without the ruling.")

    def test_the_calibration_cites_the_measured_distribution(self):
        self.assertIn(str(max(MEASURED)), _contract(),
                      "the calibration must cite the measured maximum, or it "
                      "is a number with no provenance")

    def test_the_understatement_check_is_gone(self):
        """Ruling F4 removed it with the per-commit cadence it encoded.

        Anchored on the assertion direction rather than on the WRITE_OFFSET
        constant, because the first version of this control grepped for the
        constant and a re-introduced check that recomputes the offset inline
        would have sailed past it. Under milestone refresh the declared drift
        legitimately lags, so a control demanding the two track each other
        fails every ordinary commit.
        """
        with open(os.path.join(REPO_ROOT, "tests", "unit",
                               "test_meta_integrity.py"),
                  encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("WRITE_OFFSET", source,
                         "the write-offset tolerance exists only under "
                         "per-commit refresh, which the ruling replaced")
        self.assertNotIn("stated, actual - 1", source,
                         "the drift control compares the declared value against "
                         "actual minus one, which is the per-commit cadence "
                         "reintroduced by the back door")
        self.assertRegex(
            source, r"stated,\s*actual",
            "the drift control must still compare the declared value against "
            "the real one; the overstatement direction is what remains")

    def test_the_cadence_is_declared_not_inferred(self):
        """The ruling forbids tuning the threshold to silence an alarm.

        Anchored on the rule sentence itself. The first version asserted a
        phrase from the sentence that follows it, so deleting the rule left
        every probe intact and the control passed on a contract that no longer
        said anything about retuning.
        """
        contract = _contract()
        self.assertIn("milestone", contract.lower(),
                      "the refresh cadence must be stated, since the window is "
                      "calibrated against it and cannot be justified without")
        self.assertIn(
            "改阈值来消除报警", contract,
            "the contract must forbid retuning the window to silence an "
            "alarm. Without that sentence, a later edit can widen the number "
            "and the only trace is that nothing fires.")


if __name__ == "__main__":
    unittest.main()
