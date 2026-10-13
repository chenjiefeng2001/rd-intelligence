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
import sys
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


FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "fork-baseline",
                       "glslang_compile.cpp")

#: The upstream file at the declared base, exported with
#: `git show b7f1554fe...:renderdoc/driver/shaders/spirv/glslang_compile.cpp`.
#: Vendored so the blast-radius check is verified on CI, which has no fork.
#: RenderDoc is BSD-3-Clause; this is a verbatim upstream excerpt.
FIXTURE_SHA256 = (
    "c5f883b874010eda6fc762a3c3f1ba3e2e3b9018ee63d56644898382da81ef3d"
)

DECLARATION = os.path.join(REPO_ROOT, "fork-exception.json")


def _load_verifier():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fork_audit_for_glslang",
        os.path.join(REPO_ROOT, "scripts", "audit_fork_integrity.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VER = _load_verifier()


def _git(repo, *args):
    out = subprocess.run(["git", "-C", repo] + list(args),
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if out.returncode != 0:
        raise AssertionError("git {} failed: {}".format(" ".join(args),
                                                       out.stderr))
    return out.stdout


def _scratch_repo(root, apply_artefact=True):
    """A repository holding the upstream base file, with the artefact applied.

    Built from the vendored fixture rather than a clone, so it works on CI.
    """
    fork = os.path.join(root, "ws")
    dest = os.path.join(fork, *TARGET.split("/"))
    os.makedirs(os.path.dirname(dest))
    shutil.copyfile(FIXTURE, dest)
    _git(fork, "init", "-q")
    _git(fork, "config", "user.email", "t@example.invalid")
    _git(fork, "config", "user.name", "t")
    _git(fork, "add", "-A")
    _git(fork, "commit", "-qm", "upstream base")
    if apply_artefact:
        body = open(ARTIFACT, "rb").read()
        patched = os.path.join(root, "apply.patch")
        with open(patched, "wb") as fh:
            fh.write(body + b"\n")
        subprocess.run(["git", "-C", fork, "apply", patched], check=True,
                       capture_output=True)
    return fork


class TestTheAuditStatesItsOwnVerdict(unittest.TestCase):
    """A missing external evidence root is not a regression.

    release_gate maps any non-zero gate exit to REGRESSION. That is right for
    a gate that ran and found the work wrong, and wrong here: the commonest
    failure on a clean machine is that the external capture evidence this audit
    binds to is not present. CAPTURE-CORPUS-CONTRACT section 5 forbids
    translating an absence into REGRESSION and DESIGN_SPEC 4.2.2 lists it as an
    explicitly forbidden mapping, so the audit writes its own four-state verdict
    and the gate reads that instead of the exit code.
    """

    def _run(self, fork, declaration, tag):
        out = os.path.join(self.root, tag + ".json")
        proc = subprocess.run(
            [sys.executable,
             os.path.join(REPO_ROOT, "scripts", "audit_fork_integrity.py"),
             "--fork", fork, "--declaration", declaration,
             "--verdict-json", out],
            capture_output=True, text=True)
        with open(out, encoding="utf-8") as fh:
            return proc.returncode, json.load(fh)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fork_verdict_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _declaration_with_root(self, root):
        doc = json.loads(json.dumps(
            json.load(open(DECLARATION, encoding="utf-8"))))
        doc["exceptions"][0]["provenance"]["root"] = root
        path = os.path.join(self.root, "decl.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def test_absent_external_evidence_root_is_infrastructure(self):
        """The discrimination, at the level it is actually made.

        Tested here rather than end to end because reaching the F3 requires a
        fork carrying both declared modifications, and the scratch repository
        holds one file: the capture exception is absent first and F2 fires
        before provenance is ever reached.
        """
        missing = os.path.join(self.root, "no-such-validation-tree")
        decl = self._declaration_with_root(missing)
        v = VER.Violation(
            "F3",
            f"declaration names mechanism_path='capture_mechanism.patch' as "
            f"provenance evidence, but 'capture_mechanism.patch' does not "
            f"exist under {missing}",
            kind=VER.ABSENCE_EXTERNAL)
        outcome, why = VER._outcome_for(v, decl)
        self.assertEqual(outcome, "INFRASTRUCTURE_FAILURE")
        self.assertIn("absent on this machine", why)

    def test_evidence_present_but_disagreeing_is_a_regression(self):
        decl = self._declaration_with_root(self.root)
        v = VER.Violation("F3", "N3-05A1.json records patch 'OTHER'")
        outcome, _why = VER._outcome_for(v, decl)
        self.assertEqual(outcome, "REGRESSION")

    def test_a_wrong_artefact_digest_is_a_regression(self):
        """The artefact is in this repository, so a mismatch is a real fact."""
        decl = self._declaration_with_root(self.root)
        v = VER.Violation("F3", "patch artefact hashes to deadbeef")
        outcome, _why = VER._outcome_for(v, decl)
        self.assertEqual(outcome, "REGRESSION")

    def test_a_violation_that_is_not_provenance_is_always_a_regression(self):
        for code in ("F1", "F2", "F4"):
            decl = self._declaration_with_root(os.path.join(self.root, "gone"))
            outcome, _why = VER._outcome_for(VER.Violation(code, "x"), decl)
            self.assertEqual(outcome, "REGRESSION", code)

    def test_the_verdict_file_carries_the_reason_and_the_violation(self):
        fork = _scratch_repo(self.root)
        decl = self._declaration_with_root(os.path.join(self.root, "gone"))
        _code, verdict = self._run(fork, decl, "reason")
        self.assertEqual(verdict["outcome"], "REGRESSION")
        self.assertTrue(verdict["detail"])
        self.assertIn("violation_code", verdict["evidence"])
        self.assertIn("abort", verdict["evidence"])

    def test_the_capture_exception_names_no_evidence_that_cannot_exist(self):
        """A named evidence path must be a file that is actually there.

        mechanism_path and recorded_path were removed from the capture
        exception. They named capture_mechanism.patch and
        capture_mechanism.patch_recorded under rdebug-validation, neither of
        which exists anywhere, and patch_verification.json in that same tree
        records verdict STOP with patch_verified_in_binary false -- no .rdc
        from that run may be admitted.

        The audit would have reported INFRASTRUCTURE_FAILURE forever, and the
        only way to turn that green was to write the files, which is
        fabricating the record of a capture its own evidence says did not
        happen. A check that can only fail is not a check.
        """
        with open(DECLARATION, encoding="utf-8") as fh:
            doc = json.load(fh)
        capture = next(e for e in doc["exceptions"]
                       if e["exception_id"] == "n3-headless-capture-trigger")
        prov = capture["provenance"]
        for key in ("mechanism_path", "recorded_path"):
            self.assertNotIn(key, prov,
                             f"{key} names evidence that does not exist; put "
                             "it back only if the file is real, and say where "
                             "it came from")
        root = os.path.normpath(os.path.join(
            REPO_ROOT, prov.get("root", ".")))
        for key, rel in prov.items():
            if key.endswith("_path"):
                path = rel if os.path.isabs(rel) else os.path.join(root, rel)
                self.assertTrue(os.path.isfile(path),
                                f"named evidence {rel} does not exist at {path}")

    def test_the_provenance_that_can_be_verified_is_still_declared(self):
        """Removing two fields must not quietly thin the contract."""
        with open(DECLARATION, encoding="utf-8") as fh:
            doc = json.load(fh)
        prov = next(e for e in doc["exceptions"]
                    if e["exception_id"] == "n3-headless-capture-trigger"
                    )["provenance"]
        for key in ("metadata_globs", "patch_artifact", "patch_sha256",
                    "base_commit", "root"):
            self.assertIn(key, prov,
                          f"{key} is verifiable provenance and was not to be "
                          "removed along with the two that were")

    def test_the_gate_is_wired_to_read_that_verdict(self):
        with open(os.path.join(REPO_ROOT, "release-gates.json"),
                  encoding="utf-8") as fh:
            gate = next(g for g in json.load(fh)["gates"]
                        if g["id"] == "fork_integrity")
        self.assertEqual(gate["runner"], "verdict_json",
                         "an exit_code runner would collapse the four-state "
                         "verdict back into pass or REGRESSION")
        self.assertTrue(gate["verdict_path"])


class TestDeclaredBlastRadius(unittest.TestCase):
    """The declared symbols are the symbols the patch actually produces.

    Every other control in this file checks what the artefact contains. None of
    them checked that the declaration's blast radius matches it: the declared
    list was only ever asserted to have four entries, so a renamed symbol, or
    a patch whose hunks move, would leave the whole suite green while the F4
    check began rejecting the very patch the exception exists to permit.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="glslang_radius_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        with open(DECLARATION, encoding="utf-8") as fh:
            self.doc = json.load(fh)
        self.exc = next(e for e in self.doc["exceptions"]
                        if e["exception_id"] == "glslang-rdcspv-lifecycle")
        self.declared = sorted(self.exc["files"][TARGET]["allowed_symbols"])

    def test_the_fixture_is_the_base_file_it_claims_to_be(self):
        self.assertTrue(os.path.isfile(FIXTURE),
                        "without the vendored base file the blast radius is "
                        "only checkable where a RenderDoc checkout exists")
        self.assertEqual(_digest(FIXTURE), FIXTURE_SHA256,
                         "the vendored base file changed; the declared patch "
                         "would no longer apply to it")

    def test_the_declared_symbols_are_exactly_the_ones_the_patch_produces(self):
        fork = _scratch_repo(self.root)
        mods = VER.tracked_modifications(fork)
        produced = sorted({VER._classify_hunk(fork, TARGET, h)
                           for h in mods[TARGET]})
        self.assertEqual(self.declared, produced)

    def test_the_declaration_pins_the_base_the_fixture_came_from(self):
        self.assertEqual(self.exc["provenance"]["base_commit"], BASE_COMMIT)

    def test_a_symbol_outside_the_declared_set_is_rejected(self):
        """The boundary is load-bearing, not decorative."""
        fork = _scratch_repo(self.root)
        narrowed = json.loads(json.dumps(self.exc))
        narrowed["files"][TARGET]["allowed_symbols"] = ["rdcspv::Init"]
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(fork, self._with_only(narrowed), REPO_ROOT)
        self.assertEqual(ctx.exception.code, "F4")

    def _with_only(self, exc):
        doc = json.loads(json.dumps(self.doc))
        doc["exceptions"] = [exc]
        path = os.path.join(self.root, "decl.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path


class TestDeliveredWorkspacePasses(unittest.TestCase):
    """The success path, proved rather than assumed.

    Every committed control in this file proves a rejection. If the audit could
    never return PASS on a compliant workspace, the suite would stay green and
    the CI verdict would be indistinguishable from a real violation. The
    capture exception's success path is covered elsewhere against a synthetic
    repository; this covers the driver exception's.

    The scratch repository's commit is not b7f1554fe -- it cannot be, it is a
    different history -- so the declaration's base is repointed at it here. The
    declared value itself is pinned separately, by
    test_the_declaration_pins_the_base_the_fixture_came_from and by
    TestGlslangArtefactIsDeclared.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="glslang_pass_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        with open(DECLARATION, encoding="utf-8") as fh:
            self.doc = json.load(fh)
        self.exc = next(e for e in self.doc["exceptions"]
                        if e["exception_id"] == "glslang-rdcspv-lifecycle")

    def _declaration(self, fork):
        doc = json.loads(json.dumps(self.doc))
        doc["exceptions"] = [json.loads(json.dumps(self.exc))]
        doc["exceptions"][0]["provenance"]["base_commit"] = _git(
            fork, "rev-parse", "HEAD").strip()
        path = os.path.join(self.root, "decl.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def test_the_delivered_workspace_passes(self):
        fork = _scratch_repo(self.root)
        summary = VER.verify(fork, self._declaration(fork), REPO_ROOT)
        self.assertEqual(summary["exceptions"], 1)
        self.assertEqual(summary["tracked_modifications"], 1)

    def test_an_undeclared_driver_change_still_fails_it(self):
        fork = _scratch_repo(self.root)
        decl = self._declaration(fork)
        VER.verify(fork, decl, REPO_ROOT)          # the compliant state
        extra = os.path.join(fork, "renderdoc", "driver", "other.cpp")
        os.makedirs(os.path.dirname(extra), exist_ok=True)
        with open(extra, "w", encoding="utf-8") as fh:
            fh.write("int stray;\n")
        # Tracked, not merely present: the comparison reads `git diff HEAD`, so
        # an untracked file is invisible to it and would make this pass for the
        # wrong reason.
        _git(fork, "add", "-A")
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(fork, decl, REPO_ROOT)
        self.assertEqual(ctx.exception.code, "F1")

    def test_a_tampered_digest_still_fails_it(self):
        fork = _scratch_repo(self.root)
        doc = json.loads(json.dumps(self.doc))
        doc["exceptions"] = [json.loads(json.dumps(self.exc))]
        doc["exceptions"][0]["provenance"]["base_commit"] = _git(
            fork, "rev-parse", "HEAD").strip()
        doc["exceptions"][0]["provenance"]["patch_sha256"] = "0" * 64
        path = os.path.join(self.root, "bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        with self.assertRaises(VER.Violation) as ctx:
            VER.verify(fork, path, REPO_ROOT)
        self.assertEqual(ctx.exception.code, "F3")


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
