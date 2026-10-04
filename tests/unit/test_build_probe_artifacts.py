"""The generation probe's primary artifacts are preserved and self-verifying.

Section 8 asserted a 320-target evaluated surface, the absence of a
DesignTimeBuild target, and 38 evaluated DependsOn properties. Those numbers
originally came from files in a temporary directory that would be cleared. They
are now kept in build-probe/ with a manifest, and these controls both pin the
digests and re-derive the two decisive claims from the artifacts themselves, so
the record cannot drift away from its own evidence.
"""

import hashlib
import json
import os
import unittest
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
ARTIFACT_DIR = os.path.join(REPO_ROOT, "build-probe")
MANIFEST = os.path.join(ARTIFACT_DIR, "MANIFEST.sha256")
NS = "{http://schemas.microsoft.com/developer/msbuild/2003}"

EXPECTED_TARGET_COUNT = 320
EXPECTED_PROPERTY_COUNT = 38


def _manifest():
    entries = {}
    with open(MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            digest, name = line.split("  ", 1)
            entries[name] = digest
    return entries


class TestArtifactsAreIntact(unittest.TestCase):
    """Every stored file must still hash to its recorded value."""

    def test_every_manifest_entry_matches(self):
        for name, digest in _manifest().items():
            path = os.path.join(ARTIFACT_DIR, name)
            self.assertTrue(os.path.isfile(path), f"{name} is missing")
            with open(path, "rb") as fh:
                actual = hashlib.sha256(fh.read()).hexdigest()
            self.assertEqual(
                actual, digest,
                f"{name} no longer matches its recorded digest, so it can no "
                "longer be cited as the probe's evidence")

    def test_no_unlisted_file_is_present(self):
        """An extra file would be unaccounted-for evidence."""
        present = {n for n in os.listdir(ARTIFACT_DIR)
                   if n != "MANIFEST.sha256"}
        self.assertEqual(
            sorted(present), sorted(_manifest()),
            "build-probe holds a file the manifest does not cover")


class TestClaimsAreRederivedFromTheArtifacts(unittest.TestCase):
    """The decisive numbers must follow from the stored evidence."""

    def test_the_evaluated_surface_has_320_targets_and_no_design_time_target(self):
        """FLOW: parse renderdoc_pp.xml -> count Target names.

        This is the direct evidence for section 8.1 and 8.3: the evaluated
        surface holds 320 targets and none of them is called
        DesignTimeBuild, which is why the original invocation was an invalid
        probe rather than a project failure.
        """
        path = os.path.join(ARTIFACT_DIR, "renderdoc_pp.xml")
        root = ET.parse(path).getroot()
        names = {t.get("Name") for t in root.findall(f"{NS}Target")}
        self.assertEqual(
            len(names), EXPECTED_TARGET_COUNT,
            "the evaluated surface size changed, so the recorded count is no "
            "longer what this checkout produces")
        self.assertNotIn(
            "DesignTimeBuild", names,
            "a target named DesignTimeBuild now exists; section 8.3 would no "
            "longer hold and G3 would have to be reclassified")
        self.assertIn("DesignTimeXamlMarkupCompilation", names)

    def test_the_evaluated_depends_on_properties_are_recorded(self):
        """FLOW: parse props.out -> count properties -> check BuildDependsOn.

        This is the evidence that property indirection is observable at all,
        and that the top-level order reaches the compile phase without any
        target having been executed.
        """
        path = os.path.join(ARTIFACT_DIR, "props.out")
        with open(path, encoding="utf-8") as fh:
            props = json.load(fh)["Properties"]
        self.assertEqual(len(props), EXPECTED_PROPERTY_COUNT)
        build_chain = props["BuildDependsOn"]
        for phase in ("PrepareForBuild", "ResolveReferences",
                      "BuildGenerateSources", "BuildCompile"):
            self.assertIn(
                phase, build_chain,
                f"{phase} is no longer in the evaluated BuildDependsOn, so the "
                "recorded effective order no longer matches this checkout")

    def test_the_binlogs_show_no_compiler_or_link_invocation(self):
        """FLOW: decompress each binlog -> scan for invocation evidence.

        The record claims no C++ compilation occurred. That claim is only worth
        something if the logs that establish it are still here.
        """
        import gzip
        for name in ("G1.binlog", "G2.binlog", "G3.binlog"):
            path = os.path.join(ARTIFACT_DIR, name)
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            self.assertNotIn("LINK", body, f"{name} records a link step")
            self.assertNotIn("/c ", body,
                             f"{name} records a compiler command line")


if __name__ == "__main__":
    unittest.main()
