"""Controls for the capture corpus being a declared external prerequisite.

Ruled 2026-10-02. Captures are third-party generated artefacts whose source
authorisation, redistribution rights and lifecycle ownership are **not**
established, so they are not version controlled. That is a governance decision,
not an omission, and it has to be *declared* rather than left implicit -- the
previous state had the corpus consumed by gates, ignored by git, and named by
nothing, which is the one option that was rejected.

These controls exist because a declaration nobody checks is a comment. They pin
the declaration, the absence semantics, and the things the contract must not
contain.
"""

import ast
import importlib.util
import json
import os
import re
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
CONTRACT = os.path.join(REPO_ROOT, "docs", "CAPTURE-CORPUS-CONTRACT.md")
PIPELINE_SPEC = os.path.join(REPO_ROOT, "ci-pipeline.json")
GATE_SPEC = os.path.join(REPO_ROOT, "release-gates.json")

#: The four facts the ruling requires readiness to report.
REQUIRED_CORPUS_FIELDS = ("required", "source", "tracked", "provenance_required")

CAPTURE_CONSUMING_GATES = ("integration", "cold_warm_equivalence")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _readiness():
    if REPO_ROOT not in os.sys.path:
        os.sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    return _load("pipeline_readiness_c", os.path.join(
        REPO_ROOT, "scripts", "pipeline_readiness.py"))


class TestCorpusIsDeclaredExternal(unittest.TestCase):
    """The ruling's four fields, reported rather than implied."""

    @classmethod
    def setUpClass(cls):
        cls.R = _readiness()

    def test_corpus_probe_reports_every_required_field(self):
        observed = self.R.probe_environment(REPO_ROOT, {})["corpus"]
        for field in REQUIRED_CORPUS_FIELDS:
            self.assertIn(field, observed,
                          f"readiness must report corpus.{field}; a corpus "
                          "that is only detected is an implicit assumption")

    def test_corpus_is_required_and_external(self):
        observed = self.R.probe_environment(REPO_ROOT, {})["corpus"]
        self.assertIs(observed["required"], True,
                      "replay-based verification cannot run without captures")
        self.assertEqual(observed["source"], "external")
        self.assertIs(observed["provenance_required"], True)

    def test_tracked_is_a_boolean_claim_not_just_a_count(self):
        observed = self.R.probe_environment(REPO_ROOT, {})["corpus"]
        self.assertIsInstance(observed["tracked"], bool)
        self.assertIsInstance(observed["tracked_captures"], int)
        # A non-zero count is a contract violation, not a capability, so the
        # two fields must not be allowed to drift into the same thing.
        self.assertEqual(observed["tracked"],
                         observed["tracked_captures"] > 0)

    def test_tracked_is_derived_from_observation_not_hardcoded(self):
        """A hardcoded False would be indistinguishable from a derived one.

        Found by mutation: replacing `bool(tracked)` with a literal `False`
        passed every control, because this repository has zero tracked captures
        so both expressions evaluate to False. The declaration would then be a
        constant that silently stops being true the day a capture is committed.

        Proven here by making the observation report a tracked file. No capture
        is added to the repository to do it -- that would violate the very
        Contract under test.
        """
        import subprocess as real_subprocess

        original = real_subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "git" in cmd and "ls-files" in cmd:
                return type("R", (), {
                    "stdout": "tests/workload/corpus/example.rdc\n",
                    "returncode": 0})()
            return original(cmd, *args, **kwargs)

        self.R.subprocess.run = fake_run
        try:
            observed = self.R.probe_environment(REPO_ROOT, {})["corpus"]
        finally:
            self.R.subprocess.run = original
        self.assertEqual(observed["tracked_captures"], 1)
        self.assertIs(
            observed["tracked"], True,
            "tracked must be derived from the observation; a hardcoded False "
            "cannot report a contract violation when captures are committed")

    def test_absence_is_reported_as_absent_not_as_a_pass(self):
        observed = self.R.probe_environment(REPO_ROOT, {})["corpus"]
        self.assertIsInstance(observed["captures_present"], bool)


class TestAbsenceSemantics(unittest.TestCase):
    """Absent corpus is an infrastructure failure and nothing else."""

    @classmethod
    def setUpClass(cls):
        cls.G = _load("release_gate_c", os.path.join(
            REPO_ROOT, "scripts", "release_gate.py"))

    def _gate_with_capture_requirement(self):
        spec = json.load(open(GATE_SPEC, encoding="utf-8"))
        gate = next(g for g in spec["gates"]
                    if g["id"] in CAPTURE_CONSUMING_GATES
                    and (g.get("requires") or {}).get("capture"))
        return dict(gate)

    def test_gates_that_replay_declare_a_capture_requirement(self):
        spec = json.load(open(GATE_SPEC, encoding="utf-8"))
        for gate_id in CAPTURE_CONSUMING_GATES:
            gate = next(g for g in spec["gates"] if g["id"] == gate_id)
            self.assertTrue(
                (gate.get("requires") or {}).get("capture"),
                f"{gate_id} consumes captures and must declare it")

    def test_missing_capture_is_infrastructure_failure(self):
        gate = self._gate_with_capture_requirement()
        # No capture path in the environment: the gate must not run and must
        # not be reported as a regression or a pass.
        rec = self.G.run_gate(gate, REPO_ROOT, env={})
        self.assertEqual(rec["outcome"], self.G.INFRA)
        self.assertNotEqual(rec["outcome"], self.G.REGRESSION)
        self.assertNotEqual(rec["outcome"], self.G.PASS)

    def test_the_reason_names_the_capture(self):
        gate = self._gate_with_capture_requirement()
        rec = self.G.run_gate(gate, REPO_ROOT, env={})
        self.assertIn("capture", rec["detail"].lower(),
                      "the reason must name what was missing, so a blocked run "
                      "is auditable rather than merely red")

    def test_missing_capture_is_reported_before_the_gate_runs(self):
        gate = self._gate_with_capture_requirement()
        rec = self.G.run_gate(gate, REPO_ROOT, env={})
        self.assertEqual(rec["executed"], 0)
        self.assertIsNone(rec.get("tests_executed"),
                          "nothing ran, so no test result may be reported")


class TestContractDocumentExists(unittest.TestCase):
    """A ruling that lives only in chat has no force."""

    @staticmethod
    def _R_probe():
        if REPO_ROOT not in os.sys.path:
            os.sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        return _readiness().probe_environment(REPO_ROOT, {})

    def test_contract_file_exists(self):
        self.assertTrue(os.path.isfile(CONTRACT),
                        f"missing {CONTRACT}")

    def _text(self):
        with open(CONTRACT, encoding="utf-8") as handle:
            return handle.read()

    def test_contract_states_each_required_rule(self):
        text = self._text().lower()
        for phrase, why in (
                ("external", "the corpus is an external prerequisite"),
                ("not version controlled", "captures are not tracked in git"),
                ("infrastructure_failure", "absence maps to INFRA"),
                ("regression", "absence must never become a regression"),
                ("pass", "absence must never become a pass"),
                ("provenance", "provenance is required"),
                # The ruling said "fake capture"; the Contract words the same
                # prohibition as generating, synthesising or substituting. The
                # control follows the Contract's vocabulary rather than
                # demanding a synonym, which is what a wording-only difference
                # should not turn into a failure.
                ("substitut", "substitute captures are forbidden"),
                ("synthes", "substitute captures are forbidden"),
                # Found by mutation: deleting the whole Forbidden section
                # passed, because every prohibition phrase also appears in the
                # decision block and the absence-semantics section. The section
                # has to be pinned by its own identity, not by shared wording.
                ("forbidden", "the prohibitions are stated as forbidden")):
            self.assertIn(phrase, text, f"the contract must state {why!r}")

    def test_contract_contains_no_machine_specific_paths(self):
        text = self._text()
        for pattern, why in (
                (r"[A-Z]:\\\\", "an absolute Windows path"),
                (r"/Users/", "a macOS home path"),
                (r"/home/[a-z]", "a Linux home path"),
                (r"c:\\\\renderdoc", "this machine's layout")):
            self.assertIsNone(
                re.search(pattern, text, re.IGNORECASE),
                f"the contract must not contain {why}; it describes a "
                "prerequisite, not this machine")

    def test_contract_contains_no_download_urls(self):
        text = self._text()
        self.assertIsNone(
            re.search(r"https?://", text),
            "the contract must not carry a download URL; acquisition is "
            "external and unauthorised sources are out of scope")

    def test_pipeline_spec_declares_the_corpus_facts(self):
        spec = json.load(open(PIPELINE_SPEC, encoding="utf-8"))
        corpus = (spec.get("capability_declaration") or {}).get("corpus") or {}
        declared = set(corpus.get("declares") or ())
        for field in REQUIRED_CORPUS_FIELDS:
            self.assertIn(field, declared,
                          f"ci-pipeline.json must declare corpus.{field}")

    def test_pipeline_spec_declares_the_corpus_values_not_only_the_names(self):
        """A field name with the wrong value is not a declaration.

        Found by mutation: flipping the spec's provenance_required to false
        passed, because the control only checked that the field names appeared
        in the declares list.
        """
        spec = json.load(open(PIPELINE_SPEC, encoding="utf-8"))
        corpus = (spec.get("capability_declaration") or {}).get("corpus") or {}
        self.assertIs(corpus.get("required"), True)
        self.assertEqual(corpus.get("source"), "external")
        self.assertIs(corpus.get("tracked"), False)
        self.assertIs(corpus.get("provenance_required"), True)
        self.assertIn("CAPTURE-CORPUS-CONTRACT", str(corpus.get("contract")),
                      "the spec must point at the Contract that governs it")

    def test_contract_and_probe_agree(self):
        """The document and the probe must not drift into two truths."""
        spec = json.load(open(PIPELINE_SPEC, encoding="utf-8"))
        corpus = (spec.get("capability_declaration") or {}).get("corpus") or {}
        observed = self._R_probe()["corpus"]
        for field in REQUIRED_CORPUS_FIELDS:
            self.assertEqual(
                observed[field], corpus[field],
                f"readiness reports corpus.{field} = {observed[field]!r} but "
                f"ci-pipeline.json declares {corpus[field]!r}")

    def test_readiness_module_does_not_generate_or_synthesise_captures(self):
        """No substitute capture may be produced to make a gate run."""
        with open(os.path.join(REPO_ROOT, "scripts", "pipeline_readiness.py"),
                  encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                called.add(getattr(func, "attr", None)
                           or getattr(func, "id", None))
        for banned in ("urlretrieve", "urlopen", "copy", "copyfile",
                       "shutil"):
            self.assertNotIn(
                banned, called,
                f"readiness must not produce a capture ({banned}); a "
                "substitute would make absence invisible")


if __name__ == "__main__":
    unittest.main()
