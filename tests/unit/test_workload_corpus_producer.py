"""workload_corpus producer: naming contract and membership.

Written against the defect, before the fix.

The producer had three mutually inconsistent statements about the same
14-file population: it tested for ``w00001_frame11.rdc``, it wrote through
a stem that makes the app emit that same name, and it documented
``w00001.rdc``. Because the canonical files were already present, every run
took the skip branch and still reported ``corpus ready: 14`` -- a count that
was evidence of the skip counter, not of the population. It also counted
tier membership with a ``w00001*.rdc`` prefix glob, so ``w00001_evil.rdc``
satisfied the 1-draw tier.

These controls pin the naming contract and the membership check. They
deliberately exercise pure logic only: the real generation path needs a GPU
and MSVC, so no test may stand in for it by fabricating a capture.
"""

import importlib.util
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PRODUCER = os.path.join(REPO_ROOT, "scripts", "workload_corpus.py")

#: The population the producer is contracted to produce, pinned explicitly so
#: a change to DRAWS cannot silently redefine what the corpus is.
EXPECTED = [
    "w00001_frame11.rdc", "w00002_frame11.rdc", "w00004_frame11.rdc",
    "w00008_frame11.rdc", "w00016_frame11.rdc", "w00032_frame11.rdc",
    "w00064_frame11.rdc", "w00128_frame11.rdc", "w00256_frame11.rdc",
    "w00512_frame11.rdc", "w01024_frame11.rdc", "w02048_frame11.rdc",
    "w10000_frame11.rdc", "w20000_frame11.rdc",
]


def _producer():
    spec = importlib.util.spec_from_file_location("workload_corpus", PRODUCER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProducerNamingContract(unittest.TestCase):
    """One canonical name per tier, used by every statement about it."""

    def setUp(self):
        self.mod = _producer()

    def test_canonical_names_are_the_documented_population(self):
        """FLOW: DRAWS -> canonical_name -> the 14 names the docs cite.

        The `_frame11` suffix is not a preference. The app is handed the stem
        `w00001.rdc` and emits `w00001_frame11.rdc`, and that name is what
        README, DESIGN_SPEC, D4-EVIDENCE, F12, GATE3 and the freeze records
        all cite. Dropping the suffix would invalidate those records.
        """
        produced = [self.mod.canonical_name(d)
                    for d in self.mod.DRAWS]
        self.assertEqual(
            produced, EXPECTED,
            "the producer's canonical population must match the names the "
            "evidence documents cite")
        self.assertEqual(len(self.mod.DRAWS), 14)

    def test_population_lists_canonical_paths_only(self):
        """The declared population is 14 exact paths, not a glob result."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.mod.population(corpus_dir=self.mod.Path(tmp))
            self.assertEqual([p.name for p in paths], EXPECTED)


class TestProducerMembershipIsExact(unittest.TestCase):
    """A tier is satisfied by its canonical file and nothing else."""

    def setUp(self):
        self.mod = _producer()

    def _corpus(self, names):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in names:
            (self.mod.Path(tmp.name) / name).write_bytes(b"not a real capture")
        return tmp.name

    def test_a_complete_population_has_nothing_missing(self):
        """Positive control: the legal 14-file population is recognised."""
        corpus = self._corpus(EXPECTED)
        self.assertEqual(self.mod.missing_draws(corpus_dir=corpus), [])

    def test_a_deleted_fixture_is_reported_missing(self):
        """Negative: absence must be reported, not tolerated."""
        corpus = self._corpus([n for n in EXPECTED
                               if n != "w00016_frame11.rdc"])
        self.assertEqual(self.mod.missing_draws(corpus_dir=corpus), [16])

    def test_a_substituted_tier_is_not_accepted_by_prefix(self):
        """Negative: `w00001_evil.rdc` must not satisfy the 1-draw tier.

        The old check globbed `w00001*.rdc`, so a file that merely started
        with the tier's prefix was counted as that tier's capture.
        """
        corpus = self._corpus([n for n in EXPECTED
                               if n != "w00001_frame11.rdc"])
        self.mod.Path(corpus, "w00001_evil.rdc").write_bytes(b"injected")
        self.assertEqual(self.mod.missing_draws(corpus_dir=corpus), [1])

    def test_the_documented_legacy_name_is_not_canonical(self):
        """Negative: the name the docstring used is not the fixture.

        `w00001.rdc` is the stem handed to the app, not the artefact. Treating
        it as the fixture would let a half-written capture satisfy the tier.
        """
        corpus = self._corpus([n for n in EXPECTED
                               if n != "w00001_frame11.rdc"])
        self.mod.Path(corpus, "w00001.rdc").write_bytes(b"legacy stem")
        self.assertEqual(self.mod.missing_draws(corpus_dir=corpus), [1])


class TestProducerRerunIsIdempotentWithoutAGpu(unittest.TestCase):
    """A satisfied population must not reach the generation path."""

    def test_rerun_reports_ready_without_building_the_fixture_app(self):
        """FLOW: main() -> missing_draws() empty -> report and return.

        The generation path needs a GPU and MSVC. Idempotency is only
        observable if a complete population short-circuits before that, so
        this also pins the property that the happy path is testable here.
        find_exe is replaced with a tripwire rather than allowed to run.
        """
        mod = _producer()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in EXPECTED:
            (mod.Path(tmp.name) / name).write_bytes(b"not a real capture")

        def tripwire():
            raise AssertionError(
                "the generation path was entered with a complete population")

        original = (mod.CORPUS, mod.WORKDIR, mod.find_exe)
        mod.CORPUS, mod.WORKDIR, mod.find_exe = (
            mod.Path(tmp.name), mod.Path(tmp.name) / "wd", tripwire)
        try:
            self.assertEqual(mod.main(), 0)
        finally:
            mod.CORPUS, mod.WORKDIR, mod.find_exe = original


if __name__ == "__main__":
    unittest.main()
