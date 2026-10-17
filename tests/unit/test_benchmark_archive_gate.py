"""Controls for the benchmark archive gate (DESIGN_SPEC 4.4).

The gate reads a manifest and a repository and answers whether the archived
benchmark still covers the code it is attached to. Every classification is
proven against a state the control builds: the negative controls drive a
throwaway repository with its own manifest, so the verdicts are exercised
against repositories that exist rather than asserted about in a table. The
final control runs the gate against the real repository, because the fact the
release pipeline will act on is that the real archive covers this HEAD, and
that is a property of this tree rather than of the gate's logic.

The change-coupling semantics are pinned in both directions: a monitored
change without re-archiving is REGRESSION (and the gate names the file), and
re-archiving -- advancing archived_at_commit with a new archive -- returns
it to PASS. The two must be pinned together, or a gate that never went green
again would pass its own controls.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATE = os.path.join(REPO_ROOT, "scripts", "benchmark_archive_gate.py")
REAL_MANIFEST = os.path.join(REPO_ROOT, "docs", "validation",
                             "benchmark-archive-manifest.json")


def _load_gate():
    spec = importlib.util.spec_from_file_location("benchmark_archive_gate",
                                                  GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FixtureRepo:
    """A throwaway repository with a monitored surface and an archive.

    The gate must be drivable against a repository the control owns; the
    real one is read-only for these purposes, and every negative state below
    would be vandalism if built in place.
    """

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="rdebug-bench-gate-")
        self._git("init", "-q")
        self._git("config", "user.email", "control@example.com")
        self._git("config", "user.name", "control")
        self.write("src/session_cache.py", "# session surface\n")
        self.write("docs/archive.md", "# benchmark archive\n")
        self.commit("initial surface and archive")

    def _git(self, *args):
        return subprocess.run(["git", "-C", self.root, *args],
                              capture_output=True, text=True)

    def write(self, rel, content):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)

    def commit(self, message):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)

    def head(self):
        return self._git("rev-parse", "HEAD").stdout.strip()

    def sha256(self, rel):
        h = hashlib.sha256()
        with open(os.path.join(self.root, rel), "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def manifest(self, base=None, monitored=("src/session_cache.py",),
                 files=("docs/archive.md",), schema="rdebug-benchmark-archive/1"):
        doc = {
            "schema": schema,
            "spec_gate": "DESIGN_SPEC 4.4",
            "archived_at_commit": base or self.head(),
            "monitored_paths": list(monitored),
            "archive_files": [
                # A declared-but-absent file gets a placeholder digest: the
                # gate classifies its absence before it ever hashes, so a
                # control can build that state without fabricating evidence.
                {"path": rel,
                 "sha256": self.sha256(rel) if os.path.isfile(
                     os.path.join(self.root, rel)) else "0" * 64}
                for rel in files
            ],
        }
        path = os.path.join(self.root, "manifest.json")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            json.dump(doc, fh, indent=1)
        return path

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestChangeCoupling(unittest.TestCase):
    """The decision path: coverage, staleness, re-archiving."""

    def setUp(self):
        self.gate = _load_gate()
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.close)

    def test_pass_when_the_archive_covers_head(self):
        summary = self.gate.verify(self.repo.root, self.repo.manifest())
        self.assertEqual(summary["archived_at_commit"], self.repo.head())

    def test_regression_names_the_changed_monitored_file(self):
        manifest = self.repo.manifest()
        self.repo.write("src/session_cache.py", "# session surface, edited\n")
        self.repo.commit("touch the monitored surface")
        with self.assertRaises(self.gate.GateFailure) as caught:
            self.gate.verify(self.repo.root, manifest)
        self.assertEqual(caught.exception.outcome, "REGRESSION")
        self.assertIn("src/session_cache.py", caught.exception.detail)

    def test_rearchiving_returns_the_gate_to_pass(self):
        manifest = self.repo.manifest()
        self.repo.write("src/session_cache.py", "# session surface, edited\n")
        self.repo.commit("touch the monitored surface")
        with self.assertRaises(self.gate.GateFailure):
            self.gate.verify(self.repo.root, manifest)
        # Re-archive: the manifest advances to the new HEAD with a new
        # digest for nothing changed in the archive itself.
        manifest = self.repo.manifest()
        summary = self.gate.verify(self.repo.root, manifest)
        self.assertEqual(summary["archived_at_commit"], self.repo.head())


class TestInfrastructureClassification(unittest.TestCase):
    """A gate that cannot decide is never a pass, and never a regression."""

    def setUp(self):
        self.gate = _load_gate()
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.close)

    def _infra(self, manifest):
        with self.assertRaises(self.gate.GateFailure) as caught:
            self.gate.verify(self.repo.root, manifest)
        self.assertEqual(caught.exception.outcome, "INFRASTRUCTURE_FAILURE")

    def test_missing_manifest(self):
        self._infra(os.path.join(self.repo.root, "no-such-manifest.json"))

    def test_unparseable_manifest(self):
        path = os.path.join(self.repo.root, "broken.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self._infra(path)

    def test_wrong_schema(self):
        self._infra(self.repo.manifest(schema="rdebug-benchmark-archive/2"))

    def test_archived_commit_is_not_in_this_repository(self):
        self._infra(self.repo.manifest(base="0" * 40))

    def test_declared_archive_file_is_absent(self):
        self._infra(self.repo.manifest(files=("docs/gone.md",)))

    def test_nothing_is_monitored(self):
        self._infra(self.repo.manifest(monitored=()))

    def test_a_monitored_path_that_does_not_exist_watches_nothing(self):
        # A typo'd path makes the coverage diff silently empty, which is a
        # vacuous PASS wearing the shape of a verdict. It must be refused.
        self._infra(self.repo.manifest(monitored=("src/session_cache.pyc",)))


class TestEvidenceIntegrity(unittest.TestCase):
    """The archive itself is content: modifying it is a regression."""

    def setUp(self):
        self.gate = _load_gate()
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.close)

    def test_modified_archive_file_is_regression(self):
        manifest = self.repo.manifest()
        self.repo.write("docs/archive.md", "# benchmark archive, edited\n")
        self.repo.commit("edit the archived evidence")
        with self.assertRaises(self.gate.GateFailure) as caught:
            self.gate.verify(self.repo.root, manifest)
        self.assertEqual(caught.exception.outcome, "REGRESSION")
        self.assertIn("docs/archive.md", caught.exception.detail)


class TestVerdictProtocol(unittest.TestCase):
    """The gate speaks the verdict_json protocol the runner consumes."""

    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.close)

    def _run_gate(self, manifest_path, verdict_rel):
        verdict = os.path.join(self.repo.root, verdict_rel)
        proc = subprocess.run(
            [sys.executable, GATE,
             "--repo-root", self.repo.root,
             "--manifest", manifest_path,
             "--json", verdict],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace")
        with open(verdict, encoding="utf-8") as fh:
            return proc, json.load(fh)

    def test_pass_verdict_shape_and_exit(self):
        proc, doc = self._run_gate(self.repo.manifest(), "verdict.json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(doc["outcome"], "PASS")
        self.assertIn("detail", doc)

    def test_regression_verdict_shape_and_exit(self):
        manifest = self.repo.manifest()
        self.repo.write("src/session_cache.py", "# edited\n")
        self.repo.commit("touch the monitored surface")
        proc, doc = self._run_gate(manifest, "verdict.json")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(doc["outcome"], "REGRESSION")
        self.assertIn("src/session_cache.py", doc["detail"])

    def test_the_runner_renders_the_verdict_without_raising(self):
        # The runner's own detail formatter is the consumer; feeding the
        # verdict through it pins the protocol rather than a guess at it.
        proc, doc = self._run_gate(self.repo.manifest(), "verdict.json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        loader = importlib.util.spec_from_file_location(
            "rg", os.path.join(REPO_ROOT, "scripts", "release_gate.py"))
        rg = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(rg)
        rendered = rg._verdict_detail(doc)
        self.assertIsInstance(rendered, str)
        self.assertIn(doc["outcome"], rendered)


class TestTheRealArchive(unittest.TestCase):
    """The real repository is measured, not assumed covered."""

    def setUp(self):
        self.gate = _load_gate()

    def test_the_real_archive_covers_head(self):
        summary = self.gate.verify(REPO_ROOT, REAL_MANIFEST)
        self.assertTrue(summary["archived_at_commit"])
        self.assertGreaterEqual(summary["monitored"], 1)
        self.assertGreaterEqual(summary["archive_files"], 1)

    def test_every_real_monitored_path_exists_at_head(self):
        with open(REAL_MANIFEST, encoding="utf-8") as fh:
            doc = json.load(fh)
        for rel in doc["monitored_paths"]:
            probe = subprocess.run(
                ["git", "-C", REPO_ROOT, "cat-file", "-e", f"HEAD:{rel}"],
                capture_output=True)
            self.assertEqual(probe.returncode, 0,
                             f"monitored path {rel} is not at HEAD")

    def test_every_real_archive_file_hash_matches(self):
        with open(REAL_MANIFEST, encoding="utf-8") as fh:
            doc = json.load(fh)
        for rec in doc["archive_files"]:
            h = hashlib.sha256()
            with open(os.path.join(REPO_ROOT, rec["path"]), "rb") as fh2:
                for chunk in iter(lambda: fh2.read(1 << 20), b""):
                    h.update(chunk)
            self.assertEqual(h.hexdigest(), rec["sha256"],
                             f"archive file {rec['path']} drifted")


if __name__ == "__main__":
    unittest.main()
