"""Lint integration controls -- defect version, written before the feature.

`pyproject.toml` configures `[tool.ruff]` and `[tool.ruff.lint]`, and nothing
in the repository executes it. These controls exist to make that impossible to
keep: they fail today, and they must pass only when lint is a real precondition
of the unit gate.

Ruled scope, from docs/LINT-EXECUTION-CONTRACT.md:

  ruff not run / absent / config broken  -> INFRASTRUCTURE_FAILURE
  ruff run and violations                -> REGRESSION

No fifth state. No downgrade to diagnostic. The overall priority stays
REGRESSION > INFRASTRUCTURE_FAILURE > UNKNOWN > PASS. So a real lint violation
lifts the overall verdict from BLOCKED_INFRA to FAIL_REGRESSION, and the
integration gate keeps its own INFRASTRUCTURE_FAILURE row rather than being
erased by that.

lint is a precondition of the existing unit gate. It does not become an eighth
gate.
"""

import json
import os
import re
import sys
import tempfile
import tokenize
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

#: Accepted suppression form: codes then a reason on the same line.
NOQA = re.compile(r"^#\s*noqa(?P<codes>(?::\s*[A-Z]+[0-9]+"
                  r"(?:\s*,\s*[A-Z]+[0-9]+)*)?)\s*(?P<reason>.*)$")

#: Markers that make a suppression temporary. Each of these promises the line
#: will change, so each needs a date it can be checked against.
TEMPORARY = ("temporary", "temporarily", "until", "remove after", "fixme",
             "todo")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _python_files():
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs
                   if d not in (".git", "__pycache__", ".ruff_cache")]
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(root, name)
                yield path, os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")


class TestLintIsAUnitGatePrecondition(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(REPO_ROOT, "release-gates.json"),
                  encoding="utf-8") as fh:
            self.spec = json.load(fh)

    def _unit(self):
        for gate in self.spec["gates"]:
            if gate["id"] == "unit":
                return gate
        self.fail("release-gates.json has no unit gate")

    # 1 -- the precondition is declared
    def test_unit_gate_declares_a_lint_precondition(self):
        gate = self._unit()
        self.assertIn(
            "lint", gate,
            "the unit gate declares no lint precondition. A lint rule with no "
            "executor is a rule that cannot fail anything; four violations "
            "survived several full pipelines for exactly this reason.")

    def test_the_lint_precondition_names_a_real_command(self):
        lint = self._unit().get("lint") or {}
        command = lint.get("command") or []
        self.assertTrue(
            command and "ruff" in " ".join(command),
            f"the lint precondition has no command naming ruff: {command!r}")

    def test_the_precondition_declares_its_availability_probe(self):
        """Exit codes alone cannot tell an absent tool from a violation.

        `python -m ruff` on a machine without ruff exits 1, which is also what
        ruff exits with when it finds violations. So the probe is part of the
        contract, not a convenience: without it the ruled mapping for 'ruff
        absent' silently becomes REGRESSION.
        """
        lint = self._unit().get("lint") or {}
        probe = lint.get("probe_command") or []
        self.assertTrue(
            probe, "the lint precondition declares no probe_command, so a "
                   "missing ruff is indistinguishable from a violation")

    # 2 -- lint must not have become a gate of its own
    def test_lint_is_not_an_eighth_gate(self):
        ids = [g["id"] for g in self.spec["gates"]]
        self.assertEqual(len(ids), 7, f"gate set changed: {ids!r}")
        self.assertNotIn("lint", ids,
                         "lint belongs to the unit gate as a precondition, not "
                         "as an eighth gate. A new gate brings a new exit "
                         "mapping and a new readiness combination.")

    # 3 -- no fifth state, no changed exits
    def test_exit_codes_agree_with_what_overall_actually_returns(self):
        """FLOW, not EXISTENCE.

        The sibling control asserts the mapping strings are present in the
        source. That is existence: a later edit could leave every string intact
        while overall() started returning something else, and the control would
        stay green. Recorded as a deviation against
        docs/CONTROL-ADMISSION-CONTRACT.md section 4, which says exactly this
        about this control.

        So this drives overall() and compares what it returns against
        DEFAULT_EXIT_CODES. A synthetic spec with every gate IMPLEMENTED is used
        because the real one keeps benchmark_archive PROCESS_ONLY, which holds
        the aggregate off PASS by design -- asserted separately below.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rg", os.path.join(REPO_ROOT, "scripts", "release_gate.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        everything = {"gates": [{"id": "g1", "state": "IMPLEMENTED",
                                 "required_execution": True,
                                 "blocking": True}]}

        def row(outcome):
            return {"gate": "g1", "outcome": outcome, "state": "IMPLEMENTED",
                    "required_execution": True, "attempted": True,
                    "executed": 1}

        # Compared against the module's constants, not their names. PASS_OVERALL
        # has the value "PASS", so asserting the string "PASS_OVERALL" failed
        # against a mapping that was already correct -- this control's first
        # version mistook a constant for its own name, which is the same
        # near-miss the section 6.1 mapping work ran into.
        for outcome, state in (("PASS", module.PASS_OVERALL),
                               ("REGRESSION", module.FAIL_REGRESSION),
                               ("INFRASTRUCTURE_FAILURE", module.BLOCKED_INFRA),
                               ("UNKNOWN", module.NEEDS_REVIEW)):
            got = module.overall(everything, [row(outcome)])
            self.assertEqual(
                got["status"], state,
                f"one {outcome} gate produced {got['status']!r}, not {state!r}")
            self.assertEqual(
                got["exit_code"], module.DEFAULT_EXIT_CODES[state],
                f"{state} returned exit {got['exit_code']}, but "
                f"DEFAULT_EXIT_CODES says {module.DEFAULT_EXIT_CODES[state]}. "
                "The strings in the source are not the mapping the pipeline "
                "actually uses.")

    def test_a_process_only_gate_holds_the_aggregate_off_pass(self):
        """The invariant from contract 1.1, checked against the real spec.

        Declaring a gate PROCESS_ONLY must make it impossible to report PASS.
        If this ever passes, a gate with nothing to run has stopped holding
        the aggregate off PASS -- which is the failure the whole four-state
        ordering exists to prevent.
        """
        import importlib.util
        loader = importlib.util.spec_from_file_location(
            "rg", os.path.join(REPO_ROOT, "scripts", "release_gate.py"))
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        with open(os.path.join(REPO_ROOT, "release-gates.json"),
                  encoding="utf-8") as fh:
            spec = json.load(fh)
        rows = [{"gate": g["id"], "outcome": "PASS", "state": "IMPLEMENTED",
                 "required_execution": bool(g.get("required_execution", True)),
                 "attempted": True, "executed": 1}
                for g in spec["gates"]]
        got = module.overall(spec, rows)
        self.assertNotEqual(
            got["status"], "PASS",
            "every implemented gate passed and the aggregate still reached "
            "PASS, so a declared PROCESS_ONLY gate stopped holding it off")
        self.assertEqual(got["status"], "NEEDS_REVIEW")

    def test_four_states_and_exit_mapping_are_unchanged(self):
        path = os.path.join(REPO_ROOT, "scripts", "release_gate.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        for name in ("PASS", "FAIL_REGRESSION", "BLOCKED_INFRA",
                     "NEEDS_REVIEW"):
            self.assertRegex(source, rf'{name}\s*=\s*"{name}"',
                             "the four overall states must not change")
        for name, code in (("PASS_OVERALL", 0), ("FAIL_REGRESSION", 2),
                           ("BLOCKED_INFRA", 3), ("NEEDS_REVIEW", 4)):
            self.assertRegex(source, rf"{name}:\s*{code}\b",
                             f"{name} must remain exit {code}")


class TestLintFailureClassification(unittest.TestCase):
    """The mapping ruled in the contract, exercised through the real seam."""

    def _classify(self, **kwargs):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rg", os.path.join(REPO_ROOT, "scripts", "release_gate.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.classify_lint(**kwargs)

    def test_clean_run_is_a_pass(self):
        outcome, _ = self._classify(exit_code=0, stdout="All checks passed!",
                                   stderr="")
        self.assertEqual(outcome, "PASS")

    def test_violations_are_a_regression(self):
        outcome, detail = self._classify(
            exit_code=1,
            stdout="tests/unit/x.py:1:1: UP031 Use format specifiers",
            stderr="")
        self.assertEqual(
            outcome, "REGRESSION",
            "ruff ran and found violations. That is a conclusion about code "
            "content, so it is REGRESSION.")
        self.assertIn("UP031", detail,
                      "the detail must name what failed, or the row says "
                      "REGRESSION and explains nothing")

    def test_missing_ruff_is_infrastructure(self):
        outcome, detail = self._classify(exit_code=None, stdout="", stderr="",
                                         launch_error="No module named ruff")
        self.assertEqual(
            outcome, "INFRASTRUCTURE_FAILURE",
            "lint could not run. Recording that as anything else states a "
            "conclusion about code content that was never reached.")
        self.assertIn("ruff", detail)

    def test_broken_config_is_infrastructure(self):
        outcome, _ = self._classify(exit_code=2, stdout="",
                                    stderr="Failed to parse pyproject.toml")
        self.assertEqual(
            outcome, "INFRASTRUCTURE_FAILURE",
            "a config that will not parse means the gate is broken, not that "
            "the code is wrong.")

    def test_unexpected_exit_is_fail_closed(self):
        for code in (2, 3, 127):
            outcome, _ = self._classify(exit_code=code, stdout="", stderr="?")
            self.assertEqual(
                outcome, "INFRASTRUCTURE_FAILURE",
                f"unexpected ruff exit {code} must not be read as a verdict "
                "about the code. Only 0 means clean and 1 means violations.")

    def test_violations_outrank_infrastructure_overall(self):
        """The acceptance case: a real violation is not swallowed.

        Today the integration gate fails INFRASTRUCTURE_FAILURE, giving
        BLOCKED_INFRA. A genuine lint violation must be able to lift that to
        FAIL_REGRESSION without the infrastructure row being erased.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rg", os.path.join(REPO_ROOT, "scripts", "release_gate.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with open(os.path.join(REPO_ROOT, "release-gates.json"),
                  encoding="utf-8") as fh:
            spec = json.load(fh)

        def row(gate, outcome):
            return {"gate": gate, "outcome": outcome, "state": "IMPLEMENTED",
                    "required_execution": True, "attempted": True,
                    "executed": 1}

        cases = [
            ([row("integration", "INFRASTRUCTURE_FAILURE"),
              row("unit", "REGRESSION")], "FAIL_REGRESSION", 2),
            ([row("integration", "INFRASTRUCTURE_FAILURE"),
              row("unit", "PASS")], "BLOCKED_INFRA", 3),
            ([row("integration", "INFRASTRUCTURE_FAILURE"),
              row("unit", "INFRASTRUCTURE_FAILURE")], "BLOCKED_INFRA", 3),
        ]
        for results, status, code in cases:
            got = module.overall(spec, results)
            self.assertEqual(got["status"], status,
                             f"overall for {[r['outcome'] for r in results]}")
            self.assertEqual(got["exit_code"], code)


class TestLintIsFailClosedWhenItCannotRun(unittest.TestCase):
    """The wiring, not the mapping.

    Revert-only found this hole. Testing classify_lint on its own proved the
    table was right while saying nothing about whether run_gate acted on it. A
    precondition that returns INFRA and is then ignored is fail-open, and the
    ruled requirement -- ruff not executed must fail closed as INFRA, never
    default to PASS -- is exactly about that act, not about the label.

    So this drives run_gate with lint unable to execute and asserts the gate's
    own command never ran. Checking the sentinel file rather than the verdict
    alone is deliberate: a verdict can be right by accident, a side effect
    cannot.
    """

    def _run_gate(self, gate):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rg", os.path.join(REPO_ROOT, "scripts", "release_gate.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.run_gate(gate, REPO_ROOT, timeout=120)

    def test_lint_that_cannot_run_stops_the_gate(self):
        with tempfile.TemporaryDirectory() as workdir:
            sentinel = os.path.join(workdir, "gate-ran.txt")
            gate = {
                "id": "probe", "state": "IMPLEMENTED",
                "required_execution": True, "blocking": True,
                # A module that does not exist: ruff cannot be launched.
                "lint": {"command": [sys.executable,
                                     "-m", "ruff_is_not_installed_here",
                                     "check"]},
                "command": [sys.executable, "-c",
                            f"open({sentinel!r}, 'w').write('ran')"],
            }
            row = self._run_gate(gate)
            self.assertEqual(
                row["outcome"], "INFRASTRUCTURE_FAILURE",
                "lint could not execute, so the gate has no conclusion. "
                "Anything else states one.")
            self.assertFalse(
                os.path.exists(sentinel),
                "the gate's own command ran even though its lint precondition "
                "failed to execute. The verdict happened to be right; the "
                "behaviour was fail-open.")

    def test_lint_violation_also_stops_the_gate(self):
        with tempfile.TemporaryDirectory() as workdir:
            sentinel = os.path.join(workdir, "gate-ran.txt")
            gate = {
                "id": "probe", "state": "IMPLEMENTED",
                "required_execution": True, "blocking": True,
                "lint": {"command": [sys.executable, "-c",
                                     "import sys; sys.stderr.write('x:1:1: "
                                     "E501 long line\\n'); sys.exit(1)"]},
                "command": [sys.executable, "-c",
                            f"open({sentinel!r}, 'w').write('ran')"],
            }
            row = self._run_gate(gate)
            self.assertEqual(row["outcome"], "REGRESSION")
            self.assertFalse(
                os.path.exists(sentinel),
                "the gate's own command ran despite a lint violation; the "
                "tests could not change the verdict, so spending the run on "
                "them only delays the report")

    def test_a_clean_lint_lets_the_gate_run(self):
        """The other direction: fail-closed must not become always-closed."""
        with tempfile.TemporaryDirectory() as workdir:
            sentinel = os.path.join(workdir, "gate-ran.txt")
            gate = {
                "id": "probe", "state": "IMPLEMENTED",
                "required_execution": True, "blocking": True,
                "lint": {"command": [sys.executable, "-c", "pass"]},
                "command": [sys.executable, "-c",
                            f"open({sentinel!r}, 'w').write('ran')"],
            }
            row = self._run_gate(gate)
            self.assertTrue(os.path.exists(sentinel),
                            "a clean lint must let the gate proceed, "
                            "otherwise the precondition is a gate that "
                            "always fails")
            self.assertNotEqual(row["outcome"], "INFRASTRUCTURE_FAILURE")


class TestLintIsVisibleInTheReport(unittest.TestCase):
    """A verdict with no visible cause is not a verdict a reader can act on.

    build_report rebuilds each gate row from a whitelist. The lint sub-record
    was not on it, so a unit REGRESSION caused by lint reached the report with
    only a detail string and nothing naming the check. The test result was
    added to that same whitelist for exactly this reason; lint belongs there
    for the same reason.
    """

    def test_build_report_carries_the_lint_sub_record(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cp", os.path.join(REPO_ROOT, "scripts", "ci_pipeline.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        gate_report = {"gates": [{
            "gate": "unit", "state": "IMPLEMENTED", "outcome": "REGRESSION",
            "required_execution": True, "attempted": True, "executed": 0,
            "exit_code": None,
            "lint": {"command": ["ruff", "check"], "outcome": "REGRESSION",
                     "exit_code": 1, "detail": "1 violation line(s)"},
        }]}
        report = module.build_report({}, 2, gate_report, [])
        row = next(g for g in report["gates"] if g["gate"] == "unit")
        self.assertIsNotNone(
            row.get("lint"),
            "the pipeline report drops the lint sub-record, so the row reads "
            "REGRESSION without naming the check that produced it")
        self.assertEqual(row["lint"]["exit_code"], 1)
        self.assertEqual(row["lint"]["outcome"], "REGRESSION")


class TestNoqaGovernance(unittest.TestCase):
    """Only the four rules already ruled. Who approves, and when a date has
    passed, are explicitly undefined and not guessed at here."""

    def _suppressions(self):
        """Yield (path, line, comment) for every real suppression.

        Uses tokenize so only COMMENT tokens count. A raw line scan also
        matched the literal "# noqa" inside this file's own regex and
        docstrings, which made the control fail on itself.
        """
        for path, rel in _python_files():
            with open(path, "rb") as fh:
                try:
                    tokens = list(tokenize.tokenize(fh.readline))
                except (tokenize.TokenError, SyntaxError, UnicodeDecodeError):
                    continue
            for token in tokens:
                if token.type != tokenize.COMMENT:
                    continue
                if "noqa" not in token.string.lower():
                    continue
                yield rel, token.start[0], token.string.strip()

    def test_there_is_something_to_check(self):
        self.assertIsNotNone(next(iter(self._suppressions()), None),
                             "expected at least one suppression to govern")

    def test_no_bare_noqa(self):
        for rel, number, line in self._suppressions():
            match = NOQA.search(line)
            self.assertIsNotNone(match,
                                 f"{rel}:{number} has 'noqa' in a form this "
                                 f"contract does not define: {line.strip()!r}")
            self.assertIsNotNone(
                match.group("codes"),
                f"{rel}:{number} is a bare '# noqa'. A blanket suppression "
                "silences every rule on the line including the ones that were "
                "not the problem.")

    def test_every_suppression_states_a_reason(self):
        for rel, number, line in self._suppressions():
            match = NOQA.search(line)
            if match is None:
                continue
            reason = (match.group("reason") or "").strip()
            self.assertTrue(
                reason,
                f"{rel}:{number} suppresses {match.group('codes').lstrip(':').strip()} without "
                "saying why. A reason is the only thing that distinguishes a "
                "considered suppression from a way to make the gate quiet.")

    def test_temporary_suppression_carries_an_expiry_date(self):
        for rel, number, line in self._suppressions():
            match = NOQA.search(line)
            if match is None:
                continue
            reason = (match.group("reason") or "").strip()
            if not any(marker in reason.lower() for marker in TEMPORARY):
                continue
            self.assertRegex(
                reason, DATE,
                f"{rel}:{number} reads as temporary ('{reason[:48]}') but "
                "carries no date. Whether the date has passed is undefined "
                "here, but a temporary claim with no date is not a claim "
                "anyone can act on.")


if __name__ == "__main__":
    unittest.main()
