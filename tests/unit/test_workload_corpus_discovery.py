"""Workload corpus discovery admits only the declared canonical fixtures.

Written against the defect, before the fix.

`discover_corpus` globbed every `*.rdc` and matched a `w<digits>` prefix against
the stem. That accepted `w00001_evil.rdc` as the 1-draw tier and admitted any
`wNNNNN.rdc` as a population member, so a file nobody declared could be picked
up and run as a workload sample.

The harness is not a gate consumer and is ruled against as one, so this is a
containment fix inside one non-gating module. It introduces no manifest, no
digest and no content identity: membership is the producer's declared
canonical name set, the same source the integration gate already uses.
"""

import importlib
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

CANONICAL = [
    "w00001_frame11.rdc", "w00002_frame11.rdc", "w00004_frame11.rdc",
    "w00008_frame11.rdc", "w00016_frame11.rdc", "w00032_frame11.rdc",
    "w00064_frame11.rdc", "w00128_frame11.rdc", "w00256_frame11.rdc",
    "w00512_frame11.rdc", "w01024_frame11.rdc", "w02048_frame11.rdc",
    "w10000_frame11.rdc", "w20000_frame11.rdc",
]


def _harness():
    return importlib.import_module("tests.workload.harness")


def _producer():
    spec = importlib.util.spec_from_file_location(
        "producer_for_discovery", os.path.join(REPO_ROOT, "scripts",
                                               "workload_corpus.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDiscoveryIsTheDeclaredPopulation(unittest.TestCase):
    """Membership is the declared set, not a prefix match."""

    def setUp(self):
        self.h = _harness()

    def _discover_in(self, names):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in names:
            with open(os.path.join(tmp.name, name), "wb") as fh:
                fh.write(b"not a real capture")
        original = self.h.CORPUS_DIR
        self.h.CORPUS_DIR = self.h.Path(tmp.name)
        try:
            return self.h.discover_corpus()
        finally:
            self.h.CORPUS_DIR = original

    def test_the_declared_names_match_the_producer(self):
        """FLOW: discovery membership comes from the producer's canonical set.

        If the harness kept its own name construction the two lists could
        diverge silently, which is the drift the producer fix removed.
        """
        self.assertEqual(sorted(self.h.declared_fixture_names()),
                         sorted(CANONICAL))
        self.assertEqual(sorted(_producer().DRAWS),
                         sorted(self.h.DRAW_COUNTS))

    def test_a_complete_population_is_discovered(self):
        """Positive control: the legal 14 files are all found."""
        found = self._discover_in(CANONICAL)
        self.assertEqual(len(found), 14)
        self.assertEqual(sorted(c["draws"] for c in found),
                         [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048,
                          10000, 20000])

    def test_a_forged_same_prefix_file_is_not_admitted(self):
        """Negative: `w00001_evil.rdc` must not stand in for the tier.

        The old prefix match read `w00001` off the stem and accepted it. Under
        exact membership the tier stays absent instead of being filled by a
        file nobody declared.
        """
        corpus = [n for n in CANONICAL if n != "w00001_frame11.rdc"]
        corpus.append("w00001_evil.rdc")
        found = self._discover_in(corpus)
        self.assertEqual(len(found), 13)
        self.assertNotIn(1, [c["draws"] for c in found])
        for cap in found:
            self.assertNotIn("evil", cap["path"])

    def test_an_undeclared_draw_count_is_not_admitted(self):
        """Negative: a plausible but undeclared name is still not a member."""
        found = self._discover_in(CANONICAL + ["w00003_frame11.rdc"])
        self.assertEqual(len(found), 14)
        self.assertNotIn(3, [c["draws"] for c in found])

    def test_an_extra_capture_does_not_change_the_population(self):
        """A file nobody declared must not enlarge what the harness runs."""
        found = self._discover_in(CANONICAL + ["w00001_evil.rdc",
                                               "w00003_frame11.rdc",
                                               "zzz_other.rdc"])
        self.assertEqual(len(found), 14)

    def test_an_absent_corpus_directory_is_still_empty(self):
        """The pre-existing empty case is preserved, not turned into an error."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        missing = os.path.join(tmp.name, "no-such-dir")
        original = self.h.CORPUS_DIR
        self.h.CORPUS_DIR = self.h.Path(missing)
        try:
            self.assertEqual(self.h.discover_corpus(), [])
        finally:
            self.h.CORPUS_DIR = original


if __name__ == "__main__":
    unittest.main()
