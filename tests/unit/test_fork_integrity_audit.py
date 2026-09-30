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


def _write_declaration(root, **overrides):
    doc = json.loads(json.dumps(DECLARATION_TEMPLATE))
    exc = doc["exceptions"][0]
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


def _insert_into(fork, rel, anchor, text):
    path = os.path.join(fork, rel)
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    body = body.replace(anchor, anchor + text)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


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
            self.assertEqual(exc["category"], "capture_acquisition_tooling")
            self.assertTrue(exc.get("purpose"))
            self.assertTrue(exc.get("mechanism"))
            self.assertTrue(exc.get("files"))
            for spec in exc["files"].values():
                self.assertTrue(spec.get("allowed_symbols") or spec.get("allowed_file_scope"))
            for surface in ("replay", "driver", "mcp", "ai", "semantic_graph", "indexing"):
                self.assertIn(surface, exc["excluded_surfaces"])

    def test_real_fork_state_passes(self):
        """Positive control on the state the project is actually in.

        Read-only: the verifier only runs git status and git diff.
        """
        if not os.path.isdir(os.path.join(REAL_FORK, ".git")):
            self.skipTest("fork not present")
        summary = VER.verify(REAL_FORK, DECLARATION, REPO_ROOT)
        self.assertEqual(summary["exceptions"], 1)
        self.assertGreaterEqual(summary["tracked_modifications"], 1)

    def test_cli_exit_code_is_zero_for_the_real_state(self):
        if not os.path.isdir(os.path.join(REAL_FORK, ".git")):
            self.skipTest("fork not present")
        out = subprocess.run(
            [os.sys.executable, os.path.join(REPO_ROOT, "scripts", "audit_fork_integrity.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
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
