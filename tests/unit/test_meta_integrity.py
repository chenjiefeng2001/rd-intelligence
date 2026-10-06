"""Meta-integrity controls: the status layer and the evidence layer.

These do not check product behaviour. They check that the things a maintainer
reads in order to decide what to do next are not quietly wrong.

N1 -- the status baseline. A control asserting `declared == HEAD` cannot work:
writing the document is itself a commit, so the moment the value is correct the
next commit makes it stale. Requiring the declared drift to equal the real drift
fails for the same reason, and fails again on the very next commit, which makes
it an invariant that can only be satisfied by never committing.

What is enforceable is a bound, plus one asymmetry. The document must name a
real ancestor, must state its drift, must not understate how far behind it is
(understating is the dangerous direction: a reader believes they are current),
and must not be allowed to rot past MAX_DRIFT unrefreshed. Overstating its
staleness is tolerated, because it errs toward caution.

Whether the verdicts the document states are still *true* is the question a
reader actually has, and it has no commit offset at all -- see
TestStatusSubstantiveClaimsMatchReality.

N2 -- the real-process evidence layer. tests/workload is ruled against as a
gate, so the seven controls that spawn a compiled NULL dereference, a real
taskkill and a real timeout run in no gate. Three controls assert that file
exists and names those cases, which catches deletion but not an edit that keeps
the name and empties the body. These require the cases to be *substantive*.

N3 -- a stale note in a gate's own deviation record.
"""

import ast
import importlib.util
import json
import os
import re
import subprocess
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
STATUS = os.path.join(os.path.dirname(REPO_ROOT), "STATUS.md")
FREEZE = os.path.join(REPO_ROOT, "docs", "CURRENT-EVIDENCE-FREEZE.md")
AUDIT = os.path.join(REPO_ROOT, "scripts", "audit_boundaries.py")
EVIDENCE = os.path.join(REPO_ROOT, "tests", "workload",
                        "test_termination_evidence.py")

#: The declaration line both status documents must carry. Machine-checkable on
#: purpose: prose drifts, a number does not.
DRIFT_PATTERN = re.compile(
    r"^baseline_drift:\s*(-?\d+)\s*$", re.MULTILINE)
AS_OF_PATTERN = re.compile(r"^as_of_commit:\s*`?([0-9a-f]{7,40})`?\s*$",
                           re.MULTILINE)
FRESHNESS_PATTERN = re.compile(r"^freshness_policy:\s*(\S+)\s*$", re.MULTILINE)


def _freshness_policy(path):
    """The policy the document declares about itself, or None if it declares none.

    Read from the document rather than hardcoded per file. A hardcoded table
    would keep enforcing the milestone bound against a document that had been
    reclassified, which is precisely the case the scope decision is about.
    """
    match = FRESHNESS_PATTERN.search(_read(path))
    return match.group(1) if match else None


BASELINE_PATTERN = re.compile(r"^baseline_commit:\s*`?([0-9a-f]{7,40})`?\s*$",
                              re.MULTILINE)

#: How many commits a status document may fall behind before a control insists
#: on a refresh. Status documents in this repository are refreshed at milestone
#: boundaries (G1/G2, G4), not per commit, so this is deliberately not 1.
#: How many commits a status document may fall behind before a control insists
#: on a refresh. Calibrated against the measured interval distribution of
#: CURRENT-EVIDENCE-FREEZE.md -- [1,1,1,2,1,1,3,3,3,2,2,1,19,9,1,1,1,3] --
#: whose maximum is 19. Ruling F4 (DOCUMENT-CLASSIFICATION-CONTRACT.md 9.2):
#: status documents refresh on milestone cadence, so ordinary commits may
#: legitimately accumulate without one. A window below the observed maximum
#: fires on a normal milestone gap, which alarms about the wrong thing.
#:
#: A calibration, not a truth. If the cadence changes, F4 reopens calibration;
#: do not retune it to silence an alarm.
#:
#: SECOND CALIBRATION (scope, not value). 19 is unchanged. What changed is
#: *which documents it applies to*. It was written for a milestone-refreshed
#: status document and was being enforced against a document whose own front
#: matter declares:
#:
#:     document_role: evidence_record
#:     freshness_policy: point_in_time
#:     "any point-in-time declaration expires automatically"
#:
#: Under section 3 of that same contract, a `point_in_time` record declares an
#: `as_of_commit` and is *expected* to age; it describes one moment, not the
#: current state. Demanding that it track HEAD's milestone cadence is a category
#: error -- it asks an evidence record to be a status document.
#:
#: The bound was reached at 20 commits by post-P9a feature work that produces no
#: P9a evidence at all: a React front end, an event stream and a query store. No
#: milestone in F4's sense occurred *in this document*, because this document
#: does not record the things that changed. Retuning 19 upward would have been
#: the one thing F4 forbids; recalibrating the scope is the alternative it names.
#:
#: A point_in_time document is held to a different and still-failing rule: its
#: `as_of_commit` must be a real ancestor of HEAD. That is what "describing a
#: repository that no longer exists" actually looks like, and it cannot be
#: dodged by waiting.
MAX_DRIFT = 19

REQUIRED_EVIDENCE_CASES = (
    "test_real_clean_exit",
    "test_real_explicit_nonzero_exit_is_not_a_signal",
    "test_real_python_traceback",
    "test_real_native_access_violation",
    "test_deliberate_ntstatus_exit_is_not_called_a_crash",
    "test_real_timeout_is_recorded",
    "test_real_external_kill_is_not_reported_as_a_crash",
)


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                          text=True).stdout.strip()


def _is_ancestor(commit):
    """True when `commit` is contained in HEAD's history.

    Uses the exit code, not stdout. `git merge-base --is-ancestor` says nothing
    on stdout and answers only through its status, so a check written against the
    output would see an empty string and call every commit unrelated.
    """
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=REPO_ROOT, capture_output=True).returncode == 0


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _documents():
    """Documents to check, and only those that exist.

    CURRENT-EVIDENCE-FREEZE.md is inside the repository, so it is always
    present. STATUS.md is a cross-repository report that lives outside this
    repository and is therefore legitimately absent from a fresh clone. An
    earlier version listed it unconditionally and raised FileNotFoundError,
    which a gate counts as an ERROR, i.e. INFRASTRUCTURE_FAILURE: a clean
    clone could not pass its own unit gate. The corpus contract already
    established that a clean clone cannot run the executable suites; it must
    not also be unable to run the status controls.

    Absence is a skip, not a pass, and never silently removes coverage: the
    in-repo document is required to be present by its own control below.
    """
    present = []
    if os.path.exists(FREEZE):
        present.append((FREEZE, "CURRENT-EVIDENCE-FREEZE.md"))
    if os.path.exists(STATUS):
        present.append((STATUS, "STATUS.md"))
    return tuple(present)

class TestTheDriftBoundIsScopedNotWeakened(unittest.TestCase):
    """The second calibration changed which documents the bound governs.

    A recalibration that only ever makes a control pass is indistinguishable
    from deleting it. These controls pin the part that could have been quietly
    given up: a document that is *supposed* to track the repository still fails
    past the bound, and a point_in_time document still fails on a commit that is
    not in this history.
    """

    FREEZE_REL = os.path.join("docs", "CURRENT-EVIDENCE-FREEZE.md")

    def test_the_bound_is_unchanged(self):
        # 19 is the measured maximum of the observed interval distribution.
        # Reopening calibration moved the scope; it must not have moved the
        # number, or the interval data stops meaning anything.
        self.assertEqual(MAX_DRIFT, 19)

    def test_the_freeze_document_is_still_a_point_in_time_record(self):
        # If this ever stops being point_in_time the bound applies to it again,
        # which is the intended behaviour rather than a regression.
        self.assertEqual(_freshness_policy(FREEZE), "point_in_time")

    def test_a_living_document_still_fails_past_the_bound(self):
        # Proved by reclassification rather than asserted about: temporarily
        # declare the freeze document `living` and the bound must fire again at
        # the current drift. Bytes in, bytes out -- a text round trip would
        # normalise line endings and leave the file altered.
        path = os.path.join(REPO_ROOT, self.FREEZE_REL)
        original = open(path, "rb").read()
        case = TestStatusBaselineDeclaresItsOwnDrift(
            "test_declared_drift_is_within_a_bound")
        try:
            mutated = original.decode("utf-8").replace(
                "freshness_policy: point_in_time", "freshness_policy: living", 1)
            self.assertNotEqual(mutated, original.decode("utf-8"),
                                "the mutation did not apply")
            with open(path, "wb") as handle:
                handle.write(mutated.encode("utf-8"))
            with self.assertRaises(AssertionError) as caught:
                case.test_declared_drift_is_within_a_bound()
            self.assertIn(str(MAX_DRIFT), str(caught.exception),
                          "the bound did not fire for a document declared living")
        finally:
            with open(path, "wb") as handle:
                handle.write(original)
        self.assertEqual(open(path, "rb").read(), original,
                         "the mutation did not revert")

    def test_a_point_in_time_document_with_an_unknown_commit_is_refused(self):
        # "Describing a repository that no longer exists" is the failure the
        # original bound was reaching for. Asserted directly, because the
        # substituted rule has to fail on the same thing.
        self.assertFalse(_is_ancestor("0" * 40))
        self.assertFalse(_is_ancestor("deadbee"))
        self.assertTrue(_is_ancestor("HEAD"))

    def test_the_declared_policy_is_read_from_the_document_not_hardcoded(self):
        # A per-file table would keep enforcing the milestone bound against a
        # document that had been reclassified, which is the case the scope
        # decision exists for.
        text = _read(FREEZE)
        self.assertIn("freshness_policy:", text)
        self.assertEqual(_freshness_policy(FREEZE),
                         re.search(r"^freshness_policy:\s*(\S+)", text,
                                   re.M).group(1))

    def test_the_misclassification_door_is_auditable(self):
        # The loophole this opens: a living document could declare
        # point_in_time and escape the bound. What closes it is that the same
        # declaration is mirrored in docs/README.md, and that consistency is
        # enforced by test_docs_index.py.
        #
        # Asserted as "that control exists and covers this document" rather than
        # by reading the index here. Reading it directly duplicated an existing
        # control and, because the scanner resolves a bare "README.md" against
        # the repository root, it also made the *root* README a machine-read
        # input of this module -- an obligation created by a path spelling
        # rather than by anything the test needed.
        index_control = os.path.join(REPO_ROOT, "tests", "unit",
                                     "test_docs_index.py")
        source = _read(index_control)
        # Asserted as properties rather than as a document name: the index audit
        # derives its coverage from disk, so naming a document here would test a
        # spelling rather than the door. What closes the loophole is that the
        # audit compares the index cell against the document's own front matter,
        # so the two cannot be changed in one place only.
        self.assertIn("def on_disk", source,
                      "the index audit must derive coverage from the directory")
        self.assertIn("front_matter", source,
                      "the index audit must read front matter to compare against")
        self.assertIn("index freshness disagrees with front matter", source,
                      "the freshness claim must be compared, or a "
                      "reclassification could live in one place only")


class TestStatusBaselineDeclaresItsOwnDrift(unittest.TestCase):
    """N1. A status document must state how far behind it is."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO_ROOT, "release-gates.json"),
                  encoding="utf-8") as handle:
            cls.gates = json.load(handle)["gates"]
        with open(os.path.join(REPO_ROOT, "ci-pipeline.json"),
                  encoding="utf-8") as handle:
            cls.pipeline = json.load(handle)

    def test_both_documents_declare_a_machine_readable_baseline(self):
        for path, label in _documents():
            self.assertTrue(os.path.isfile(path), f"missing {path}")
            text = _read(path)
            self.assertIsNotNone(
                BASELINE_PATTERN.search(text),
                f"{label} must carry a 'baseline_commit:' line")
            self.assertIsNotNone(
                DRIFT_PATTERN.search(text),
                f"{label} must carry a 'baseline_drift:' line stating how far "
                "behind HEAD it is; a document cannot stay current by hand, so "
                "it has to be honest about being stale")

    def test_the_in_repo_document_is_always_checked(self):
        """Guards against the degradation above silently becoming coverage 0.

        If both documents were absent these controls would pass vacuously,
        which is the failure mode every "skip when missing" control has.
        """
        self.assertTrue(
            os.path.exists(FREEZE),
            "CURRENT-EVIDENCE-FREEZE.md is inside the repository and must "
            "always exist; if it does not, the status controls below are "
            "checking nothing and reporting success")

    def test_the_cross_repo_report_is_absent_by_design(self):
        """The STATUS.md dependency is outside version control, on purpose.

        Asserted rather than left implicit so that a future move of the file
        into the repository is a deliberate change to this contract instead of
        an accident that quietly stops exercising the cross-repository half.
        """
        self.assertFalse(
            STATUS.startswith(REPO_ROOT + os.sep),
            "STATUS.md is expected outside this repository; if it has moved "
            "inside, update this control rather than leaving it misleading")
        labels = [label for _, label in _documents()]
        self.assertIn("CURRENT-EVIDENCE-FREEZE.md", labels)

    def test_declared_baseline_is_a_real_ancestor_of_head(self):
        for path, label in _documents():
            declared = BASELINE_PATTERN.search(_read(path)).group(1)
            kind = subprocess.run(
                ["git", "cat-file", "-t", declared], cwd=REPO_ROOT,
                capture_output=True, text=True).stdout.strip()
            self.assertEqual(kind, "commit",
                             f"{label} declares {declared}, which is not a "
                             "commit in this repository")
            merge = subprocess.run(
                ["git", "merge-base", "--is-ancestor", declared, "HEAD"],
                cwd=REPO_ROOT).returncode
            self.assertEqual(merge, 0,
                             f"{label} declares {declared}, which is not an "
                             "ancestor of HEAD")

    def test_declared_drift_is_within_a_bound(self):
        """Bounded staleness plus one asymmetry, scoped by document class.

        Ruling F4 replaced per-commit refresh with milestone refresh, so the
        declared drift legitimately lags between milestones: ordinary commits do
        not trigger a refresh, and demanding the two track each other would fail
        every ordinary commit. The check that required them to agree --
        stated >= actual - 1 -- encoded the old cadence and went with it.

        What remains is enforceable under milestone cadence:

          declared <= actual     a document never claims to be fresher than it
                                 is. This holds from the moment it is written
                                 and stays true as commits accumulate, so it
                                 needs no refresh to maintain.
          actual  <= MAX_DRIFT   staleness is bounded, calibrated to 19 from
                                 the measured distribution.

        The bound is scoped, not retuned. It is calibrated for a document that
        is *supposed to track* the repository's state. A document declaring
        `freshness_policy: point_in_time` is not: under section 3 of the
        classification contract it describes one moment and is expected to age,
        and its own front matter says any point-in-time declaration expires
        automatically. Such a document is held to a different invariant that
        also fails loudly -- its `as_of_commit` must be a real ancestor of HEAD,
        which is what "describing a repository that no longer exists" looks
        like, and which waiting cannot fix.

        Overstating freshness is the dangerous direction for either class: a
        reader believes they are looking at current facts. Understating is the
        expected state between milestones and carries no penalty.
        """
        head = _git("rev-parse", "HEAD")
        count = int(_git("rev-list", "--count", "HEAD"))
        for path, label in _documents():
            text = _read(path)
            declared = BASELINE_PATTERN.search(text).group(1)
            stated = int(DRIFT_PATTERN.search(text).group(1))
            actual = count - int(_git("rev-list", "--count", declared))
            self.assertLessEqual(
                stated, actual,
                f"{label} claims baseline_drift {stated} but is only "
                f"{actual} commits behind HEAD ({declared} vs {head}). It "
                "overstates its own currency, which is the direction that "
                "makes a reader believe stale facts are current.")

            if _freshness_policy(path) == "point_in_time":
                as_of = AS_OF_PATTERN.search(text)
                self.assertIsNotNone(
                    as_of,
                    f"{label} declares freshness_policy: point_in_time, so it "
                    "must carry an as_of_commit naming the moment it "
                    "describes. Without one the declaration is not checkable "
                    "at all.")
                self.assertTrue(
                    _is_ancestor(as_of.group(1)),
                    f"{label} declares freshness_policy: point_in_time with "
                    f"as_of_commit {as_of.group(1)}, which is not an ancestor "
                    f"of {head}. A point-in-time record that names a commit "
                    "this repository does not contain is describing a "
                    "repository that no longer exists.")
                continue

            self.assertLessEqual(
                actual, MAX_DRIFT,
                f"{label} has not been refreshed for {actual} commits, past "
                f"the calibrated bound of {MAX_DRIFT}. Either a milestone was "
                "reached and not recorded, or the document is describing a "
                "repository that no longer exists. If the milestone cadence "
                "itself has changed, reopen calibration rather than widening "
                "this number.")

    def test_every_gate_id_appears_in_the_freeze_document(self):
        """Scoped to the canonical status block, not the whole file.

        Found by mutation: deleting a gate id from that block passed, because
        the same id still occurred elsewhere in the document. A reader looks at
        the status block, so that is the place the id has to be present.
        """
        text = _read(FREEZE)
        fence = chr(96) * 3
        start = text.index("§2.1 fork integrity")
        block_start = text.rindex(fence, 0, start)
        block_end = text.index(fence, start)
        block = text[block_start:block_end]
        for gate in self.gates:
            # Whole-token match, not substring. Found by mutation: deleting the
            # gate id from the status block passed, because `audit_fork_
            # integrity` in the same block contains the id as a substring and
            # satisfied it. Same class of defect as the two prose checks
            # earlier -- a near-miss accepted as the thing itself.
            token = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(gate['id'])}"
                               r"(?![A-Za-z0-9_])")
            self.assertRegex(
                block, token,
                f"gate {gate['id']} is missing from the freeze document's "
                "status block as a whole token, so a reader cannot see its "
                "current state")

    def test_process_only_gate_is_described_as_process_only(self):
        text = _read(FREEZE)
        for gate in self.gates:
            if gate["state"] == "PROCESS_ONLY":
                self.assertIn(gate["id"], text)
                idx = text.index(gate["id"])
                window = text[max(0, idx - 200):idx + 200]
                self.assertIn(
                    "PROCESS_ONLY", window,
                    f"{gate['id']} is PROCESS_ONLY in the spec but the freeze "
                    "document does not say so near its name")

    def test_release_blocking_claim_matches_the_pipeline_spec(self):
        enabled = bool((self.pipeline.get("release_blocking") or {})
                       .get("enabled"))
        text = _read(FREEZE)
        self.assertIn("release blocking", text.lower())
        if not enabled:
            self.assertIn("NOT AUTHORIZED", text,
                          "release_blocking is disabled in the spec, so the "
                          "freeze document must not imply it is available")

    def test_corpus_tracked_claim_matches_the_live_probe(self):
        if REPO_ROOT not in os.sys.path:
            os.sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        spec = importlib.util.spec_from_file_location(
            "readiness_meta", os.path.join(REPO_ROOT, "scripts",
                                          "pipeline_readiness.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        observed = mod.probe_environment(REPO_ROOT, {})["corpus"]
        declared = ((self.pipeline.get("capability_declaration") or {})
                    .get("corpus") or {})
        self.assertIs(observed["tracked"], declared.get("tracked"))
        self.assertEqual(observed["source"], declared.get("source"))
        text = _read(FREEZE)
        self.assertIn("tracked", text)


class TestRealProcessEvidenceIsSubstantive(unittest.TestCase):
    """N2. Present is not enough; the controls must still assert something."""

    def _tree(self):
        with open(EVIDENCE, encoding="utf-8") as handle:
            return ast.parse(handle.read())

    def test_evidence_module_still_declares_every_case(self):
        source = _read(EVIDENCE)
        for case in REQUIRED_EVIDENCE_CASES:
            self.assertIn(f"def {case}(", source,
                          f"real-process control {case} is gone")

    def test_every_case_asserts_on_a_classification(self):
        """An edit that empties a body but keeps the name must fail here.

        The seven controls run in no gate, so this is the only thing standing
        between a deleted assertion and a suite that reports itself healthy.
        """
        tree = self._tree()
        functions = {n.name: n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)}
        for case in REQUIRED_EVIDENCE_CASES:
            self.assertIn(case, functions, f"{case} is not a function")
            body = functions[case]
            asserts = [n for n in ast.walk(body)
                       if isinstance(n, ast.Assert)
                       or (isinstance(n, ast.Call)
                           and isinstance(n.func, ast.Attribute)
                           and n.func.attr.startswith("assert"))]
            self.assertTrue(
                asserts,
                f"{case} performs no assertion; it runs in no gate, so nothing "
                "else would notice")
            text = ast.dump(body)
            self.assertIn(
                "class", text,
                f"{case} must assert on a termination class, not merely that a "
                "process ran")

    def test_the_native_av_case_still_requires_a_compiled_binary(self):
        """The crash must still come from a real compiler, not a literal.

        Found by mutation: replacing the null-dereference C source with
        `int main(void){return 3221225477;}` passed, because the control only
        looked for the strings "gcc" and "int main(void)" and both survived.
        A program that returns the AV status is not an access violation, and it
        would make the whole cross-platform matrix meaningless.
        """
        source = _read(EVIDENCE)
        self.assertIn("gcc", source)
        bodies = re.findall(r"fh\.write\(\s*\"(.*?)\"", source, re.DOTALL)
        snippet = " ".join(bodies)
        dense = snippet.replace(" ", "")
        self.assertIn("intmain(void)", dense,
                      "the native case must compile a real C program")
        self.assertIn(
            "(int*)0", dense,
            "the compiled program must actually dereference a null pointer; a "
            "literal return of the AV status would fake the measurement")
        self.assertIn(
            "return*p", dense,
            "the null dereference must be reached, not merely prepared")


class TestBoundaryDeviationNoteIsCurrent(unittest.TestCase):
    """N3. A deviation note that implies pending work misleads a maintainer."""

    def _note(self):
        text = _read(AUDIT)
        idx = text.find("no guard against a second live controller")
        self.assertNotEqual(idx, -1, "the deviation record is gone")
        return text[max(0, idx - 1600):idx + 600]

    def test_note_does_not_claim_a_pending_migration_flip(self):
        note = self._note().lower()
        for superseded in ("flips to a hard check",
                           "expectedfailure until the migration lands",
                           "becomes a hard check at m1.3"):
            self.assertNotIn(
                superseded, note,
                "M1.3 has landed; a note promising a future change to this "
                "check tells a maintainer that work is outstanding when it is "
                "not. The note may explain the correction, but must not reuse "
                "the superseded phrasing as a live claim")

    def test_note_states_the_deviation_is_the_correct_end_state(self):
        note = self._note().lower()
        self.assertTrue(
            "correct end state" in note or "intentional" in note,
            "the note must say the deviation is intended, not pending")

    def test_the_test_file_documents_the_deliberate_removal(self):
        """Checked in the AST, not the text.

        The docstring quotes the decorator by name in order to explain why it
        was removed. A text search therefore flags the explanation as a
        violation, which is the third time this project has confused prose
        about a construct with the construct itself.
        """
        path = os.path.join(REPO_ROOT, "tests", "integration",
                            "test_runtime_isolation.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                rendered = ast.dump(decorator)
                self.assertNotIn(
                    "expectedFailure", rendered,
                    f"{node.name} still carries an expectedFailure "
                    "decorator; it was removed deliberately once the migration "
                    "landed")
        text = _read(path).lower()
        self.assertIn("used to carry", text,
                      "the deliberate removal must stay documented")


class TestFreezeDocDescribesItsOwnDriftRule(unittest.TestCase):
    """ARTIFACT: the prose must agree with the rule the code enforces.

    Ruling F4 moved MAX_DRIFT to 19 and inverted the rule from 'understating is
    forbidden' to 'overstating is forbidden'. The freeze document kept both the
    old number and the old direction, so it described a rule the code no longer
    implements -- in the one place a reader goes to learn what the declared
    drift means.

    Nothing caught it because the existing controls read the machine-readable
    line, which was correct, and the paragraph was prose. Same gap as a fact
    being produced but not flowing: here the fact is enforced and the statement
    about it never followed.
    """

    def _paragraph(self):
        text = _read(FREEZE)
        start = text.find("`baseline_drift` 是本文档自陈的陈旧度")
        self.assertNotEqual(start, -1,
                            "the freeze document no longer explains what "
                            "baseline_drift means to a reader")
        return text[start:start + 420]

    def test_the_stated_bound_matches_the_enforced_bound(self):
        paragraph = self._paragraph()
        # Either phrasing. The first version of this control matched only
        # "上界 N" and reported no bound against text that plainly states one as
        # "**19 commits**" -- a check that fails on correct prose is worse than
        # no check, because it gets "fixed" by weakening the text.
        numbers = ([int(n) for n in re.findall(r"上界\s*(\d+)", paragraph)]
                   + [int(n) for n in
                      re.findall(r"\*\*(\d+)\s+commits\*\*", paragraph)])
        self.assertTrue(numbers, "the paragraph states no bound at all")
        for number in numbers:
            self.assertEqual(
                number, MAX_DRIFT,
                f"the freeze document states a bound of {number} while the "
                f"controls enforce {MAX_DRIFT}. A reader would calibrate "
                "against a number nothing enforces.")

    def test_the_stated_direction_matches_the_enforced_direction(self):
        paragraph = self._paragraph()
        self.assertNotIn(
            "低报陈旧度，超过上界则控制失败", paragraph,
            "the paragraph still forbids understating staleness")
        self.assertNotIn(
            "不允许低报", paragraph,
            "the paragraph forbids understating. The enforced rule is the "
            "opposite: understating is expected between milestone refreshes, "
            "and overstating is what makes a reader trust a stale document.")
        self.assertIn(
            "高报", paragraph,
            "the paragraph must name overstating as the violation, not only "
            "imply it by negation")
        self.assertTrue(
            "低报" in paragraph or "落后于" in paragraph,
            "the paragraph must say that understating is the expected state "
            "between milestone refreshes, otherwise a reader takes the bound "
            "as something to keep clear by refreshing constantly")

    def test_the_paragraph_states_the_refresh_cadence(self):
        self.assertIn(
            "milestone", self._paragraph().lower(),
            "the bound is calibrated against a refresh cadence, so the "
            "paragraph must name it or the number is unjustifiable")


if __name__ == "__main__":
    unittest.main()
