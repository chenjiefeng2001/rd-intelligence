"""F3 / F4 / teardown-fault-shape ruling enforcement.

Defect version, written before the change.

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

Teardown fault shape -- ruling B, decided by direct cdb measurement at the
access violation. Three claims recorded earlier were measured false and
retracted: the `ff 50` indirect virtual call, the zero vtable pointer, and
`0x4A0A4D` as the instruction start. The measured instruction is `48 8b 18`
(`mov rbx, qword ptr [rax]`) at `0x4A0A4E`, with rax == 0 and a non-null,
readable rbx. These controls exist because a retraction recorded only in prose
decays: nothing stopped the superseded shape from being restated as fact, which
is exactly what happened once already.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
CONTRACT = os.path.join(REPO_ROOT, "docs",
                        "DOCUMENT-CLASSIFICATION-CONTRACT.md")
OPEN_DECISIONS = os.path.join(REPO_ROOT, "docs", "OPEN-DECISIONS.md")
FREEZE = os.path.join(REPO_ROOT, "docs", "CURRENT-EVIDENCE-FREEZE.md")
STATUS = os.path.join(os.path.dirname(REPO_ROOT), "STATUS.md")
TEARDOWN = os.path.join(REPO_ROOT, "docs",
                        "TEARDOWN-CRASH-INVESTIGATION.md")
PDB_RESULT = os.path.join(REPO_ROOT, "docs", "PDB-ATTRIBUTION-RESULT.md")

#: The measured fault instruction, as recorded in TEARDOWN section 13.
MEASURED_OFFSET = "0x4A0A4E"
MEASURED_OPCODE = "48 8b 18"
MEASURED_INSTRUCTION = "mov rbx, qword ptr [rax]"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()

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


class TestOpenDecisionsCarriesOnlyOpenItems(unittest.TestCase):
    """The document's own rule: decided items move out, they are not edited.

    OPEN-DECISIONS states that rule in its first section and then listed eight
    resolved items anyway -- F3, F4, both contract-field removals, both noqa
    mechanisms, and the 41-document deferral whose rationale the classification
    ruling replaced. A list of open decisions that mostly contains closed ones
    is worse than no list: it sends the next reader to re-derive decisions
    that were already made.
    """

    #: item -> where the resolution now lives, asserted so the removal cannot be
    #: silent the way the accumulation was
    RESOLVED = {
        "F3": "DOCUMENT-CLASSIFICATION-CONTRACT.md section 9.1",
        "F4": "DOCUMENT-CLASSIFICATION-CONTRACT.md section 9.2",
        "evidence_ref": "CI-ORCHESTRATION-CONTRACT.md 6.1 removal record",
        "duration_s": "CI-ORCHESTRATION-CONTRACT.md 6.1 removal record",
        "noqa": "LINT-EXECUTION-CONTRACT.md governance section",
    }

    def _text(self):
        with open(OPEN_DECISIONS, encoding="utf-8") as fh:
            return fh.read()

    def test_resolved_items_are_not_still_listed_as_open(self):
        text = self._text()
        stale = []
        for marker in ("CLASSIFICATION-CONSISTENCY GAP", "CALIBRATION GAP"):
            if marker in text:
                stale.append(marker)
        if "UNDEFINED BY DECISION" in text:
            stale.append("UNDEFINED BY DECISION")
        self.assertEqual(
            stale, [],
            f"{stale} are still listed as open in OPEN-DECISIONS.md. Each has a "
            "ruling: "
            + "; ".join(f"{k} -> {v}" for k, v in sorted(self.RESOLVED.items())))

    def test_the_removed_field_decisions_are_not_still_open(self):
        """Scoped to the open list, not the whole document.

        Section 4 records that each was moved out, and naming them there is
        required -- a removal that leaves no trace is indistinguishable from
        never having been proposed. The first version of this control scanned
        the whole file and so failed on its own removal record.
        """
        text = self._text()
        cut = text.find("## 4. ")
        self.assertNotEqual(cut, -1,
                            "the document must keep a section recording what "
                            "was moved out and where it was decided")
        open_list, removed = text[:cut], text[cut:]
        for field in ("evidence_ref", "duration_s"):
            self.assertNotIn(
                field, open_list,
                f"{field} was ruled removed from the contract. Leaving it in "
                "the open list makes a settled relaxation look unauthorised.")
            self.assertIn(
                field, removed,
                f"{field} was moved out and must stay named in the removal "
                "record, with the place its decision now lives")

    def test_the_document_states_what_remains_open(self):
        """Empty is only correct if the genuinely open items are still named."""
        text = self._text()
        for still_open in ("Release blocking", "RenderDoc attribution"):
            self.assertIn(
                still_open, text,
                f"{still_open} is frozen or deferred rather than decided, so it "
                "belongs in the open list. Removing it would make the document "
                "claim nothing is outstanding.")

    def test_the_move_out_rule_is_still_stated(self):
        """Anchored on section 2, where the rule is stated.

        The first version searched the whole document for 移出 and passed even
        after the rule sentence was replaced, because the section 4 heading
        still contains the word. Same shape as the anchors that did not bite:
        the probe can be satisfied by text that is not the rule.
        """
        text = self._text()
        start = text.index("## 2. ")
        end = text.index("## 3. ")
        rule = text[start:end]
        self.assertTrue(
            "移入" in rule or "移出" in rule,
            "section 2 must state that decided items move out rather than "
            "being edited in place, or this cleanup happens again by default")


class TestTeardownFaultShapeRuling(unittest.TestCase):
    """The measured fault shape stands, and the retracted one cannot return."""

    def _teardown(self):
        return _read(TEARDOWN)

    def _flat_teardown(self):
        """Whitespace-collapsed, so cdb's column padding cannot hide a match.

        The instruction is recorded twice: once as prose and once inside the
        verbatim transcript, where the mnemonics are column-aligned. Asserting
        the single-spaced form against the raw text would test cdb's layout
        rather than the record.
        """
        return re.sub(r"[ \t]+", " ", self._teardown())

    def _freeze(self):
        return _read(FREEZE)

    def _pdb(self):
        return _read(PDB_RESULT)

    def test_the_measured_facts_are_recorded(self):
        """FLOW: offset, opcode and disassembly come from the debugger.

        Each token is one the retraction replaced, so losing any of them means
        the record drifted back toward the shape that was measured false.
        """
        text = self._flat_teardown()
        for token, what in (
            (MEASURED_OFFSET, "the measured fault offset"),
            (MEASURED_OPCODE, "the measured opcode"),
            (MEASURED_INSTRUCTION, "the measured instruction"),
            ("rax=0000000000000000", "the rax reading"),
            ("rbx=00007ffb0c1edc80", "the rbx reading, as cdb printed it"),
            ("00000000`00000001", "the qword at rbx"),
        ):
            self.assertIn(
                token, text,
                f"{what} is missing from the teardown record. It is the "
                "measurement the whole ruling rests on.")

    def test_the_primary_artifact_is_retained(self):
        """FLOW: the raw debugger output stays next to the claim.

        The numbers above came from one run of a one-shot command. If only the
        interpretation is kept, the record asserts measurements whose only
        source was a temporary log that no longer exists.
        """
        text = self._teardown()
        for token, what in (
            ("Attempt to read from address 0000000000000000",
             "the exception record"),
            ("0:000> dq @rbx L1", "the memory read at rbx"),
            ("0:000> db @rip-10 L26", "the raw bytes"),
            ("cdb version", "the debugger version"),
        ):
            self.assertIn(
                token, text,
                f"{what} is missing. The measured values need a retained "
                "primary artifact, not an interpretation alone.")

    def test_the_retired_claims_cannot_return_to_the_freeze_record(self):
        """FLOW: the frozen summary carries the measurement, not the retraction.

        Anchored on the freeze document because that is the one place a reader
        takes the current shape from without reading the investigation.
        """
        text = self._freeze()
        self.assertNotIn(
            "0x4A0A4D", text,
            "0x4A0A4D was measured not to be an instruction start. If it is "
            "back in the freeze record, the retracted shape is being restated "
            "as current.")
        self.assertIsNone(
            re.search(r"^\s*vtable pointer\s", text, re.MULTILINE),
            "the freeze record used to carry a 'vtable pointer zero' field. The "
            "null is rax; there is no such field to report. Anchored to the "
            "start of a line so the SUPERSEDED annotation that names the old "
            "claim does not trip it.")
        self.assertIn(MEASURED_OFFSET, text)

    def test_each_retraction_is_marked_where_it_lived(self):
        """FLOW: each document that carried a wrong claim still marks it.

        The retraction has to travel with the claim. Correcting the summary
        while leaving the source document asserting the old shape is how the
        two coexisted.
        """
        self.assertIn(
            "已被 §13 实测推翻", self._teardown(),
            "the teardown record must still mark its own 0x4A0A4D section as "
            "refuted, or the retraction is lost with the edit")
        self.assertIn(
            "不再作为", self._pdb(),
            "the PDB result must still mark the static decode as no longer "
            "fact; that document is where the wrong shape originated")

    def test_the_attribution_boundary_is_still_declared(self):
        """FLOW: establishing the shape did not establish the cause.

        The measurement says which instruction faults and which register is
        null. It says nothing about which static owns it or why, so the
        boundary has to remain on the page.
        """
        text = self._teardown()
        for token in ("NOT_ESTABLISHED", "ROOT CAUSE OPEN",
                      "UNAUTHORIZED and NOT STARTED"):
            self.assertIn(
                token, text,
                f"{token} is the boundary the measurement did not cross. Its "
                "absence would let a measured shape read as a known cause.")
        self.assertIn(
            "不命名该全局量", text,
            "the rip-relative target must stay unnamed. Naming it is the next "
            "layer of attribution and was never authorised.")

    def test_the_scope_of_the_measurement_is_stated(self):
        """FLOW: rbx is excluded, not indicted.

        The whole point of ruling B was to ask about rbx. A record that only
        says 'rax == 0' would leave the exclusion unstated, and the earlier
        error was reading rbx as the faulting pointer.
        """
        text = self._teardown()
        self.assertIn(
            "均不是故障源", text,
            "rbx and [rbx] were measured non-null / non-zero; that exclusion "
            "is a result, not an omission")


if __name__ == "__main__":
    unittest.main()
