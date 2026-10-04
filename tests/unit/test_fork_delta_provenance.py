"""The accident build's source delta is kept as an auditable artifact.

The only surviving copy of the delta that the accident build contained was an
untracked working-tree modification in the sibling RenderDoc checkout. The
provenance files that `fork-exception.json` names for it do not exist, so that
copy was unrecoverable if lost or edited.

These controls pin the artifact and, when the sibling checkout is present, pin
the live working tree to the same digest. They deliberately do not widen the
declared exception, touch `fork_integrity`, or claim that the provenance chain
was ever complete.
"""

import hashlib
import json
import os
import subprocess
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
FORK = os.path.join(os.path.dirname(REPO_ROOT), "renderdoc")
ARTIFACT = os.path.join(REPO_ROOT, "fork-provenance",
                        "core-cpp-n3-headless-capture-trigger.patch")
EXCEPTION = os.path.join(REPO_ROOT, "fork-exception.json")

#: Recorded in docs/PDB-ATTRIBUTION-RESULT.md section 6.1. Derived as
#: sha256 of `git -C <fork> diff -- renderdoc/core/core.cpp` joined with LF,
#: encoded UTF-8 without BOM and without a trailing newline.
DELTA_SHA256 = (
    "76389727458c9a4e129ae910b5f800541dbb8e8a33a7c3a525a756999bfddd12"
)
BASE_COMMIT = "b7f1554feb0d7d7120f2b9280364b98972ec37d3"
DECLARED_SYMBOL = "RenderDoc::ShouldTriggerCapture"


def _live_delta():
    """The sibling checkout's current delta, canonically normalised."""
    proc = subprocess.run(
        ["git", "-C", FORK, "diff", "--", "renderdoc/core/core.cpp"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return "\n".join(proc.stdout.splitlines())


class TestDeltaArtifactIsIntact(unittest.TestCase):
    """The stored copy must not be edited silently."""

    def test_the_artifact_exists_and_hashes_to_the_recorded_value(self):
        """FLOW: read the artifact -> sha256 -> compare with the record.

        This is the control that makes the artifact worth having. Without it the
        file is just a copy that can drift without anyone noticing.
        """
        self.assertTrue(os.path.isfile(ARTIFACT),
                        "the accident build delta must be preserved on disk")
        with open(ARTIFACT, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(
            digest, DELTA_SHA256,
            "the preserved delta no longer matches its recorded digest, so it "
            "can no longer be used as evidence of the accident build source")

    def test_the_artifact_carries_the_declared_symbol(self):
        """Binds artifact to exception: this is the n3-headless trigger patch."""
        with open(ARTIFACT, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn(DECLARED_SYMBOL, body)
        self.assertIn("renderdoc/core/core.cpp", body)


class TestDeclaredScopeIsUnchanged(unittest.TestCase):
    """Persisting the delta must not have widened what was declared."""

    def setUp(self):
        with open(EXCEPTION, encoding="utf-8") as fh:
            self.spec = json.load(fh)

    def test_the_exception_still_declares_only_the_named_symbol(self):
        exception = self.spec["exceptions"][0]
        self.assertEqual(exception["exception_id"], "n3-headless-capture-trigger")
        for path, entry in exception["files"].items():
            self.assertEqual(path, "renderdoc/core/core.cpp")
            self.assertEqual(entry["allowed_symbols"], [DECLARED_SYMBOL])
            self.assertEqual(entry["allowed_file_scope"], ["include_block"])

    def test_replay_remains_an_excluded_surface(self):
        """The exclusion that keeps the fork gate honest is untouched."""
        exception = self.spec["exceptions"][0]
        self.assertIn("replay", exception["excluded_surfaces"])
        self.assertTrue(exception["not_a_replay_change"])


class TestLiveTreeStillMatchesTheArtifact(unittest.TestCase):
    """Drift in either direction is visible.

    Skipped rather than failed when the sibling checkout is absent: a fresh
    clone legitimately does not have it, and a control that cannot run there
    must not be reported as a pass or as a failure.
    """

    def test_the_working_tree_delta_still_matches_the_saved_copy(self):
        live = _live_delta()
        if live is None:
            self.skipTest("sibling RenderDoc checkout is not present")
        digest = hashlib.sha256(live.encode("utf-8")).hexdigest()
        self.assertEqual(
            digest, DELTA_SHA256,
            "the live working-tree delta no longer matches the preserved "
            "artifact. Either the copy drifted or the tree changed, and the "
            "accident build source can no longer be stated from either alone")


if __name__ == "__main__":
    unittest.main()
