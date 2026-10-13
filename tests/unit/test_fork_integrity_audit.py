"""Controls for the DESIGN_SPEC 2.1.1 fork integrity verifier.

The verifier exists because a plain `git status --porcelain` check is not the
rule the spec means. That check passes for a fork that silently diverged
from upstream, and it also passes for a declaration naming a patch that no
longer exists. The rule is that declared exceptions and actual tracked
modifications must agree in both directions, inside a declared blast
radius, with provenance bound to the captures that used the patch.

These controls build throwaway git repositories in a temp directory and
commit a baseline, so every scenario is produced by real git output rather
than by a hand-written diff string. The real fork is never touched; one
control reads it read-only, which is the positive control for the state the
project is actually in.

What is deliberately NOT asserted: that the fork is clean. It is not, and
making it clean was rejected. What is asserted is that the modification is
declared, in scope, and provenance-bound.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DECLARATION = os.path.join(REPO_ROOT, "fork-exception.json")
REAL_FORK = os.path.normpath(os.path.join(REPO_ROOT, "..", "renderdoc"))
VALIDATION = os.path.normpath(os.path.join(REPO_ROOT, "..", "rdebug-validation"))


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "audit_fork_integrity",
        os.path.join(REPO_ROOT, "scripts", "audit_fork_integrity.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VER = _load_verifier()

BASE_CORE = """#include "hooks/hooks.h"
#include "replay/replay_driver.h"

bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)
{
  return false;
}

int RenderDoc::OtherFunction(int a)
{
  return a;
}
"""

DECLARATION_TEMPLATE = {
    "schema": "rdebug-fork-exception/1",
    "exceptions": [
        {
            "exception_id": "test-exception",
            "enabled": True,
            "category": "capture_acquisition_tooling",
            "purpose": "synthetic fixture for the verifier controls",
            "mechanism": "TEST_TRIGGER",
            "files": {
                "renderdoc/core/core.cpp": {
                    "allowed_symbols": ["RenderDoc::ShouldTriggerCapture"],
                    "allowed_file_scope": ["include_block"],
                }
            },
            "excluded_surfaces": [
                "replay", "driver", "serialise", "mcp", "ai",
                "semantic_graph", "indexing",
            ],
            "provenance": {
                "metadata_globs": ["metadata/N3-05A*.json"],
                "root": ".",
                "mechanism_path": "capture_mechanism.patch",
                "recorded_path": "capture_mechanism.patch_recorded",
            },
            "not_a_replay_change": True,
        }
    ],
}


def _git(repo, *args):
    out = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise AssertionError("git {} failed: {}".format(" ".join(args), out.stderr))
    return out.stdout


def _make_repo(root):
    """A git repo with one committed C++ file mimicking RenderDoc's shape."""
    fork = os.path.join(root, "renderdoc")
    os.makedirs(os.path.join(fork, "renderdoc", "core"))
    with open(os.path.join(fork, "renderdoc", "core", "core.cpp"), "w",
              encoding="utf-8") as fh:
        fh.write(BASE_CORE)
    _git(fork, "init", "-q")
    _git(fork, "config", "user.email", "t@example.invalid")
    _git(fork, "config", "user.name", "t")
    _git(fork, "add", "-A")
    _git(fork, "commit", "-qm", "base")
    return fork


def _write_declaration(root, provenance_extra=None, **overrides):
    doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
    exc = doc["exceptions"][0]
    if provenance_extra:
        exc.setdefault("provenance", {}).update(provenance_extra)
    for key, value in overrides.items():
        exc[key] = value
    path = os.path.join(root, "fork-exception.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


def _write_metadata(root, patch="TEST_TRIGGER", recorded=True, name="N3-05A1.json"):
    mdir = os.path.join(root, "metadata")
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, name), "w", encoding="utf-8") as fh:
        json.dump(
            {"capture_mechanism": {"type": "test", "patch": patch,
                                   "patch_recorded": recorded}},
            fh,
        )
    # The declaration names these two as its provenance evidence, and the
    # verifier now checks that they exist. A fixture that declares evidence it
    # does not write would fail for the right reason and read as a bug.
    for name_ in ("capture_mechanism.patch", "capture_mechanism.patch_recorded"):
        with open(os.path.join(root, name_), "w", encoding="utf-8") as fh:
            fh.write(f"synthetic evidence for {patch}\n")


def _insert_into(fork, rel, anchor, text):
    path = os.path.join(fork, rel)
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    body = body.replace(anchor, anchor + text)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def _real_patch_identity(root, fork, rel="renderdoc/core/core.cpp"):
    """A patch artefact that genuinely describes this fork's modification.

    Ruling: the patch identity is atomic -- artefact, digest and base must all
    be present. A fixture cannot satisfy that by naming three fields; the
    artefact has to be the patch it claims to be. So this exports the actual
    diff rather than stubbing a path, and returns the three fields plus the
    provenance dict ready to splat into a declaration.
    """
    raw = _git(fork, "diff", "--", rel)
    adir = os.path.join(root, "fork-provenance")
    os.makedirs(adir, exist_ok=True)
    apath = os.path.join(adir, "synthetic.patch")
    body = "\n".join(raw.splitlines()).encode("utf-8")
    with open(apath, "wb") as fh:
        fh.write(body)
    digest = hashlib.sha256(body).hexdigest()
    base = _git(fork, "rev-parse", "HEAD").strip()
    return {
        "patch_artifact": "fork-provenance/synthetic.patch",
        "patch_sha256": digest,
        "base_commit": base,
    }


class VerifierBase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fork_audit_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.fork = _make_repo(self.root)
        self.rel = "renderdoc/core/core.cpp"
        _write_metadata(self.root)

    def verify(self, **overrides):
        decl = _write_declaration(self.root, **overrides)
        return VER.verify(self.fork, decl, self.root)

    def _modify(self):
        """The declared, in-scope modification every compliant fixture needs."""
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")

    def assertFails(self, code, **overrides):
        with self.assertRaises(VER.Violation) as ctx:
            self.verify(**overrides)
        self.assertEqual(
            ctx.exception.code, code,
            f"expected {code}, got {ctx.exception.code}: {ctx.exception}",
        )


class TestPositiveControl(VerifierBase):
    """The compliant state: declared, in scope, provenance-bound."""

    def test_declared_in_scope_change_passes(self):
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  // synthetic capture trigger\n  if(1) { return true; }\n")
        summary = self.verify()
        self.assertEqual(summary["tracked_modifications"], 1)
        self.assertEqual(summary["exceptions"], 1)

    def test_include_block_change_passes(self):
        _insert_into(self.fork, self.rel, '#include "hooks/hooks.h"',
                     '\n#include "os/os_specific.h"')
        self.assertEqual(self.verify()["tracked_modifications"], 1)

    def test_real_declaration_is_wellformed(self):
        with open(DECLARATION, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["schema"], "rdebug-fork-exception/1")
        self.assertTrue(doc["exceptions"])
        for exc in doc["exceptions"]:
            self.assertTrue(exc.get("purpose"))
            self.assertTrue(exc.get("files"))
            for spec in exc["files"].values():
                self.assertTrue(spec.get("allowed_symbols") or spec.get("allowed_file_scope"))
            self.assertTrue(exc["excluded_surfaces"])
            # `mechanism` is what binds capture metadata to a declared patch,
            # so it is required exactly where metadata globs are declared. A
            # patch-identity exception has no capture corpus and no mechanism.
            if (exc.get("provenance") or {}).get("metadata_globs"):
                self.assertTrue(exc.get("mechanism"))
        # The category and the surface list are per-exception. Both were
        # asserted as one value across the whole list only while the
        # declaration had a single exception.
        by_id = {e["exception_id"]: e for e in doc["exceptions"]}
        capture = by_id["n3-headless-capture-trigger"]
        self.assertEqual(capture["category"], "capture_acquisition_tooling")
        for surface in ("replay", "driver", "mcp", "ai", "semantic_graph",
                        "indexing"):
            self.assertIn(surface, capture["excluded_surfaces"])
        driver = by_id["glslang-rdcspv-lifecycle"]
        self.assertEqual(driver["category"], "driver_lifecycle_fix")
        # driver is dropped from the driver's own surface list on purpose:
        # this exception lives inside that directory, scoped to one file and
        # one digest. The declaration says so where a reader will see it.
        self.assertNotIn("driver", driver["excluded_surfaces"])
        self.assertIn("excluded_surfaces", driver["excluded_surfaces_note"])

    def test_a_pinned_fork_in_the_declared_state_passes(self):
        """The compliant state, on a fork this control owns.

        This used to run against the sibling checkout and assert that whatever
        state that machine happened to be in was compliant. That is not a
        property of the verifier -- it is a property of one developer's working
        tree, and it fails the moment the developer commits anything. The
        compliant path is now pinned to a repository the control builds, at a
        base it declares, carrying exactly the declared modification.
        """
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  // synthetic capture trigger\n  if(1) { return true; }\n")
        base = _git(self.fork, "rev-parse", "HEAD").strip()
        self.assertEqual(base, _git(self.fork, "rev-parse", "HEAD").strip())
        summary = self.verify(provenance_extra=_real_patch_identity(
            self.root, self.fork, self.rel))
        self.assertEqual(summary["exceptions"], 1)
        self.assertEqual(summary["tracked_modifications"], 1)

    def test_the_real_fork_is_reported_against_the_declared_base(self):
        """The real fork is measured, not assumed compliant.

        Ruling: the sibling checkout is one commit past the base its declaration
        pins, carrying a change to renderdoc/driver/ -- a surface the exception
        excludes. That is reported, not asserted away, and not reset either: the
        commit is real work and discarding it is a separate decision this control
        must not make.

        Two outcomes, both assertions. Either the fork is absent (CI) or it is
        present, and when present it must either match the pinned base or say
        exactly why it does not. What it must never do is report PASS for a fork
        whose HEAD is not the declared one.
        """
        if not os.path.isdir(os.path.join(REAL_FORK, ".git")):
            self.skipTest("fork not present")
        with open(DECLARATION, encoding="utf-8") as fh:
            base = json.load(fh)["exceptions"][0]["provenance"]["base_commit"]
        head = subprocess.run(
            ["git", "-C", REAL_FORK, "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        if head == base:
            self.assertEqual(VER.verify(REAL_FORK, DECLARATION, REPO_ROOT)[
                "exceptions"], 1)
            return
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(REAL_FORK, DECLARATION, REPO_ROOT)
        # Now F2, which is what the module's own header defines F2 to mean. It
        # reported F1 while there was one exception, because "declared but
        # absent" and "modified but undeclared" were then the same event.
        # With two they are not: this fork's driver fix is committed, so it is
        # absent from the working tree, and F1 would name a file it never
        # touched.
        self.assertEqual(ctx.exception.code, "F2")
        self.assertNotIn("PASS", str(ctx.exception))

    def test_cli_exit_code_is_zero_for_a_pinned_fork(self):
        """Exit code zero, on a state the control constructs rather than finds."""
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  // synthetic capture trigger\n  if(1) { return true; }\n")
        # The CLI resolves repo_root from its own location, so both the
        # provenance root and the patch artefact must be absolute to land
        # beside this fixture rather than in the real repository.
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        ident["patch_artifact"] = os.path.join(self.root, ident["patch_artifact"])
        decl = _write_declaration(self.root,
                                  provenance_extra=dict(ident, root=self.root))
        out = subprocess.run(
            [os.sys.executable, os.path.join(REPO_ROOT, "scripts",
                                             "audit_fork_integrity.py"),
             "--fork", self.fork, "--declaration", decl],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("PASS", out.stdout)


class TestF1UndeclaredModification(VerifierBase):
    """F1: a tracked modification no declaration covers."""

    def _add_new_tracked_file(self, rel, body):
        path = os.path.join(self.fork, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        _git(self.fork, "add", "-A")

    def test_extra_tracked_file_not_declared_fails(self):
        self._add_new_tracked_file(
            "renderdoc/core/extra.cpp", "int unrelated() { return 0; }\n"
        )
        self.assertFails("F1")

    def test_untracked_file_is_not_a_tracked_modification(self):
        """Section 2.1 speaks of tracked modifications, so this must pass.

        An untracked file is not a violation, and treating build output as
        one would make the audit unusable. This control pins that boundary
        so it stays a decision rather than becoming an accident.
        """
        with open(os.path.join(self.fork, "renderdoc", "core", "scratch.cpp"), "w",
                  encoding="utf-8") as fh:
            fh.write("int scratch() { return 0; }\n")
        doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
        doc["exceptions"][0]["enabled"] = False
        path = os.path.join(self.root, "fork-exception.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        summary = VER.verify(self.fork, path, self.root)
        self.assertEqual(summary["tracked_modifications"], 0)

    def test_undeclared_file_while_allowed_file_also_modified_fails(self):
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        self._add_new_tracked_file(
            "renderdoc/core/extra.cpp", "int unrelated() { return 0; }\n"
        )
        self.assertFails("F1")

    def test_modification_present_but_no_declaration_fails(self):
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
        doc["exceptions"][0]["enabled"] = False
        path = os.path.join(self.root, "fork-exception.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, path, self.root)
        self.assertEqual(ctx.exception.code, "F1")


class TestF2DeclaredButAbsent(VerifierBase):
    """F2: the declaration names a patch that is not in the tree."""

    def test_clean_tree_with_enabled_declaration_fails(self):
        self.assertFails("F2")

    def test_disabled_declaration_on_clean_tree_passes(self):
        doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
        doc["exceptions"][0]["enabled"] = False
        path = os.path.join(self.root, "fork-exception.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        summary = VER.verify(self.fork, path, self.root)
        self.assertEqual(summary["tracked_modifications"], 0)

    def _two_exceptions(self):
        doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
        second = json.loads(json.dumps(doc["exceptions"][0]))
        second["exception_id"] = "second-exception"
        second["files"] = {"renderdoc/driver/spv.cpp": {
            "allowed_symbols": ["Spirv::Thing"], "allowed_file_scope": []}}
        doc["exceptions"].append(second)
        path = os.path.join(self.root, "two.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path, second

    def test_a_declared_file_with_no_modification_is_f2(self):
        self._modify()
        path, _ = self._two_exceptions()
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, path, self.root)
        self.assertEqual(ctx.exception.code, "F2")
        self.assertIn("renderdoc/driver/spv.cpp", str(ctx.exception))

    def test_an_undeclared_modification_is_still_f1(self):
        self._modify()
        path, _ = self._two_exceptions()
        extra = os.path.join(self.fork, "renderdoc", "core", "other.cpp")
        with open(extra, "w", encoding="utf-8") as fh:
            fh.write("int stray;\n")
        _git(self.fork, "add", "-A")
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, path, self.root)
        self.assertEqual(ctx.exception.code, "F1")
        self.assertIn("renderdoc/core/other.cpp", str(ctx.exception))

    def test_both_declarations_matching_passes(self):
        self._modify()
        path, second = self._two_exceptions()
        target = os.path.join(self.fork, *second["files"].keys())
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("bool Spirv::Thing()\n{\n  return false;\n}\n")
        _git(self.fork, "add", "-A")
        _insert_into(self.fork, *second["files"],
                     "bool Spirv::Thing()\n{", "\n  if(1) { return true; }\n")
        summary = VER.verify(self.fork, path, self.root)
        self.assertEqual(summary["exceptions"], 2)
        self.assertEqual(summary["tracked_modifications"], 2)


class TestF3ProvenanceBinding(VerifierBase):
    """F3: metadata must record the patch and agree with reality."""

    def test_missing_metadata_fails(self):
        shutil.rmtree(os.path.join(self.root, "metadata"))
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        self.assertFails("F3")

    def test_metadata_records_a_different_patch_fails(self):
        _write_metadata(self.root, patch="SOMETHING_ELSE")
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        self.assertFails("F3")

    def test_metadata_not_marked_recorded_fails(self):
        _write_metadata(self.root, recorded=False)
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        self.assertFails("F3")

    def test_metadata_covering_only_unrelated_capture_fails(self):
        """The over-broad glob that the real declaration initially had.

        N3-02 and N3-03 were captured without the patch, so a glob matching
        every metadata file drags in records that carry no mechanism. The
        failure is the point: a broad glob is not a safe default.
        """
        shutil.rmtree(os.path.join(self.root, "metadata"))
        _write_metadata(self.root, patch=None, recorded=None, name="N3-02.json")
        _write_metadata(self.root, patch=None, recorded=None, name="N3-03.json")
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        self.assertFails("F3", provenance={
            "metadata_globs": ["metadata/*.json"], "root": ".",
            "mechanism_path": "capture_mechanism.patch",
            "recorded_path": "capture_mechanism.patch_recorded",
        })

    def test_a_declaration_with_no_provenance_fails(self):
        """No provenance at all is F3, and says so.

        The message matters as much as the code. The old dispatch reported
        `no capture metadata matched []`, which reads as "the corpus metadata
        is not here right now" -- a transient, environmental problem. It is
        not: the declaration simply never stated how it is to be verified.
        """
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        with self.assertRaises(VER.Violation) as ctx:
            self.verify(provenance={})
        self.assertEqual(ctx.exception.code, "F3")
        self.assertIn("declares no provenance", str(ctx.exception))
        self.assertNotIn("no capture metadata matched", str(ctx.exception))

    def test_capture_metadata_is_still_required_alongside_a_patch_identity(self):
        """Declaring a patch identity does not discharge the capture metadata.

        Guard against the dispatch becoming an either/or. This declaration
        carries a complete patch triple *and* capture globs; the metadata is
        removed, so the capture check must still reject it. A dispatch where
        either group could satisfy the other would pass here.
        """
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        shutil.rmtree(os.path.join(self.root, "metadata"))
        with self.assertRaises(VER.Violation) as ctx:
            # provenance_extra merges into the template, so the globs stay.
            self.verify(provenance_extra=ident)
        self.assertEqual(ctx.exception.code, "F3")
        self.assertIn("no capture metadata matched", str(ctx.exception))

    def test_named_evidence_that_is_absent_is_rejected(self):
        """A declaration may not name evidence it cannot produce.

        The contract's rule is "patch_recorded agrees with patch presence".
        Only the recorded side was ever read: mechanism_path and recorded_path
        were fetched and discarded, so both could be absent and the exception
        still verified. On the real declaration they are absent today.
        """
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        for absent in ("capture_mechanism.patch",
                       "capture_mechanism.patch_recorded"):
            os.remove(os.path.join(self.root, absent))
            with self.assertRaises(VER.Violation) as ctx:
                self.verify()
            self.assertEqual(ctx.exception.code, "F3")
            self.assertIn("does not exist", str(ctx.exception))
            _write_metadata(self.root)   # restore for the next iteration

    def test_named_evidence_is_checked_even_with_a_valid_patch_identity(self):
        """Patch provenance does not excuse missing capture evidence."""
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        os.remove(os.path.join(self.root, "capture_mechanism.patch"))
        with self.assertRaises(VER.Violation) as ctx:
            self.verify(provenance_extra=ident)
        self.assertEqual(ctx.exception.code, "F3")
        self.assertIn("does not exist", str(ctx.exception))


    """F2: a declaration names a modification the working tree does not have.

    The mirror image of F1, and only distinguishable from it when the
    declaration holds more than one exception. With one, "declared but absent"
    and "modified but undeclared" are the same event and either code is
    arguable. With two they are different events and each deserves its own.
    """

class TestF4BlastRadius(VerifierBase):
    """F4: the change lands outside the declared file or symbol scope."""

    def test_change_in_undeclared_symbol_fails(self):
        _insert_into(self.fork, self.rel,
                     "int RenderDoc::OtherFunction(int a)\n{",
                     "\n  if(a > 0) { return a + 1; }\n")
        self.assertFails("F4")

    def test_comment_alone_does_not_grant_compliance(self):
        """A well-meaning comment in an undeclared function is still F4.

        Condition 3 of the Contract: scope is decided by where the change is,
        not by whether someone explained it.
        """
        _insert_into(self.fork, self.rel,
                     "int RenderDoc::OtherFunction(int a)\n{",
                     "\n  // this is only a capture trigger, honestly\n"
                     "  if(a > 0) { return a + 1; }\n")
        self.assertFails("F4")

    def test_change_in_excluded_surface_fails(self):
        rel = "renderdoc/replay/replay_driver.cpp"
        os.makedirs(os.path.join(self.fork, "renderdoc", "replay"))
        with open(os.path.join(self.fork, rel), "w", encoding="utf-8") as fh:
            fh.write("void ReplayDriver::DoThing()\n{\n}\n")
        _git(self.fork, "add", "-A")
        _git(self.fork, "commit", "-qm", "add driver")
        _insert_into(self.fork, rel, "void ReplayDriver::DoThing()\n{",
                     "\n  if(1) { return; }\n")
        self.assertFails("F1")

    def test_declaration_without_scope_lists_is_rejected(self):
        doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
        doc["exceptions"][0]["files"] = {
            "renderdoc/core/core.cpp": {"allowed_symbols": [], "allowed_file_scope": []}
        }
        path = os.path.join(self.root, "fork-exception.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, path, self.root)
        self.assertEqual(ctx.exception.code, "F4")


class TestBaseCommitIsEnforced(unittest.TestCase):
    """A committed change is invisible to a working-tree comparison.

    tracked_modifications runs `git diff --name-only HEAD`. That is the check
    this module's docstring disclaims -- the one that "would pass for a fork
    that silently diverges from upstream". These controls pin the replacement:
    the fork is compared against a declared base commit, so a commit made on
    top of the base cannot hide.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fork_base_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.fork = _make_repo(self.root)
        self.rel = "renderdoc/core/core.cpp"
        _write_metadata(self.root)
        self.base = _git(self.fork, "rev-parse", "HEAD").strip()

    def _declared(self, **provenance):
        doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
        doc["exceptions"][0]["provenance"].update(provenance)
        path = os.path.join(self.root, "fork-exception.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path


    def _modify(self):
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")

    def test_a_commit_past_the_base_is_rejected(self):
        """The real fork's shape: one unpushed commit past the pinned base."""
        self._modify()
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        self.assertEqual(ident["base_commit"], self.base)
        _git(self.fork, "add", "-A")
        _git(self.fork, "commit", "-qm", "past the base")
        self._modify()
        decl = self._declared(**ident)
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, decl, self.root)
        self.assertEqual(ctx.exception.code, "F3")
        # The pin has to be what fired. A partial identity also raises F3, and
        # that would be this control passing for the wrong reason.
        self.assertIn(self.base[:12], str(ctx.exception))
        self.assertNotIn("partial", str(ctx.exception))

    def test_a_committed_change_to_an_excluded_surface_is_rejected(self):
        """The case that passed before: driver/ committed, patch uncommitted.

        The rejection is F3 rather than F1, and that is the whole point. A
        committed change moves HEAD off the base, so pinning HEAD is what
        catches it; a separate diff-against-base pass would be unreachable,
        because any divergence strong enough to need it has already moved HEAD.
        """
        self._modify()
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        other = "renderdoc/driver/shaders/spirv/glslang_compile.cpp"
        os.makedirs(os.path.dirname(os.path.join(self.fork, other)), exist_ok=True)
        with open(os.path.join(self.fork, other), "w", encoding="utf-8") as fh:
            fh.write("int x;\n")
        _git(self.fork, "add", "--", other)
        _git(self.fork, "commit", "-qm", "undeclared driver change")
        decl = self._declared(**ident)
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, decl, self.root)
        self.assertEqual(ctx.exception.code, "F3")
        self.assertIn(self.base[:12], str(ctx.exception))
        self.assertNotIn("partial", str(ctx.exception))

    def test_a_committed_driver_change_is_invisible_without_a_pinned_base(self):
        """Why the pin exists: undeclared and excluded, yet accepted.

        Without base_commit the same fork passes, which is the defect the
        working-tree comparison cannot see.
        """
        self._modify()
        other = "renderdoc/driver/shaders/spirv/glslang_compile.cpp"
        os.makedirs(os.path.dirname(os.path.join(self.fork, other)), exist_ok=True)
        with open(os.path.join(self.fork, other), "w", encoding="utf-8") as fh:
            fh.write("int x;\n")
        _git(self.fork, "add", "--", other)
        _git(self.fork, "commit", "-qm", "undeclared driver change")
        summary = VER.verify(self.fork, self._declared(), self.root)
        self.assertEqual(summary["tracked_modifications"], 1)

    def test_a_fork_at_the_base_with_only_the_declared_patch_passes(self):
        self._modify()
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        self.assertEqual(ident["base_commit"], self.base)
        summary = VER.verify(self.fork, self._declared(**ident), self.root)
        self.assertEqual(summary["tracked_modifications"], 1)

    def test_a_declaration_that_pins_no_base_is_unaffected(self):
        """Opt-in: a declaration without base_commit keeps the old behaviour."""
        self._modify()
        summary = VER.verify(self.fork, self._declared(), self.root)
        self.assertEqual(summary["tracked_modifications"], 1)

    def test_a_missing_patch_artefact_is_rejected(self):
        """A complete identity naming an artefact that is not there.

        Declared all three fields, so the rejection is the artefact-existence
        check and not a partial-identity complaint.
        """
        self._modify()
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        absent = dict(ident, patch_artifact="fork-provenance/absent.patch")
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, self._declared(**absent), self.root)
        self.assertEqual(ctx.exception.code, "F3")
        self.assertIn("does not exist", str(ctx.exception))
        self.assertNotIn("partial", str(ctx.exception))

    def test_a_tampered_patch_artefact_is_rejected(self):
        """A complete identity whose artefact does not hash to its digest.

        The intact identity verifies; the same identity with one digest field
        altered is rejected by the digest check. All three fields are declared
        in both calls, so a partial-identity complaint cannot be what fires.
        """
        self._modify()
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        self.assertEqual(ident["base_commit"], self.base)
        VER.verify(self.fork, self._declared(**ident), self.root)
        tampered = dict(ident, patch_sha256="0" * 64)
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, self._declared(**tampered), self.root)
        self.assertEqual(ctx.exception.code, "F3")
        self.assertIn(ident["patch_sha256"], str(ctx.exception))
        self.assertNotIn("partial", str(ctx.exception))

    def test_a_partial_patch_identity_is_rejected(self):
        """Two of three fields is not an identity nobody has to verify."""
        self._modify()
        ident = _real_patch_identity(self.root, self.fork, self.rel)
        del ident["base_commit"]
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, self._declared(**ident), self.root)
        self.assertEqual(ctx.exception.code, "F3")
        self.assertIn("base_commit", str(ctx.exception))

    def test_the_real_declaration_pins_a_base_and_an_artefact(self):
        """A′: the shipped declaration opts in, so the check cannot be lost."""
        with open(DECLARATION, encoding="utf-8") as fh:
            doc = json.load(fh)
        prov = doc["exceptions"][0]["provenance"]
        self.assertTrue(prov.get("base_commit"))
        self.assertTrue(prov.get("patch_artifact"))
        self.assertTrue(prov.get("patch_sha256"))
        artifact = os.path.join(REPO_ROOT, prov["patch_artifact"])
        self.assertTrue(os.path.isfile(artifact))
        import hashlib
        with open(artifact, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(digest, prov["patch_sha256"],
                         "the pinned artefact digest must match the file on disk")
        self.assertEqual(prov["base_commit"],
                         "b7f1554feb0d7d7120f2b9280364b98972ec37d3")


class TestDeclarationSchema(VerifierBase):
    def _raw_declaration(self, mutate):
        doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
        mutate(doc)
        path = os.path.join(self.root, "fork-exception.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def test_wrong_schema_fails(self):
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        path = self._raw_declaration(lambda d: d.__setitem__("schema", "wrong/9"))
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, path, self.root)
        self.assertEqual(ctx.exception.code, "SCHEMA")

    def test_no_enabled_exception_with_modifications_fails(self):
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        path = self._raw_declaration(lambda d: d.__setitem__("exceptions", []))
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(self.fork, path, self.root)
        self.assertEqual(ctx.exception.code, "F1")

    def test_generic_purpose_is_still_accepted_but_scope_must_exist(self):
        """Condition 2 requires a declared purpose; a vague one is not a bypass.

        The verifier does not judge prose, so this control pins that the
        mechanical half of the Contract is what enforces scope, and that a
        vague purpose does not weaken it.
        """
        _insert_into(self.fork, self.rel,
                     "bool RenderDoc::ShouldTriggerCapture(uint32_t frameNumber)\n{",
                     "\n  if(1) { return true; }\n")
        self.verify(purpose="tooling change")
        _insert_into(self.fork, self.rel, "int RenderDoc::OtherFunction(int a)\n{",
                     "\n  if(a) { return 2; }\n")
        self.assertFails("F4", purpose="tooling change")


if __name__ == "__main__":
    unittest.main()
