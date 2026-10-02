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
BASELINE_PATTERN = re.compile(r"^baseline_commit:\s*`?([0-9a-f]{7,40})`?\s*$",
                              re.MULTILINE)

#: How many commits a status document may fall behind before a control insists
#: on a refresh. Status documents in this repository are refreshed at milestone
#: boundaries (G1/G2, G4), not per commit, so this is deliberately not 1.
MAX_DRIFT = 5

#: The commit that writes a document is the next commit, so a document that was
#: accurate when written is one behind immediately. That is the only lag a
#: correctly-refreshed document is entitled to, and only in the safe direction.
WRITE_OFFSET = 1

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


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


class TestStatusBaselineDeclaresItsOwnDrift(unittest.TestCase):
    """N1. A status document must state how far behind it is."""

    def _documents(self):
        return ((STATUS, "STATUS.md"), (FREEZE, "CURRENT-EVIDENCE-FREEZE.md"))

    def test_both_documents_declare_a_machine_readable_baseline(self):
        for path, label in self._documents():
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

    def test_declared_baseline_is_a_real_ancestor_of_head(self):
        for path, label in self._documents():
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
        """Bounded staleness, not exact equality.

        The first version of this control required the stated drift to equal
        the real drift. That is unachievable under normal development: the
        commit that writes the document is itself the next commit, so a correct
        value is stale the moment it lands, and the control failed again on the
        very next commit. An invariant that can only be satisfied by never
        committing is not an invariant.

        The enforceable property is a bound plus one asymmetry. The document must
        declare a baseline that is a real ancestor, must state its drift so a
        reader can see it, must not understate how far behind it actually is,
        and must not rot past MAX_DRIFT unrefreshed. Understating is the
        direction that matters: it tells a reader they are looking at current
        facts when they are not. Overstating errs toward caution and is
        tolerated.

        Requiring exact equality instead is not stricter, it is unreachable. It
        failed again on the commit immediately following the one that wrote the
        number, which is the control failing for a reason no author can act on.
        What actually matters -- whether the verdicts it states are still true
        -- is covered by TestStatusSubstantiveClaimsMatchReality, which has no
        commit offset to fight.
        """
        head = _git("rev-parse", "HEAD")
        count = int(_git("rev-list", "--count", "HEAD"))
        for path, label in self._documents():
            text = _read(path)
            declared = BASELINE_PATTERN.search(text).group(1)
            stated = int(DRIFT_PATTERN.search(text).group(1))
            actual = count - int(_git("rev-list", "--count", declared))
            self.assertGreaterEqual(
                stated, actual - WRITE_OFFSET,
                f"{label} understates its own staleness: it claims "
                f"baseline_drift {stated} while being {actual} commits behind "
                f"HEAD ({declared} vs {head}). A reader would believe these "
                "facts are current when they are not.")
            self.assertLessEqual(
                actual, MAX_DRIFT,
                f"{label} has not been refreshed for {actual} commits, past "
                f"the bound of {MAX_DRIFT}. Refresh the baseline, or the "
                "document is describing a repository that no longer exists")


class TestStatusSubstantiveClaimsMatchReality(unittest.TestCase):
    """A correct commit hash still does not make a stale verdict true."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO_ROOT, "release-gates.json"),
                  encoding="utf-8") as handle:
            cls.gates = json.load(handle)["gates"]
        with open(os.path.join(REPO_ROOT, "ci-pipeline.json"),
                  encoding="utf-8") as handle:
            cls.pipeline = json.load(handle)

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
            token = re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])"
                               % re.escape(gate["id"]))
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


if __name__ == "__main__":
    unittest.main()
