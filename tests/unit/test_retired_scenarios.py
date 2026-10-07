"""Controls for retired workload scenarios.

A retirement that only exists in a document is a retirement somebody will
re-litigate. These controls make three properties mechanical:

  * every retirement carries a complete, honest record;
  * a retired scenario cannot quietly re-enter the active diagnostic set;
  * the coverage that justified the retirement still exists.

The last one matters most. A retirement justified by "covered elsewhere" stops
being true the moment the covering test is deleted or renamed, and nothing in
the workload suite would notice. Here it would.

These are in the unit gate deliberately: the invariant is governance, and
governance that nothing checks is a comment.
"""

import json
import os
import pathlib
import shutil
import sys
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
MANIFEST = os.path.join(REPO_ROOT, "tests", "workload", "retired_scenarios.json")

REQUIRED_ENTRY_FIELDS = (
    "scenario", "state", "retired_on", "owner", "adjudication",
    "adjudication_commit", "reason", "reason_detail", "not_a_regression",
    "replacement_coverage", "reproduce_original_failure", "last_failure",
    "test_method",
)

# Words that would convert a retirement into a false claim. A retired scenario
# did not start working; the assertion it made is held somewhere else.
FORBIDDEN_CLAIMS = ("fixed", "passing", "passed", "resolved", "obsolete",
                    "no longer needed", "not a bug")

VALID_STATES = ("RETIRED",)


class UnimportableModule(Exception):
    """A module that is present but will not load.

    Separate from "the module does not exist" because a governance control that
    cannot tell them apart will report a deleted test as the reason a
    retirement is unjustified, which is a false claim about the repository
    manufactured by an environment fault.
    """

    def __init__(self, dotted, cause):
        self.dotted = dotted
        self.cause = cause
        super().__init__(
            dotted + " exists but failed to import: " + str(cause))


def _load():
    with open(MANIFEST, encoding="utf-8") as handle:
        return json.load(handle)


def _entries():
    return _load().get("retired") or []


class TestRetirementRecordsAreComplete(unittest.TestCase):
    """A retirement with a missing field is an undocumented decision."""

    def test_manifest_exists_and_parses(self):
        self.assertTrue(os.path.isfile(MANIFEST),
                        f"retirement manifest missing at {MANIFEST}")
        self.assertEqual(_load()["schema"], "rdebug-retired-scenarios/1")

    def test_every_entry_carries_every_required_field(self):
        entries = _entries()
        self.assertTrue(entries, "manifest declares no retirements at all")
        for entry in entries:
            for field in REQUIRED_ENTRY_FIELDS:
                self.assertIn(field, entry,
                              f"{entry.get('scenario')!r} is missing {field!r}")
                self.assertNotEqual(entry[field], "", f"{field!r} is empty")

    def test_every_entry_has_an_owner_and_a_dated_adjudication(self):
        for entry in _entries():
            self.assertTrue(str(entry["owner"]).strip())
            self.assertRegex(str(entry["retired_on"]), r"^\d{4}-\d{2}-\d{2}$")
            self.assertRegex(str(entry["adjudication_commit"]), r"^[0-9a-f]{7,40}$")
            self.assertTrue(os.path.isfile(
                os.path.join(REPO_ROOT, entry["adjudication"])),
                f"adjudication doc missing: {entry['adjudication']}")

    def test_state_is_a_known_value(self):
        for entry in _entries():
            self.assertIn(entry["state"], VALID_STATES)

    def test_retirement_is_never_claimed_as_a_fix(self):
        # The distinction the whole exercise turned on: the scenario did not
        # start working, its assertion is held elsewhere. Wording that says
        # "fixed" or "obsolete" is a false claim about the code.
        for entry in _entries():
            blob = json.dumps(entry).lower()
            for claim in FORBIDDEN_CLAIMS:
                self.assertNotIn(
                    claim, blob,
                    f"{entry['scenario']!r} record asserts {claim!r}; a "
                    "retirement is not a fix and not obsolescence")

    def test_reason_names_coverage_rather_than_difficulty(self):
        for entry in _entries():
            self.assertEqual(
                entry["reason"], "covered_by_existing_blocking_gates",
                "a retirement must state what covers the assertion, not that "
                "it was awkward")

    def test_non_regression_is_recorded_with_a_reason(self):
        for entry in _entries():
            self.assertIs(entry["not_a_regression"], True)
            self.assertTrue(str(entry["not_a_regression_reason"]).strip())

    def test_original_failure_evidence_is_preserved(self):
        for entry in _entries():
            failure = entry["last_failure"]
            for field in ("type", "exception", "site", "exit_code"):
                self.assertIn(field, failure)
            self.assertTrue(str(failure["exception"]).strip())
            self.assertNotEqual(failure["exit_code"], 0,
                                "a retirement record whose last failure was exit "
                                "0 is not preserving a failure")

    def test_reproduction_command_is_recorded(self):
        for entry in _entries():
            self.assertIn("isolated_runner", entry["reproduce_original_failure"])


class TestRetirementCannotBeUndoneSilently(unittest.TestCase):

    def test_retired_test_is_not_collected_by_default_discovery(self):
        from tests.workload import test_workload_reliability as mod

        collected = set()
        stack = [unittest.TestLoader().loadTestsFromModule(mod)]
        while stack:
            node = stack.pop()
            if isinstance(node, unittest.TestSuite):
                stack.extend(node)
            else:
                collected.add(node.id().rsplit(".", 1)[-1])
        for entry in _entries():
            original = entry["test_method"]["original_name"]
            self.assertNotIn(
                original, collected,
                f"{original!r} is collected again; a retired scenario has "
                "re-entered the active diagnostic set")

    def test_retired_method_keeps_a_non_test_name(self):
        from tests.workload import test_workload_reliability as mod

        for entry in _entries():
            retired = entry["test_method"]["retired_name"]
            self.assertTrue(hasattr(mod.TestReliabilityScenarios, retired),
                            "the retired method body should be kept so the "
                            "failure stays reproducible")
            self.assertFalse(retired.startswith("test"),
                             f"{retired!r} would be collected by unittest")

    def test_scenario_function_is_still_reachable(self):
        # Deleting the scenario would erase the evidence. Retirement means
        # unreachable by default, not gone.
        from tests.workload import scenarios

        for entry in _entries():
            self.assertIn(entry["scenario"], scenarios.SCENARIOS,
                          "the scenario must stay callable for reproduction")

    def test_replacement_coverage_is_declared(self):
        for entry in _entries():
            coverage = entry["replacement_coverage"]
            self.assertTrue(coverage,
                            "a retirement justified by coverage must name it")
            for item in coverage:
                self.assertIn(item["gate"], ("unit", "transport", "integration",
                                             "boundary_audit",
                                             "cold_warm_equivalence",
                                             "fork_integrity"))
                self.assertTrue(str(item["asserts"]).strip())


class TestReplacementCoverageStillExists(unittest.TestCase):
    """The load-bearing control.

    A retirement justified by "covered elsewhere" silently becomes false if the
    covering test is renamed or deleted. Nothing in tests/workload would notice,
    because the workload suite does not import the gates. This does.
    """

    def _resolve(self, test_id):
        """Import the longest importable module prefix, then walk attributes.

        Two things bit this control before it worked. tests_transport modules do
        a top-level ``from test_transport import ...``, so they are only
        importable with that directory on sys.path -- which is how the transport
        gate runs them. And splitting the id on the first dot yields ``tests``,
        not ``tests.integration.test_m15_acceptance``, so the walk then looked
        for a submodule that had never been imported onto the package.

        A module that is genuinely absent and a module that is present but whose
        own import fails are told apart, because conflating them makes this
        control lie. Swallowing every ImportError meant a stale bytecode file, a
        half-written source file, or a dependency missing for a moment all
        produced the same answer as a deleted test -- and the failure message
        then claimed a retirement was no longer justified on the grounds that
        the covering test "no longer exists". That is a governance claim
        manufactured out of an environment fault, which is worse than no
        control: it invites someone to re-open a retirement that is fine.

        Only an ImportError naming the module being imported means absence. Any
        other ImportError means the module is right there and failed to load,
        and that is raised rather than reported as absence.
        """
        import importlib

        transport_dir = os.path.join(REPO_ROOT, "tests_transport")
        if transport_dir not in sys.path:
            sys.path.insert(0, transport_dir)

        parts = test_id.split(".")
        module = None
        consumed = 0
        for i in range(len(parts), 0, -1):
            dotted = ".".join(parts[:i])
            try:
                module = importlib.import_module(dotted)
            except ImportError as exc:
                missing = getattr(exc, "name", None)
                if missing is None or not (
                        missing == dotted or dotted.startswith(missing + ".")):
                    raise UnimportableModule(dotted, exc) from exc
                continue
            consumed = i
            break
        if module is None:
            return False
        obj = module
        for attr in parts[consumed:]:
            if not hasattr(obj, attr):
                return False
            obj = getattr(obj, attr)
        return callable(obj)

    def test_every_named_replacement_test_still_exists(self):
        for entry in _entries():
            for item in entry["replacement_coverage"]:
                try:
                    resolved = self._resolve(item["test_id"])
                except UnimportableModule as exc:
                    # Fails, and says what is actually wrong. The assertion is
                    # not loosened: an unjudgeable claim is still a failure, but
                    # it is an environment fault to fix, not a retirement to
                    # re-open.
                    self.fail(
                        item["test_id"] + " exists but could not be imported ("
                        + str(exc) + "), so whether it still covers the "
                        "retirement cannot be judged. This is an environment "
                        "fault, not a deleted test.")
                self.assertTrue(
                    resolved,
                    f"{item['test_id']} no longer exists, so the retirement of "
                    f"{entry['scenario']!r} is no longer justified")

    def test_replacements_are_not_themselves_retired(self):
        retired_methods = {
            e["test_method"]["retired_name"] for e in _entries()}
        for entry in _entries():
            for item in entry["replacement_coverage"]:
                self.assertNotIn(item["test_id"].rsplit(".", 1)[-1],
                                 retired_methods,
                                 "replacement coverage must be active coverage")

    def test_no_replacement_comes_from_the_retired_suite(self):
        # Coverage cannot be justified by the suite that is being retired.
        for entry in _entries():
            for item in entry["replacement_coverage"]:
                self.assertNotIn(
                    "tests.workload", item["test_id"],
                    f"{item['test_id']} is inside tests/workload; a retired "
                    "scenario cannot be its own replacement")


class TestTheResolverTellsAbsentFromBroken(unittest.TestCase):
    """The distinction the coverage control depends on to avoid lying.

    A retirement is justified by "covered elsewhere". If the control cannot
    import the covering test it reports that the test "no longer exists", and
    that is a claim about the repository. It has to be true. These exercise the
    three cases the resolver can be in, so the difference between them is a
    tested property rather than an intention.
    """

    def setUp(self):
        import tempfile

        self.resolver = TestReplacementCoverageStillExists()
        self._tmp = tempfile.mkdtemp(prefix="rdebug-resolve-")
        self.addCleanup(self._added_cleanup)
        sys.path.insert(0, self._tmp)

    def _added_cleanup(self):
        if self._tmp in sys.path:
            sys.path.remove(self._tmp)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _package(self, name, body):
        pkg = pathlib.Path(self._tmp) / name
        pkg.mkdir()
        (pkg / "__init__.py").write_text(body, encoding="utf-8")
        self.addCleanup(sys.modules.pop, name, None)
        return name

    def test_a_module_that_is_genuinely_absent_resolves_to_false(self):
        # Absent is a legitimate answer: the covering test really was deleted,
        # and that is exactly what the control exists to catch.
        self.assertFalse(
            self.resolver._resolve("definitely_absent_pkg_xyz.SomeClass.m"))

    def test_a_module_that_imports_cleanly_resolves_to_true(self):
        name = self._package("presentpkg_ok", "class C:\n    def m(self):\n        pass\n")
        self.assertTrue(self.resolver._resolve(name + ".C.m"))

    def test_a_module_that_exists_but_will_not_import_raises(self):
        # The defect. Swallowing this ImportError made a broken environment
        # indistinguishable from a deleted test, and the failure message then
        # claimed a retirement was unjustified because a covering test "no
        # longer exists" -- a governance claim invented by an environment fault.
        name = self._package("presentpkg_broken",
                             "import definitely_not_a_real_module_xyz\n")
        with self.assertRaises(UnimportableModule) as caught:
            self.resolver._resolve(name + ".C.m")
        self.assertIn("exists but failed to import", str(caught.exception))

    def test_an_absent_submodule_of_a_present_package_is_not_a_broken_module(self):
        # Absence has to stay absence at every depth, or the distinction above
        # would just move the false claim one level down.
        name = self._package("presentpkg_partial", "class C:\n    pass\n")
        self.assertFalse(self.resolver._resolve(name + ".NoSuchClass.m"))
        self.assertFalse(self.resolver._resolve(name + ".nosuchmodule.m"))


class TestRetirementDidNotRegressTheCodeUnderTest(unittest.TestCase):
    """Guards the things the authorisation explicitly forbade."""

    def test_removed_symbols_are_still_absent(self):
        # Restoring _session_factory to make the old scenario run again would
        # contradict test_m15_acceptance:124-129, which requires it absent.
        from rdebug_mcp import server

        for gone in ("_MANAGER", "_session_factory", "_open", "_session"):
            self.assertFalse(hasattr(server, gone),
                             f"server.{gone} was restored; M1.3 removed it and "
                             "a blocking gate asserts it is absent")

    def test_workload_is_not_admitted_to_any_gate(self):
        with open(os.path.join(REPO_ROOT, "release-gates.json"),
                  encoding="utf-8") as handle:
            spec = json.load(handle)
        for gate in spec["gates"]:
            self.assertNotIn(
                "tests/workload", json.dumps(gate.get("command")),
                f"gate {gate['id']!r} runs tests/workload; it remains a "
                "section 5 diagnostic")
        self.assertNotIn("workload", [g["id"] for g in spec["gates"]])
        # The corpus directory is not the test suite. cold_warm_equivalence
        # legitimately points at a capture under tests/workload/corpus, so a
        # whole-file substring search produces a false positive here -- it did,
        # once. Scoping the check to commands is what makes it true.
        self.assertIn("tests/workload/corpus",
                      json.dumps(spec.get("captures") or {}),
                      "expected the cold/warm capture to live under the "
                      "workload corpus; a whole-file search would flag this")


if __name__ == "__main__":
    unittest.main()
