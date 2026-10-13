"""Identity and reproducibility controls for the glslang lifecycle artefact.

The sibling RenderDoc checkout carries an unpushed commit, f4b3d4fa, whose
root cause is attributed at binary level in docs/PDB-ATTRIBUTION-RESULT.md
sections 12-15: `rdcspv::Shutdown()` dereferenced a null container because
`glslang_inited` was never reset. That evidence is why the change is worth
preserving and reviewing.

This control preserves it as an auditable artefact. It deliberately does not
declare it: fork-exception.json still excludes renderdoc/driver/, the artefact
is not referenced by any exception, and nothing here makes the fork compliant.
A candidate governance asset and an approved exception are different things,
and only the second one may widen the gate's scope.

What these controls pin is that the artefact cannot drift silently. Missing,
altered, misbased, or carrying unrelated changes all fail.
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
FORK = os.path.join(os.path.dirname(REPO_ROOT), "renderdoc")

ARTIFACT = os.path.join(REPO_ROOT, "fork-provenance",
                        "glslang-rdcspv-lifecycle-init-shutdown.patch")

#: Derived from `git -C <fork> diff <base> <commit> -- <target>`, lines joined
#: with LF, UTF-8 without BOM and without a trailing newline -- the same
#: canonicalisation as the capture-trigger artefact, so the two digests are
#: comparable rather than two private conventions.
BASE_COMMIT = "b7f1554feb0d7d7120f2b9280364b98972ec37d3"
SOURCE_COMMIT = "f4b3d4fac3412e35f472036e1a5d344c3a7e60a1"
TARGET = "renderdoc/driver/shaders/spirv/glslang_compile.cpp"
DELTA_SHA256 = (
    "2a87e8bb01ce6698e2486b03ac4c2eb16fdeb874aef305b68ee9a14ad70f7d89"
)
EXPECTED_INSERTIONS = 30
EXPECTED_DELETIONS = 5


def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _stat():
    """(insertions, deletions) as git counts them, excluding diff headers."""
    lines = pathlib.Path(ARTIFACT).read_text(encoding="utf-8").splitlines()
    ins = sum(1 for line in lines
              if line.startswith("+") and not line.startswith("+++"))
    dele = sum(1 for line in lines
               if line.startswith("-") and not line.startswith("---"))
    return ins, dele


class TestGlslangArtefactIdentity(unittest.TestCase):
    """The artefact exists, is the recorded one, and is only the fix."""

    def test_the_artefact_is_present_and_tracked(self):
        self.assertTrue(os.path.isfile(ARTIFACT),
                        "the glslang lifecycle artefact must exist; without "
                        "it the only copy of this delta is an unpushed commit")
        rel = os.path.relpath(ARTIFACT, REPO_ROOT).replace(os.sep, "/")
        self.assertEqual(rel,
                         "fork-provenance/glslang-rdcspv-lifecycle-init-shutdown.patch",
                         "the artefact belongs in fork-provenance/ under a "
                         "stable name, so it can be cited by path")

    def test_the_digest_matches_the_record(self):
        self.assertEqual(_digest(ARTIFACT), DELTA_SHA256,
                         "the stored artefact no longer hashes to the value "
                         "recorded for it, so it cannot be cited as evidence")

    def test_the_scope_is_exactly_the_declared_change(self):
        insertions, deletions = _stat()
        self.assertEqual(insertions, EXPECTED_INSERTIONS)
        self.assertEqual(deletions, EXPECTED_DELETIONS)

    def test_it_touches_one_declared_path(self):
        body = pathlib.Path(ARTIFACT).read_text(encoding="utf-8")
        paths = {line.split(" b/", 1)[1].strip()
                 for line in body.splitlines()
                 if line.startswith("+++ b/")}
        self.assertEqual(paths, {TARGET},
                         "the artefact must carry the lifecycle fix and "
                         "nothing else")

    def test_it_is_the_lifecycle_fix_and_not_something_adjacent(self):
        body = pathlib.Path(ARTIFACT).read_text(encoding="utf-8")
        for required in ("glslang_inited = false",
                         "glslang::InitializeProcess()",
                         "glslang_inited = true"):
            self.assertIn(required, body,
                          f"the artefact does not carry {required!r}, so it is "
                          "not the recorded lifecycle fix")
        for unrelated in ("ShouldTriggerCapture", "RDOC_TRIGGER_FRAMES"):
            self.assertNotIn(unrelated, body,
                             f"the artefact carries {unrelated!r}, which belongs "
                             "to a different declared change")

    def test_the_canonical_form_is_what_the_digest_covers(self):
        raw = pathlib.Path(ARTIFACT).read_bytes()
        self.assertFalse(raw.endswith(b"\n"),
                         "the artefact is canonicalised without a trailing "
                         "newline; a re-export that adds one changes the "
                         "digest even though the change is identical")
        self.assertNotIn(b"\r\n", raw, "line endings must be LF")


class TestGlslangArtefactReproduces(unittest.TestCase):
    """From the pinned base, the artefact rebuilds the recorded state.

    Skipped when the sibling checkout is absent -- CI has no RenderDoc fork --
    so these are local evidence controls, not gate controls. What they establish
    locally is that the artefact is not a description of a change but the change.
    """

    def setUp(self):
        if not os.path.isdir(os.path.join(FORK, ".git")):
            self.skipTest("fork not present")
        self.tmp = tempfile.mkdtemp(prefix="glslang_repro_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _clean_clone_at_base(self):
        clone = os.path.join(self.tmp, "fork")
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", FORK, clone],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", clone, "checkout", "-q", BASE_COMMIT],
                       check=True, capture_output=True)
        return clone

    def _apply(self, clone, source=None):
        """Apply an artefact. git needs a terminated patch; the artefact is
        canonicalised without one, exactly as the capture-trigger one is."""
        target = os.path.join(self.tmp, "apply.patch")
        with open(source or ARTIFACT, "rb") as fh:
            body = fh.read()
        with open(target, "wb") as fh:
            fh.write(body + b"\n")
        return subprocess.run(["git", "-C", clone, "apply", "--check", target],
                              capture_output=True, text=True)

    def test_it_applies_cleanly_to_the_pinned_base(self):
        clone = self._clean_clone_at_base()
        proc = self._apply(clone)
        self.assertEqual(proc.returncode, 0,
                         "the artefact does not apply to its pinned base:\n"
                         + proc.stdout + proc.stderr)

    def test_applying_it_rebuilds_the_recorded_scope(self):
        clone = self._clean_clone_at_base()
        self.assertEqual(self._apply(clone).returncode, 0)
        subprocess.run(["git", "-C", clone, "apply", os.path.join(self.tmp,
                                                                 "apply.patch")],
                       check=True, capture_output=True)
        out = subprocess.run(["git", "-C", clone, "diff", "--stat", BASE_COMMIT],
                             capture_output=True, text=True).stdout
        self.assertIn(f"1 file changed, {EXPECTED_INSERTIONS} insertions(+), "
                      f"{EXPECTED_DELETIONS} deletions(-)", out)

    def test_the_rebuilt_file_matches_the_sibling_checkout(self):
        clone = self._clean_clone_at_base()
        self.assertEqual(self._apply(clone).returncode, 0)
        subprocess.run(["git", "-C", clone, "apply", os.path.join(self.tmp,
                                                                 "apply.patch")],
                       check=True, capture_output=True)
        rebuilt = os.path.join(clone, *TARGET.split("/"))
        original = os.path.join(FORK, *TARGET.split("/"))
        self.assertEqual(_digest(rebuilt), _digest(original),
                         "applying the artefact did not reproduce the file the "
                         "sibling checkout actually has")

    def test_a_tampered_artefact_does_not_reproduce(self):
        """Identity is what makes the artefact evidence, so prove it binds."""
        clone = self._clean_clone_at_base()
        tampered = os.path.join(self.tmp, "t.patch")
        with open(ARTIFACT, encoding="utf-8") as fh:
            body = fh.read()
        with open(tampered, "w", encoding="utf-8") as fh:
            fh.write(body + "+\n// tampered\n")
        self.assertNotEqual(_digest(tampered), DELTA_SHA256)
        proc = self._apply(clone, source=tampered)
        self.assertNotEqual(proc.returncode, 0,
                            "a tampered artefact should not apply cleanly")


class TestGlslangArtefactIsDeclared(unittest.TestCase):
    """The artefact is declared, and declared narrowly.

    Ruling history: the artefact was first preserved as a candidate asset with
    nothing declared, and these controls asserted exactly that -- no exception
    referenced it, driver stayed an excluded surface, the capture-trigger
    exception was the only one. The exception has since been adjudicated and
    written, so those assertions are now inverted. They are kept rather than
    deleted because each one still names a way this exception could be widened
    by accident.
    """

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "fork-exception.json"),
                  encoding="utf-8") as fh:
            self.doc = json.load(fh)
        self.exc = next(e for e in self.doc["exceptions"]
                        if e["exception_id"] == "glslang-rdcspv-lifecycle")

    def test_it_is_declared_and_enabled(self):
        self.assertIs(self.exc["enabled"], True)
        self.assertIn("fork-provenance/"
                      "glslang-rdcspv-lifecycle-init-shutdown.patch",
                      json.dumps(self.doc))

    def test_the_declared_identity_matches_the_artefact_on_disk(self):
        prov = self.exc["provenance"]
        self.assertEqual(prov["patch_artifact"],
                         "fork-provenance/"
                         "glslang-rdcspv-lifecycle-init-shutdown.patch")
        self.assertEqual(prov["patch_sha256"], DELTA_SHA256)
        self.assertEqual(prov["base_commit"], BASE_COMMIT)
        self.assertEqual(_digest(ARTIFACT), prov["patch_sha256"])
        self.assertEqual(prov["patch_sha256"], DELTA_SHA256)

    def test_it_is_scoped_to_one_file_and_nothing_under_driver_otherwise(self):
        files = self.exc["files"]
        self.assertEqual(list(files), [TARGET],
                         "the exception must name exactly one file")
        self.assertFalse(files[TARGET]["allowed_file_scope"],
                         "no file-scope grant; every hunk is symbol-scoped")
        self.assertEqual(len(files[TARGET]["allowed_symbols"]), 4)

    def test_it_borrows_no_capture_provenance(self):
        prov = self.exc["provenance"]
        self.assertNotIn("metadata_globs", prov,
                         "a driver lifecycle fix must not claim the capture "
                         "corpus; that identity belongs to the other exception")
        self.assertNotIn("root", prov)

    def test_the_capture_trigger_exception_is_untouched(self):
        other = next(e for e in self.doc["exceptions"]
                     if e["exception_id"] == "n3-headless-capture-trigger")
        self.assertEqual(other["mechanism"], "RDOC_TRIGGER_FRAMES")
        self.assertEqual(list(other["files"]), ["renderdoc/core/core.cpp"])
        self.assertIn("n3-corpus/metadata/N3-05A*.json",
                      other["provenance"]["metadata_globs"])
        self.assertIn("driver", other["excluded_surfaces"],
                      "driver remains excluded for the capture exception")

    def test_the_source_commit_is_recorded_but_is_not_the_base(self):
        src = self.exc["source_commit"]
        self.assertEqual(src["sha"], SOURCE_COMMIT)
        self.assertNotEqual(src["sha"], self.exc["provenance"]["base_commit"],
                            "the audit baseline stays the public base; the "
                            "source commit is a provenance record only")
        self.assertEqual(self.exc["provenance"]["base_commit"], BASE_COMMIT)
