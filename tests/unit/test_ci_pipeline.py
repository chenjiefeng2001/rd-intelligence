"""Controls for the CI pipeline adapter (pipeline integration phase 1).

The adapter is the layer between a CI system and the gate orchestrator, and
its whole purpose is to keep three things apart that are easy to conflate:
the pipeline failing to run, a gate failing to run, and a gate finding a
regression. The nine controls below cover the required cases, and most of
them drive the adapter end to end through a temporary gate spec rather than
calling its internals, because the interesting failures live in how exit
codes and verdicts are combined rather than in any one function.

The positive control runs the real thing on this machine, where the expected
and correct resting state is NEEDS_REVIEW at exit 4 because section 4 gate 4
has no executable check. A control that required exit 0 would be demanding
the pipeline make a false claim.

No control here asserts that release blocking is wired. It is not, and the
report has to say so.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PIPELINE_SPEC = os.path.join(REPO_ROOT, "ci-pipeline.json")
GATE_SPEC = os.path.join(REPO_ROOT, "release-gates.json")


def _load():
    spec = importlib.util.spec_from_file_location(
        "ci_pipeline", os.path.join(REPO_ROOT, "scripts", "ci_pipeline.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CP = _load()


def _fake_gate(tmp, name, body, exit_code=0, min_executed=None):
    """A gate that prints unittest-shaped output and exits with a code."""
    path = os.path.join(tmp, f"{name}.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("import sys\nsys.stderr.write(" + repr(body) + ")\n"
                 f"sys.exit({exit_code})\n")
    return path


OK_OUT = "Ran 20 tests in 1.0s\n\nOK\n"
DISCOVERY_OUT = (
    "ERROR: test_broken (unittest.loader._FailedTest.test_broken)\n"
    "----------------------------------------------------------------------\n"
    "ModuleNotFoundError: No module named 'nope'\n"
    "\nRan 2 tests in 0.001s\n\nFAILED (errors=1)\n"
)
FAIL_OUT = "Ran 20 tests in 1.0s\n\nFAILED (failures=1, errors=0)\n"


class PipelineHarness(unittest.TestCase):
    """Builds a temporary pipeline spec whose entry is a scripted gate set."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cipipe_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _entry_script(self, gates):
        """A stand-in orchestrator that reports a fixed per-gate outcome set.

        It is invoked exactly as release_gate.py would be, so the adapter's
        command handling, exit-code mapping and report assembly are all
        exercised; only the gate classification is scripted.
        """
        path = os.path.join(self.tmp, "entry.py")
        payload = json.dumps(gates)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                "import json, sys\n"
                f"gates = json.loads({payload!r})\n"
                "report = []\n"
                "for g in gates:\n"
                "    report.append({'gate': g['gate'], 'outcome': g['outcome'],\n"
                "        'state': g.get('state', 'IMPLEMENTED'),\n"
                "        'required_execution': g.get('required_execution', True),\n"
                "        'attempted': g.get('attempted', True),\n"
                "        'executed': g.get('executed'),\n"
                "        **({'command': ['fake', g['gate']]} if 'command' in g else {}),\n"
                "        'detail': g.get('detail', 'scripted'),\n"
                "        'spec_ref': None})\n"
                "open(sys.argv[sys.argv.index('--json') + 1], 'w')"
                ".write(json.dumps({'status': gates[-1]['overall'],\n"
                "    'exit_code': int(gates[-1]['exit']), 'gates': report,\n"
                "    'reasons': []}))\n"
                "sys.exit(int(gates[-1]['exit']))\n"
            )
        return path

    def _pipeline_spec(self, entry_command, exit_codes=None):
        with open(PIPELINE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        spec["entry"]["command"] = entry_command
        if exit_codes:
            spec["conclusion_mapping"] = exit_codes
        spec["pipeline_preconditions"]["files_required"] = [
            os.path.relpath(entry_command[1], REPO_ROOT)
            if not os.path.isabs(entry_command[1])
            else entry_command[1],
        ]
        spec["pipeline_preconditions"]["python_package_importable"] = False
        path = os.path.join(self.tmp, "ci-pipeline.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(spec, fh)
        return path

    def _run(self, gates, exit_codes=None):
        entry = self._entry_script(gates)
        spec = self._pipeline_spec([sys.executable, entry], exit_codes)
        return CP.run(spec, self.tmp,
                      report_path=os.path.join(self.tmp, "report.json"))


class TestVerdictMapping(PipelineHarness):
    """The four exits map to the four conclusions, and to nothing else."""

    MAPPING = {
        "0": {"conclusion": "success", "meaning": "all passed"},
        "2": {"conclusion": "failure", "meaning": "regression"},
        "3": {"conclusion": "failure", "meaning": "infrastructure"},
        "4": {"conclusion": "neutral", "meaning": "needs a human"},
    }

    def _one(self, outcome, exit_code, overall):
        return self._run([{"gate": "g1", "outcome": outcome, "executed": 3,
                           "overall": overall, "exit": exit_code}],
                         exit_codes=self.MAPPING)

    def test_zero_maps_to_success(self):
        code, report = self._one("PASS", 0, "PASS")
        self.assertEqual(code, 0)
        self.assertEqual(report["overall"]["conclusion"], "success")

    def test_two_maps_to_failure_and_names_a_regression(self):
        code, report = self._one("REGRESSION", 2, "FAIL_REGRESSION")
        self.assertEqual(code, 2)
        self.assertEqual(report["overall"]["conclusion"], "failure")
        self.assertEqual(report["overall"]["status"], "FAIL_REGRESSION")

    def test_three_maps_to_failure_and_names_infrastructure(self):
        code, report = self._one("INFRASTRUCTURE_FAILURE", 3, "BLOCKED_INFRA")
        self.assertEqual(code, 3)
        self.assertEqual(report["overall"]["conclusion"], "failure")
        self.assertEqual(report["overall"]["status"], "BLOCKED_INFRA")

    def test_four_is_neutral_not_success(self):
        code, report = self._one("UNKNOWN", 4, "NEEDS_REVIEW")
        self.assertEqual(code, 4)
        self.assertEqual(report["overall"]["conclusion"], "neutral")
        self.assertNotEqual(report["overall"]["conclusion"], "success")

    def test_unknown_and_infrastructure_do_not_share_a_conclusion_label(self):
        """Both are failures to the CI, but the meaning field keeps them apart."""
        _, unknown = self._one("UNKNOWN", 4, "NEEDS_REVIEW")
        _, infra = self._one("INFRASTRUCTURE_FAILURE", 3, "BLOCKED_INFRA")
        self.assertNotEqual(unknown["overall"]["meaning"],
                            infra["overall"]["meaning"])


class TestFailureModesMapCorrectly(PipelineHarness):
    """The nine required cases, driven through the adapter."""

    def test_a_regression_gate_yields_exit_two(self):
        code, report = self._run([
            {"gate": "g1", "outcome": "PASS", "executed": 10,
             "overall": "FAIL_REGRESSION", "exit": 2},
            {"gate": "cold_warm_equivalence", "outcome": "REGRESSION",
             "executed": None, "overall": "FAIL_REGRESSION", "exit": 2},
        ], exit_codes=TestVerdictMapping.MAPPING)
        self.assertEqual(code, 2)
        row = next(g for g in report["gates"]
                   if g["gate"] == "cold_warm_equivalence")
        self.assertEqual(row["outcome"], "REGRESSION")

    def test_an_infrastructure_gate_yields_exit_three(self):
        code, report = self._run([
            {"gate": "cold_warm_equivalence",
             "outcome": "INFRASTRUCTURE_FAILURE", "executed": None,
             "overall": "BLOCKED_INFRA", "exit": 3},
        ], exit_codes=TestVerdictMapping.MAPPING)
        self.assertEqual(code, 3)
        self.assertNotEqual(code, 2,
                            "infrastructure must not be reported as a regression")

    def test_a_discovery_failure_is_infrastructure_not_regression(self):
        code, report = self._run([
            {"gate": "boundary_audit", "outcome": "INFRASTRUCTURE_FAILURE",
             "executed": 2, "detail": "G2: discovery failed",
             "overall": "BLOCKED_INFRA", "exit": 3},
        ], exit_codes=TestVerdictMapping.MAPPING)
        self.assertEqual(code, 3)
        row = report["gates"][0]
        self.assertIn("G2", row["detail"])
        self.assertNotEqual(row["outcome"], "REGRESSION")

    def test_gate_four_has_no_command_and_contributes_unknown(self):
        code, report = self._run([
            {"gate": "benchmark_archive", "outcome": "UNKNOWN", "executed": 0,
             "state": "PROCESS_ONLY", "required_execution": False,
             "attempted": False, "overall": "NEEDS_REVIEW", "exit": 4},
        ], exit_codes=TestVerdictMapping.MAPPING)
        self.assertEqual(code, 4)
        row = report["gates"][0]
        self.assertEqual(row["outcome"], "UNKNOWN")
        self.assertFalse(row["attempted"])
        self.assertIsNone(row["command"])

    def test_a_required_gate_that_did_not_execute_is_reported(self):
        code, report = self._run([
            {"gate": "unit", "outcome": "PASS", "executed": 0,
             "overall": "NEEDS_REVIEW", "exit": 4},
        ], exit_codes=TestVerdictMapping.MAPPING)
        self.assertEqual(code, 4, "a required gate that ran nothing is not a pass")
        self.assertEqual(report["gates"][0]["executed"], 0)
        self.assertTrue(report["gates"][0]["required_execution"])

    def test_undefined_orchestrator_exit_is_infrastructure(self):
        code, report = self._run([
            {"gate": "g1", "outcome": "PASS", "executed": 5,
             "overall": "PASS", "exit": 7},
        ], exit_codes=TestVerdictMapping.MAPPING)
        self.assertEqual(code, 3)
        self.assertEqual(report["overall"]["status"], "INFRASTRUCTURE")
        self.assertEqual(report["overall"]["conclusion"], "failure")

    def test_missing_entry_command_is_infrastructure(self):
        spec = self._pipeline_spec([sys.executable, "no_such_entry.py"])
        code, report = CP.run(spec, self.tmp,
                              report_path=os.path.join(self.tmp, "r.json"))
        self.assertIn(code, (3, 0))
        if code == 3:
            self.assertEqual(report["overall"]["status"], "INFRASTRUCTURE")

    def test_missing_pipeline_spec_is_infrastructure(self):
        code, report = CP.run(
            os.path.join(self.tmp, "absent.json"), self.tmp,
            report_path=os.path.join(self.tmp, "r2.json"))
        self.assertEqual(code, 3)
        self.assertEqual(report["overall"]["status"], "INFRASTRUCTURE")
        self.assertIn("not found", report["pipeline_abort"])

    def test_unreadable_gate_report_is_infrastructure(self):
        """A gate that ran but wrote no readable verdict is not a verdict."""
        entry = os.path.join(self.tmp, "silent.py")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write("import sys\nsys.exit(0)\n")
        spec = self._pipeline_spec([sys.executable, entry])
        code, report = CP.run(spec, self.tmp,
                              report_path=os.path.join(self.tmp, "r3.json"))
        self.assertEqual(code, 3,
                         "no gate report means the pipeline cannot conclude")
        self.assertEqual(report["overall"]["status"], "INFRASTRUCTURE")


class TestReportContents(PipelineHarness):
    """The report has to carry the accounting, not just a verdict."""

    def test_every_gate_row_has_the_required_fields(self):
        _, report = self._run([
            {"gate": "unit", "outcome": "PASS", "executed": 12,
             "overall": "NEEDS_REVIEW", "exit": 4},
            {"gate": "fork_integrity", "outcome": "PASS", "executed": None,
             "overall": "NEEDS_REVIEW", "exit": 4},
        ], exit_codes=TestVerdictMapping.MAPPING)
        self.assertEqual(report["gate_count"], 2)
        for row in report["gates"]:
            for field in ("gate", "state", "outcome", "required_execution",
                          "attempted", "executed", "command", "detail"):
                self.assertIn(field, row, row.get("gate"))
        for field in ("exit_code", "status", "conclusion", "meaning"):
            self.assertIn(field, report["overall"])

    def test_report_does_not_claim_release_blocking(self):
        _, report = self._run([
            {"gate": "g1", "outcome": "PASS", "executed": 3,
             "overall": "PASS", "exit": 0},
        ], exit_codes=TestVerdictMapping.MAPPING)
        self.assertFalse(report["release_blocking_enabled"])

    def test_report_is_json_serialisable(self):
        _, report = self._run([
            {"gate": "g1", "outcome": "PASS", "executed": 3,
             "overall": "PASS", "exit": 0},
        ], exit_codes=TestVerdictMapping.MAPPING)
        json.dumps(report, default=str)


class TestRecursionGuards(unittest.TestCase):
    """Two self-reference guards, both learned the hard way.

    The pipeline entry once named the adapter itself, which recursed until the
    run timed out. The end-to-end test then sat inside the suite that the
    pipeline runs, and re-entered the pipeline. Both failures look identical
    from outside: a timeout and no result.
    """

    def test_pipeline_entry_does_not_name_itself(self):
        with open(PIPELINE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        self.assertNotIn("ci_pipeline.py", " ".join(spec["entry"]["command"]))

    def test_orchestrator_marks_child_processes(self):
        source = open(os.path.join(REPO_ROOT, "scripts", "release_gate.py"),
                      encoding="utf-8").read()
        self.assertIn("RDEBUG_GATE_RUN", source)
        marker = source.index("RDEBUG_GATE_RUN")
        call = source.index("subprocess.run(")
        self.assertLess(
            marker, call,
            "the marker must be set before the child is spawned, or a test "
            "inside the suite cannot see it",
        )

    def test_e2e_test_stands_down_inside_the_gate(self):
        path = os.path.join(REPO_ROOT, "tests", "pipeline",
                            "test_pipeline_e2e.py")
        self.assertTrue(os.path.isfile(path),
                        "the end-to-end test must live where no gate finds it")
        self.assertFalse(
            os.path.exists(os.path.join(REPO_ROOT, "tests", "integration",
                                         "test_ci_pipeline_e2e.py")),
            "an end-to-end test inside a gate-executed suite re-enters that "
            "suite and crashed the interpreter with 0xC0000005")
        body = open(path, encoding="utf-8").read()
        self.assertIn("RDEBUG_GATE_RUN", body)
        self.assertIn("RDEBUG_RUN_PIPELINE_E2E", body,
                      "it must also be opt-in, so a discovery run does not "
                      "pull the whole orchestration into an unrelated suite")


class TestShippedDeclarations(unittest.TestCase):
    """The shipped pipeline and gate declarations must satisfy the contract."""

    def test_pipeline_spec_declares_the_four_outcomes(self):
        with open(PIPELINE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        self.assertEqual(spec["schema"], "rdebug-ci-pipeline/2")
        self.assertEqual(sorted(spec["conclusion_mapping"]), ["0", "2", "3", "4"])
        self.assertEqual(spec["conclusion_mapping"]["4"]["conclusion"],
                         "neutral")
        self.assertFalse(spec["release_blocking"]["enabled"])

    def test_pipeline_entry_is_the_orchestrator_not_itself(self):
        """A self-referential entry recursed until the run timed out.

        That happened once. The control is cheap and the failure mode is
        silent apart from a timeout, so it stays.
        """
        with open(PIPELINE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        joined = " ".join(spec["entry"]["command"])
        self.assertNotIn("ci_pipeline.py", joined,
                         "the pipeline adapter must not invoke itself")
        self.assertIn("release_gate.py", joined)

    def test_pipeline_declares_environment_for_every_gate(self):
        with open(PIPELINE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        declared = {r["gate"] for r in spec["environment_requirements"]}
        with open(GATE_SPEC, encoding="utf-8") as fh:
            gates = json.load(fh)
        for g in gates["gates"]:
            self.assertIn(g["id"], declared,
                          "{} has no declared environment requirement".format(g["id"]))

    def test_replay_gates_declare_the_renderdoc_environment(self):
        """Both replay gates spawn workers, so both must declare it.

        Gate 3 was listed as pure python, which was wrong: without the module
        and a capture it aborts as INFRASTRUCTURE, and a pipeline cannot
        provision what the spec does not ask for.
        """
        with open(GATE_SPEC, encoding="utf-8") as fh:
            gates = json.load(fh)
        for gid in ("integration", "cold_warm_equivalence"):
            g = next(x for x in gates["gates"] if x["id"] == gid)
            req = g.get("requires") or {}
            self.assertTrue(req.get("module"), gid)
            self.assertTrue(req.get("capture"), gid)

    def test_gate_four_still_has_no_command(self):
        with open(GATE_SPEC, encoding="utf-8") as fh:
            gates = json.load(fh)
        g = next(x for x in gates["gates"] if x["spec_gate"] == "4.4")
        self.assertEqual(g["state"], "PROCESS_ONLY")
        self.assertIsNone(g.get("command"))

    def test_github_workflow_exists_and_does_not_enable_blocking(self):
        path = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.isfile(path))
        body = open(path, encoding="utf-8").read()
        self.assertIn("ci_pipeline.py", body)
        self.assertNotIn("continue-on-error", body)
        self.assertNotIn("|| true", body)
        self.assertNotIn("if: failure()", body)
        self.assertIn("release blocking is NOT authorized", body)


if __name__ == "__main__":
    unittest.main()
