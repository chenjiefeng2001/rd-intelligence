"""Meta-integrity controls: the status layer and the evidence layer.

These do not check product behaviour. They check that the things a maintainer
reads in order to decide what to do next are not quietly wrong.

N1 -- the status baseline. A control asserting `declared == HEAD` cannot work:
writing the document is itself a commit, so the moment the value is correct the
next commit makes it stale. The enforceable invariant is therefore that the
document **declares its own drift** and the declared number matches reality. An
author who stops updating it gets a failing control instead of a document that
silently describes a repository that no longer exists.

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

    def test_declared_drift_matches_reality(self):
        head = _git("rev-parse", "HEAD")
        count = int(_git("rev-list", "--count", "HEAD"))
        for path, label in self._documents():
            text = _read(path)
            declared = BASELINE_PATTERN.search(text).group(1)
            declared_count = int(_git("rev-list", "--count", declared))
            actual_drift = count - declared_count
            stated = int(DRIFT_PATTERN.search(text).group(1))
            self.assertEqual(
                stated, actual_drift,
                f"{label} states baseline_drift {stated} but is actually "
                f"{actual_drift} commits behind HEAD ({declared} vs {head})")


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
        text = _read(FREEZE)
        for gate in self.gates:
            self.assertIn(gate["id"], text,
                          f"gate {gate['id']} is missing from the freeze "
                          "document, so a reader cannot see its current state")

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
        """The crash case must still come from a real compiler, not a literal."""
        source = _read(EVIDENCE)
        self.assertIn("gcc", source)
        self.assertIn("int main(void)", source,
                      "the native access violation must still be a compiled C "
                      "program, not a hard-coded return code")


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
