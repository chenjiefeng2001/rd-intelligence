"""Step A: integration capture membership, Layer A only.

Written against the defect, before the implementation.

Before this, the integration gate accepted any existing file as its capture.
``check_requires`` asked only whether ``RDEBUG_INTEGRATION_CAPTURE`` was a file,
so a real capture from a different population, or a real file that was never a
capture at all, satisfied the prerequisite and went on to drive the gate.

Scope, as frozen: integration only (Step C / C1), producer declaration as the
source, pre-run adjudication (Step S / S1) resolving to the existing
INFRASTRUCTURE_FAILURE with its own reason string. Nothing here may add a
verdict, change precedence, touch cold_warm, or claim content identity: a
canonical name whose content was swapped stays undetectable and belongs to
Layer B.
"""

import importlib.util
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gate_spec():
    import json
    with open(os.path.join(REPO_ROOT, "release-gates.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _gate(gid):
    for gate in _gate_spec()["gates"]:
        if gate.get("id") == gid:
            return gate
    raise AssertionError("no such gate: " + gid)


def _a_real_non_member_file():
    """A path that exists, is a file, and is not a declared fixture."""
    return os.path.join(REPO_ROOT, "release-gates.json")


class TestDeclaredPopulation(unittest.TestCase):
    """The gate reads the producer's canonical set, not a second copy."""

    def setUp(self):
        self.rg = _load("rg_membership_a", os.path.join(
            REPO_ROOT, "scripts", "release_gate.py"))

    def test_the_declared_set_is_the_producer_population(self):
        """FLOW: _declared_population() -> producer.population().

        Computed from names, so it does not require the captures to be present.
        That keeps this control runnable on a clean clone, where the corpus is
        untracked and absent.
        """
        producer = _load("producer_for_membership", os.path.join(
            REPO_ROOT, "scripts", "workload_corpus.py"))
        expected = {os.path.normcase(os.path.abspath(p))
                    for p in producer.population()}
        self.assertEqual(self.rg._declared_population(), expected)
        self.assertEqual(len(expected), 14)

    def test_membership_is_an_exact_path_test(self):
        """No prefix or substring acceptance, and path spelling is normalised."""
        declared = {os.path.normcase(os.path.abspath("corpus/a.rdc"))}
        inside = self.rg._capture_in_declared_population(
            "corpus/a.rdc", declared)
        self.assertTrue(inside)
        sibling = self.rg._capture_in_declared_population(
            "corpus/a.rdc.evil", declared)
        self.assertFalse(sibling, "a longer name is not a member")
        elsewhere = self.rg._capture_in_declared_population(
            "corpus/b.rdc", declared)
        self.assertFalse(elsewhere)
        self.assertFalse(
            self.rg._capture_in_declared_population("corpus/a.rdc", set()))


class TestPreRunMembershipAdjudication(unittest.TestCase):
    """A non-member is a prerequisite failure, decided before the gate runs."""

    def setUp(self):
        self.rg = _load("rg_membership_b", os.path.join(
            REPO_ROOT, "scripts", "release_gate.py"))
        self.capture = _a_real_non_member_file()
        self.env = {"RDEBUG_INTEGRATION_CAPTURE": self.capture}
        self._original = self.rg._declared_population
        self.rg._declared_population = lambda: {os.path.normcase(
            os.path.abspath(os.path.join(REPO_ROOT, "scripts", "never.rdc")))}

    def tearDown(self):
        self.rg._declared_population = self._original

    def test_a_non_member_is_reported_with_its_own_reason(self):
        """The verdict stays INFRA; the reason must not be the absence reason."""
        missing = self.rg.check_requires(_gate("integration"), REPO_ROOT,
                                         self.env)
        membership = [m for m in missing if "not-in-population" in m]
        self.assertEqual(
            len(membership), 1,
            "a non-member capture must produce exactly one membership reason, "
            f"got {missing}")
        self.assertNotIn(
            "capture:RDEBUG_INTEGRATION_CAPTURE", missing,
            "the file exists, so the absence reason would be misleading; this "
            "is the distinction the frozen decision requires")

    def test_a_member_passes_the_capture_prerequisite(self):
        """The positive path is unchanged: no capture reason at all."""
        self.rg._declared_population = lambda: {
            os.path.normcase(os.path.abspath(self.capture))}
        missing = self.rg.check_requires(_gate("integration"), REPO_ROOT,
                                         self.env)
        self.assertEqual(
            [m for m in missing if m.startswith("capture")], [],
            "a declared member must not produce a capture prerequisite")


class TestExistingSemanticsAreUntouched(unittest.TestCase):
    """Constraint 3: no new verdict, no changed precedence, no new scope."""

    def setUp(self):
        self.rg = _load("rg_membership_c", os.path.join(
            REPO_ROOT, "scripts", "release_gate.py"))

    def test_an_absent_capture_keeps_the_existing_reason(self):
        """A missing file is still reported as missing, with no membership."""
        env = {"RDEBUG_INTEGRATION_CAPTURE": os.path.join(
            REPO_ROOT, "definitely", "not", "here.rdc")}
        missing = self.rg.check_requires(_gate("integration"), REPO_ROOT, env)
        self.assertIn("capture:RDEBUG_INTEGRATION_CAPTURE", missing)
        self.assertEqual([m for m in missing if "not-in-population" in m], [])

    def test_an_unset_capture_keeps_the_env_reason(self):
        """Unset and nonexistent are still distinguishable."""
        missing = self.rg.check_requires(
            _gate("integration"), REPO_ROOT, {})
        self.assertIn("env:RDEBUG_INTEGRATION_CAPTURE", missing)

    def test_an_unavailable_declaration_is_its_own_prerequisite(self):
        """A declaration that cannot be read is a distinct unmet prerequisite.

        Failing open would leave the hole silent; failing with a new verdict is
        forbidden by constraint 3. An unmet prerequisite with its own reason
        keeps the verdict at INFRA and keeps the reason readable.
        """
        def boom():
            raise OSError("producer unreadable")

        original = self.rg._declared_population
        self.rg._declared_population = boom
        try:
            missing = self.rg.check_requires(
                _gate("integration"), REPO_ROOT,
                {"RDEBUG_INTEGRATION_CAPTURE": _a_real_non_member_file()})
        finally:
            self.rg._declared_population = original
        self.assertEqual(
            len([m for m in missing if "population-unavailable" in m]), 1,
            f"expected an unavailable-declaration reason, got {missing}")

    def test_the_verdict_vocabulary_and_precedence_are_unchanged(self):
        """Pinned so a future identity fix cannot quietly add a verdict."""
        self.assertEqual(
            self.rg.BLOCKING,
            (self.rg.REGRESSION, self.rg.UNKNOWN, self.rg.INFRA))
        self.assertEqual(
            self.rg.DEFAULT_EXIT_CODES,
            {"PASS": 0, "FAIL_REGRESSION": 2, "BLOCKED_INFRA": 3,
             "NEEDS_REVIEW": 4})

    def test_cold_warm_is_out_of_scope(self):
        """C1: cold_warm keeps its own mechanism and gains no membership rule."""
        declared = {os.path.normcase(os.path.abspath(
            os.path.join(REPO_ROOT, "scripts", "never.rdc")))}
        original = self.rg._declared_population
        self.rg._declared_population = lambda: declared
        try:
            gate = _gate("cold_warm_equivalence")
            missing = self.rg.check_requires(
                gate, REPO_ROOT,
                {"RDEBUG_INTEGRATION_CAPTURE": _a_real_non_member_file()})
            self.assertEqual(
                [m for m in missing if "not-in-population" in m], [],
                "cold_warm is deliberately out of scope and its single-point "
                "declaration stays a recorded gap")
        finally:
            self.rg._declared_population = original


class TestTheGateNeverRunsTheGenerator(unittest.TestCase):
    """The gate needs a declared population, not a generated one."""

    def test_membership_does_not_invoke_generation(self):
        """FLOW: check_requires -> _declared_population() -> population() only.

        A stub stands in for the producer with tripwires on every generation
        entry point. If the orchestrator ever reaches them, the gate would be
        generating captures as a side effect of a prerequisite check.
        """
        rg = _load("rg_membership_d", os.path.join(
            REPO_ROOT, "scripts", "release_gate.py"))

        class StubProducer:
            def __init__(self):
                self.calls = []

            def population(self):
                self.calls.append("population")
                return [os.path.join(REPO_ROOT, "scripts", "never.rdc")]

            def __getattr__(self, name):
                def tripwire(*a, **k):
                    raise AssertionError(
                        f"the gate reached producer.{name}; it must read the "
                        "declared population only, never generate")
                return tripwire

        stub = StubProducer()
        original = getattr(rg, "_PRODUCER", None)
        had = hasattr(rg, "_PRODUCER")
        rg._PRODUCER = stub
        try:
            env = {"RDEBUG_INTEGRATION_CAPTURE": _a_real_non_member_file()}
            missing = rg.check_requires(_gate("integration"), REPO_ROOT, env)
        finally:
            if had:
                rg._PRODUCER = original
            else:
                del rg._PRODUCER
        self.assertEqual(stub.calls, ["population"])
        self.assertEqual(len([m for m in missing
                              if "not-in-population" in m]), 1)

    def test_the_check_creates_nothing_on_disk(self):
        """A prerequisite check must not write into the corpus directory."""
        rg = _load("rg_membership_e", os.path.join(
            REPO_ROOT, "scripts", "release_gate.py"))
        producer = _load("producer_sideeffect", os.path.join(
            REPO_ROOT, "scripts", "workload_corpus.py"))
        before = sorted(p.name for p in producer.CORPUS.iterdir()) \
            if producer.CORPUS.is_dir() else None
        with tempfile.TemporaryDirectory() as tmp:
            rg._declared_population()
            probe = os.path.join(tmp, "w00001_frame11.rdc")
            with open(probe, "wb") as fh:
                fh.write(b"")
            after = sorted(p.name for p in producer.CORPUS.iterdir()) \
                if producer.CORPUS.is_dir() else None
        self.assertEqual(before, after,
                         "reading the declared population must not create, "
                         "rename or remove anything in the corpus directory")


if __name__ == "__main__":
    unittest.main()
