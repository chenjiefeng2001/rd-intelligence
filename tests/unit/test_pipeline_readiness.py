"""Controls for the pipeline readiness contract (DESIGN_SPEC 4.2).

Written before the implementation, per the established order, so they could
be shown to fail against a missing module and pass against the real one.

The contract exists because a gate that cannot run and a gate that found a
problem must never be reported the same way. The negative controls below are
the whole point of it: each one names a way "did not run" could be mistaken
for "passed", and each must be caught.

Two of the five negative controls are aimed at the report rather than the
classification, because a correct classification in an incomplete report is
still misreadable. A report without an environment section cannot tell a
reader whether the checks ran on a capable machine, and a report whose exit
code disagrees with its own state cannot be trusted at all.
"""

import importlib
import importlib.util
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PIPELINE_SPEC = os.path.join(REPO_ROOT, "ci-pipeline.json")
GATE_SPEC = os.path.join(REPO_ROOT, "release-gates.json")


def _load():
    spec = importlib.util.spec_from_file_location(
        "pipeline_readiness",
        os.path.join(REPO_ROOT, "scripts", "pipeline_readiness.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load()


def _load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "ci_pipeline_under_test",
        os.path.join(REPO_ROOT, "scripts", "ci_pipeline.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load_pipeline()
if REPO_ROOT + os.sep + "scripts" not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


def _readiness_source():
    with open(os.path.join(REPO_ROOT, "scripts", "pipeline_readiness.py"),
              encoding="utf-8") as handle:
        return handle.read()


def _spawned_commands():
    """Every argument list handed to subprocess.run, as token lists.

    The commands are list literals, so a scan for bare string constants finds
    nothing. Read the call arguments instead.
    """
    import ast

    tree = ast.parse(_readiness_source())
    commands = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name not in ("run", "check_output", "check_call", "Popen"):
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.List):
                tokens = [e.value for e in arg.elts
                          if isinstance(e, ast.Constant)
                          and isinstance(e.value, str)]
                if tokens:
                    commands.append(tokens)
    return commands


FULL_ENVIRONMENT = {
    "renderdoc": {"fork_present": True, "module_importable": True,
                  "version": "1.46", "commit": "b7f1554fe"},
    "gpu": {"present": True, "driver": "D3D11", "replay_supported": True},
    "corpus": {"captures_present": True, "manifest_match": True,
               "count": 14},
    "runtime": {"python_ok": True, "dependencies_ok": True},
}


class TestCapabilityDeclaration(unittest.TestCase):
    """4.2.1: the four capability classes, and they are prerequisites."""

    def test_report_has_all_four_capability_classes(self):
        env = R.probe_environment(REPO_ROOT, {})
        for key in ("renderdoc", "gpu", "corpus", "runtime"):
            self.assertIn(key, env, key)

    def test_renderdoc_declaration_carries_identity(self):
        env = R.probe_environment(REPO_ROOT, {})
        rd = env["renderdoc"]
        for key in ("fork_present", "module_importable", "commit"):
            self.assertIn(key, rd)

    def test_corpus_declaration_checks_manifest_not_just_existence(self):
        env = R.probe_environment(REPO_ROOT, {})
        self.assertIn("manifest_match", env["corpus"])

    def test_probe_records_current_facts_without_asserting_them(self):
        """4.2.5: the current environment is evidence, not a contract premise.

        This machine has no tracked capture and is expected to have no
        usable GPU here. The probe must report those as observed state. What
        it must not do is encode them as the assumption that they are always
        true, so a later environment that does have them is not declared
        broken.
        """
        env = R.probe_environment(REPO_ROOT, {})
        corpus = env["corpus"]
        self.assertIsInstance(corpus["captures_present"], bool)
        self.assertIsInstance(env["gpu"]["present"], bool)
        # The probe takes its inputs, so it can be pointed at an environment
        # that does have them; nothing here is hardcoded to False.
        source = open(os.path.join(REPO_ROOT, "scripts",
                                   "pipeline_readiness.py"),
                      encoding="utf-8").read()
        self.assertNotIn('"captures_present": False', source)
        self.assertNotIn('"present": False', source)


class TestFourStateClassification(unittest.TestCase):
    """4.2.2: the prohibited mappings."""

    def test_missing_required_capability_is_infrastructure(self):
        v = R.classify_missing(["renderdoc.module_importable"],
                               required=True)
        self.assertEqual(v, R.INFRA)

    def test_missing_optional_capability_is_unknown(self):
        v = R.classify_missing(["gpu.driver"], required=False)
        self.assertEqual(v, R.UNKNOWN)
        self.assertNotEqual(v, R.INFRA)

    def test_missing_capture_is_never_regression(self):
        for required in (True, False):
            v = R.classify_missing(["corpus.captures_present"],
                                   required=required)
            self.assertNotEqual(v, R.REGRESSION,
                                "a missing capture is not an observation "
                                "about rendering results")

    def test_missing_gpu_for_a_required_gate_is_not_unknown(self):
        v = R.classify_missing(["gpu.present"], required=True)
        self.assertNotEqual(v, R.UNKNOWN,
                            "a required gate that could not run is an "
                            "execution failure, not an inability to conclude")
        self.assertEqual(v, R.INFRA)

    def test_unconfigured_runner_is_never_pass(self):
        v = R.classify_missing(["runtime.python_ok"], required=True)
        self.assertNotEqual(v, R.PASS)

    def test_nothing_missing_and_no_failure_is_pass(self):
        v = R.classify_missing([], required=True, attempted=True, executed=3)
        self.assertEqual(v, R.PASS)

    def test_executed_and_failed_reports_the_failure_type(self):
        v = R.classify_missing([], required=True, attempted=True,
                               executed=3, failure_type="regression")
        self.assertEqual(v, R.REGRESSION)
        v = R.classify_missing([], required=True, attempted=True,
                               executed=3, failure_type="infrastructure")
        self.assertEqual(v, R.INFRA)

    def test_required_but_not_executed_is_infrastructure(self):
        v = R.classify_missing([], required=True, attempted=False,
                               executed=0)
        self.assertEqual(v, R.INFRA)

    def test_optional_and_not_executed_is_unknown(self):
        v = R.classify_missing([], required=False, attempted=False,
                               executed=0)
        self.assertEqual(v, R.UNKNOWN)


class TestExecutionIsNotInferredFromCounts(unittest.TestCase):
    """4.2.3: skipped counts, test counts and absence of failures prove nothing."""

    def test_zero_tests_with_no_recorded_failure_is_not_pass(self):
        v = R.classify_missing([], required=True, attempted=True, executed=0)
        self.assertNotEqual(v, R.PASS)

    def test_execution_is_not_inferred_from_a_test_count(self):
        """A declared total is not evidence that anything ran."""
        with self.assertRaises(R.ReadinessViolation):
            R.validate_report({
                "environment": FULL_ENVIRONMENT,
                "gates": [{"gate_id": "g", "required_execution": True,
                           "attempted": False, "executed": 0,
                           "state": "PASS", "reason": "",
                           "missing_requirements": []}],
                "overall": {"state": "PASS", "exit_code": 0},
            })

    def test_missing_requirements_must_be_listed_when_a_gate_did_not_run(self):
        with self.assertRaises(R.ReadinessViolation):
            R.validate_report({
                "environment": FULL_ENVIRONMENT,
                "gates": [{"gate_id": "g", "required_execution": True,
                           "attempted": False, "executed": 0,
                           "state": "INFRASTRUCTURE_FAILURE",
                           "reason": "no prerequisites recorded",
                           "missing_requirements": []}],
                "overall": {"state": "BLOCKED_INFRA", "exit_code": 3},
            })


class TestReportValidation(unittest.TestCase):
    """4.2.4 invariants V1 to V3."""

    def _report(self, **over):
        report = {
            "environment": dict(FULL_ENVIRONMENT),
            "gates": [{"gate_id": "g", "required_execution": True,
                       "attempted": True, "executed": 5, "state": "PASS",
                       "reason": "", "missing_requirements": []}],
            "overall": {"state": "PASS", "exit_code": 0},
        }
        report.update(over)
        return report

    def test_valid_report_is_accepted(self):
        R.validate_report(self._report())

    def test_missing_environment_section_is_rejected(self):
        report = self._report()
        del report["environment"]
        with self.assertRaises(R.ReadinessViolation) as ctx:
            R.validate_report(report)
        self.assertIn("environment", str(ctx.exception))

    def test_missing_gates_section_is_rejected(self):
        report = self._report()
        del report["gates"]
        with self.assertRaises(R.ReadinessViolation):
            R.validate_report(report)

    def test_missing_overall_section_is_rejected(self):
        report = self._report()
        del report["overall"]
        with self.assertRaises(R.ReadinessViolation):
            R.validate_report(report)

    def test_v2_not_attempted_but_executed_is_rejected(self):
        """The command did not run, so claiming it did is rejected."""
        report = self._report()
        report["gates"][0]["attempted"] = False
        report["gates"][0]["executed"] = 5
        with self.assertRaises(R.ReadinessViolation) as ctx:
            R.validate_report(report)
        self.assertIn("attempted", str(ctx.exception))

    def test_gate_row_missing_a_required_field_is_rejected(self):
        for field in ("gate_id", "required_execution", "attempted",
                      "executed", "state", "reason", "missing_requirements"):
            report = self._report()
            del report["gates"][0][field]
            with self.assertRaises(R.ReadinessViolation) as ctx:
                R.validate_report(report)
            self.assertIn(field, str(ctx.exception))

    def test_exit_code_must_match_overall_state(self):
        for state, code in (("PASS", 0), ("FAIL_REGRESSION", 2),
                            ("BLOCKED_INFRA", 3), ("NEEDS_REVIEW", 4)):
            report = self._report()
            report["overall"] = {"state": state, "exit_code": code}
            R.validate_report(report)

    def test_exit_code_disagreeing_with_state_is_rejected(self):
        report = self._report()
        report["overall"] = {"state": "PASS", "exit_code": 2}
        with self.assertRaises(R.ReadinessViolation) as ctx:
            R.cross_check_exit(report, 2)
        self.assertIn("state", str(ctx.exception))

    def test_process_exit_disagreeing_with_report_is_rejected(self):
        report = self._report()
        with self.assertRaises(R.ReadinessViolation) as ctx:
            R.cross_check_exit(report, 3)
        self.assertIn("exit", str(ctx.exception))

    def test_pass_overall_requires_every_required_gate_to_have_run(self):
        report = self._report()
        report["gates"].append({"gate_id": "g2", "required_execution": True,
                                "attempted": False, "executed": 0,
                                "state": "PASS", "reason": "",
                                "missing_requirements": ["corpus.captures_present"]})
        with self.assertRaises(R.ReadinessViolation) as ctx:
            R.validate_report(report)
        self.assertIn("g2", str(ctx.exception))

    def test_pass_overall_is_allowed_when_optional_gate_did_not_run(self):
        report = self._report()
        report["gates"].append({"gate_id": "g2", "required_execution": False,
                                "attempted": False, "executed": 0,
                                "state": "UNKNOWN", "reason": "process only",
                                "missing_requirements": []})
        R.validate_report(report)

    def test_capability_scope_does_not_claim_execution(self):
        """A readiness report must say it ran nothing, and mean it.

        The first implementation set attempted=True with executed=0 for gates
        the layer never touched, which is the same did-not-run confusion in
        the other direction. In capability scope nothing is attempted and the
        required-did-not-execute rule does not apply, because this report is
        not a verdict.
        """
        rows = [R.build_gate_row(
            {"id": "g", "state": "IMPLEMENTED",
             "required_execution": True, "requires": {"capabilities": []}},
            FULL_ENVIRONMENT)]
        self.assertEqual(rows[0]["attempted"], False)
        self.assertEqual(rows[0]["executed"], 0)
        self.assertEqual(rows[0]["verdict"], R.PASS)
        report = {"scope": "capability", "environment": FULL_ENVIRONMENT,
                  "gates": [{k: v for k, v in rows[0].items()
                              if k != "verdict"} | {"verdict": rows[0]["verdict"]}],
                  "overall": {"state": "PASS", "exit_code": 0}}
        R.validate_report(report, scope="capability")
        with self.assertRaises(R.ReadinessViolation):
            R.validate_report(report, scope="execution")


class TestShippedDeclarations(unittest.TestCase):
    """The shipped declarations must satisfy 4.2.3 as declared."""

    def test_every_gate_declares_required_execution(self):
        import json

        with open(GATE_SPEC, encoding="utf-8") as fh:
            gates = json.load(fh)
        for g in gates["gates"]:
            self.assertIn("required_execution", g, g["id"])
            self.assertIsInstance(g["required_execution"], bool, g["id"])

    def test_pipeline_spec_declares_every_capability_class(self):
        import json

        with open(PIPELINE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        blob = json.dumps(spec).lower()
        for token in ("renderdoc", "gpu", "corpus", "runtime"):
            self.assertIn(token, blob)

    def test_release_blocking_stays_off(self):
        import json

        with open(PIPELINE_SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        self.assertFalse(spec["release_blocking"]["enabled"])

    def test_readiness_module_provisions_nothing(self):
        """4.2.1 declares prerequisites; it must not create them.

        Checked against the parsed module, not its text. A word search was the
        first attempt and it was wrong twice over: "pip" is a substring of
        "pipeline", and the docstring sentence explaining that nothing is
        installed matched its own prohibition. Executable form is what
        matters: which modules are imported and which commands are spawned.
        """
        import ast

        tree = ast.parse(_readiness_source())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for banned in ("requests", "urllib", "ftplib", "pip", "ensurepip",
                       "setuptools", "poetry"):
            self.assertNotIn(
                banned, imported,
                "readiness declares prerequisites, it must not provision them")
        for cmd in _spawned_commands():
            for verb in ("clone", "checkout", "pull", "fetch", "install",
                         "submodule", "download"):
                self.assertNotIn(
                    verb, cmd,
                    f"readiness spawned {cmd!r}; it observes and does "
                    "not provision")

    def test_version_failure_does_not_unimport_the_module(self):
        """One failed observation must not flip an unrelated one.

        This is a regression control for a real defect. The probe read the
        RenderDoc version inside the same try block as the import check, using
        a method the Python module does not expose. The AttributeError unwound
        into module_importable, so a machine that imports RenderDoc fine was
        reported as lacking it, and the readiness report blocked the whole
        integration path on a false observation.
        """
        from rdebug.adapter import locator

        class Module:
            def GetVersionString(self):
                raise RuntimeError("no version")

        original_import = locator.import_renderdoc
        original_find = locator.find_module_dir
        try:
            locator.import_renderdoc = lambda: Module()
            locator.find_module_dir = lambda: "/somewhere/pymodules"
            env = R._probe_renderdoc(REPO_ROOT, {})
        finally:
            locator.import_renderdoc = original_import
            locator.find_module_dir = original_find
        self.assertTrue(
            env["module_importable"],
            "a version failure must not be reported as a failed import")
        self.assertIsNone(env["version"])

    def test_probe_never_reports_a_capability_it_did_not_observe(self):
        """Every declared capability must be backed by a probed class.

        Catches the class of bug above: a capability no probe populates would
        resolve to False and silently block every gate that requires it, with
        no evidence that anyone had ever looked.
        """
        observed = R.probe_environment(REPO_ROOT, {})
        for name in R.ENVIRONMENT_FIELDS:
            self.assertIsInstance(observed[name], dict,
                                  f"{name} probe did not return a mapping")
        spec = json.load(open(os.path.join(REPO_ROOT, "release-gates.json"),
                              encoding="utf-8"))
        for gate in spec["gates"]:
            for cap in (gate.get("requires") or {}).get("capabilities") or []:
                head = cap.split(".")[0]
                self.assertIn(
                    head, observed,
                    f"gate {gate['id']} declares {cap} but no {head} class is "
                    "probed, so it could only ever resolve False")
            for cap in spec["capability_names"]:
                head = cap.split(".")[0]
                self.assertIn(
                    head, observed,
                    f"{cap} is declared but no {head} class is probed, so it "
                    "could only ever resolve False")
                self.assertIsInstance(
                    R.capability_satisfied(observed, cap), bool,
                    f"{cap} did not resolve to an observation")

    def test_missing_required_capability_can_never_be_pass(self):
        """The central property, exercised against a constructed absence.

        Running this suite on a fully provisioned machine does not reach the
        missing branch at all, so an injected bug there passes silently. A
        mutation sweep made that concrete: rewording the missing-capability
        verdict to PASS left the whole suite green, because every local gate
        was runnable. The absence has to be built explicitly for the rule to
        be tested at all.
        """
        gate = {"id": "g", "state": "IMPLEMENTED", "required_execution": True,
                "requires": {"capabilities": ["renderdoc.module_importable"]}}
        lacking = {k: dict(v) if isinstance(v, dict) else v
                   for k, v in FULL_ENVIRONMENT.items()}
        lacking["renderdoc"] = dict(lacking["renderdoc"],
                                    module_importable=False)

        row = R.build_gate_row(gate, lacking)
        self.assertEqual(row["missing_requirements"],
                         ["renderdoc.module_importable"])
        self.assertEqual(row["verdict"], R.INFRA,
                         "a required gate with a missing capability must be an "
                         "infrastructure failure, never a pass")

        report = {"scope": "capability", "environment": lacking,
                  "gates": [row],
                  "overall": {"state": "BLOCKED_INFRA", "exit_code": 3}}
        R.validate_report(report, scope="capability")
        self.assertEqual(R.overall_from_rows([row], scope="capability"),
                         "BLOCKED_INFRA")

    def test_optional_missing_capability_is_unknown_not_pass(self):
        gate = {"id": "g", "state": "IMPLEMENTED", "required_execution": False,
                "requires": {"capabilities": ["gpu.present"]}}
        lacking = dict(FULL_ENVIRONMENT)
        lacking["gpu"] = dict(lacking["gpu"], present=False)
        row = R.build_gate_row(gate, lacking)
        self.assertEqual(row["verdict"], R.UNKNOWN)
        self.assertNotEqual(row["verdict"], R.PASS)

    def test_missing_capability_is_listed_not_just_refused(self):
        """A refusal without a reason is indistinguishable from a bug."""
        gate = {"id": "g", "state": "IMPLEMENTED", "required_execution": True,
                "requires": {"capabilities": ["gpu.replay_supported",
                                              "corpus.captures_present"]}}
        empty = {k: (dict(v) if isinstance(v, dict) else v)
                 for k, v in FULL_ENVIRONMENT.items()}
        empty["gpu"] = {"present": False, "driver": None,
                        "replay_supported": False}
        empty["corpus"] = {"captures_present": False, "manifest_match": False,
                           "tracked_captures": 0}
        row = R.build_gate_row(gate, empty)
        self.assertEqual(sorted(row["missing_requirements"]),
                         ["corpus.captures_present", "gpu.replay_supported"])
        for name in row["missing_requirements"]:
            self.assertIn(name, row["reason"])

    def test_declarative_gate_is_never_a_pass(self):
        """A gate with no executable check cannot pass, whatever is present.

        Second mutation the suite missed: rewording the declarative verdict to
        PASS left everything green, because the shipped environment has one
        PROCESS_ONLY gate but no control asserted its verdict. On this machine
        that gate is the only reason the overall state is NEEDS_REVIEW rather
        than PASS, so the miss was not cosmetic.
        """
        for state in ("PROCESS_ONLY", "BLOCKED", "NOT_IMPLEMENTED"):
            row = R.build_gate_row(
                {"id": "g", "state": state, "required_execution": False,
                 "requires": {"capabilities": []}}, FULL_ENVIRONMENT)
            self.assertEqual(row["verdict"], R.UNKNOWN,
                             f"a {state} gate cannot pass")
            self.assertEqual(row["executed"], 0)

        rows = [R.build_gate_row(
            {"id": "ok", "state": "IMPLEMENTED", "required_execution": True,
             "requires": {"capabilities": []}}, FULL_ENVIRONMENT),
            R.build_gate_row(
                {"id": "archive", "state": "PROCESS_ONLY",
                 "required_execution": False,
                 "requires": {"capabilities": []}}, FULL_ENVIRONMENT)]
        self.assertEqual(R.overall_from_rows(rows, scope="capability"),
                         "NEEDS_REVIEW",
                         "one unexecutable gate must keep the overall out of PASS")
        self.assertEqual(R.OVERALL_EXIT["NEEDS_REVIEW"], 4)

    def test_readiness_only_spawns_read_only_commands(self):
        """Every spawned command is a read, checked by allowlist."""
        reads = {"rev-parse", "ls-files", "status", "diff", "log", "show",
                 "cat-file"}
        commands = _spawned_commands()
        self.assertTrue(commands, "expected at least one command to inspect")
        for cmd in commands:
            self.assertEqual(cmd[0], "git",
                             f"readiness spawned {cmd!r}; the only "
                             "external reads it needs are git")
            self.assertTrue(
                set(cmd) & reads,
                f"git spawned without a read subcommand: {cmd}")
            self.assertEqual(
                len(set(cmd) & reads), 1,
                f"readiness spawned a compound git read: {cmd}")


class TestPipelineAccounting(unittest.TestCase):
    """The pipeline must not let a contradiction read as a pass.

    The observed case: the integration suite prints OK for every test and then
    dies during interpreter shutdown with 0xC0000005. The gate classifier reads
    test counts and never the exit code, so the row reads PASS. Reclassifying
    that is a gate semantics change and out of scope for this contract; failing
    to surface it is an accounting failure and inside it.
    """

    def test_pass_with_nonzero_exit_is_named(self):
        rows = [{"gate": "unit", "outcome": "PASS", "exit_code": 0},
                {"gate": "integration", "outcome": "PASS",
                 "exit_code": 3221225477}]
        found = P.accounting_inconsistencies(rows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "pass_with_nonzero_exit")
        self.assertEqual(found[0]["exit_code"], 3221225477)

    def test_clean_rows_produce_no_inconsistency(self):
        rows = [{"gate": "unit", "outcome": "PASS", "exit_code": 0},
                {"gate": "benchmark_archive", "outcome": "UNKNOWN",
                 "exit_code": 4}]
        self.assertEqual(P.accounting_inconsistencies(rows), [])

    def test_report_carries_the_inconsistency_without_changing_the_conclusion(self):
        gate_report = {"status": "NEEDS_REVIEW",
                       "gates": [{"gate": "integration", "outcome": "PASS",
                                  "executed": 63, "exit_code": 3221225477,
                                  "required_execution": True,
                                  "attempted": True}]}
        report = P.build_report({}, 4, gate_report, [])
        self.assertFalse(report["accounting_consistent"])
        self.assertEqual(report["accounting_inconsistencies"][0]["gate"],
                         "integration")
        self.assertEqual(report["overall"]["exit_code"], 4,
                         "naming the contradiction must not alter the "
                         "orchestrator exit or the conclusion mapping")

    def test_readiness_section_is_capability_only(self):
        info = P.collect_readiness(REPO_ROOT, {"gates": []})
        self.assertTrue(info["available"])
        self.assertIs(info["executes_anything"], False)
        self.assertEqual(info["scope"], "capability")
        for cls in R.ENVIRONMENT_FIELDS:
            self.assertIn(cls, info["environment"])

    def test_readiness_unavailable_is_not_a_satisfied_machine(self):
        info = P.collect_readiness(REPO_ROOT, None)
        if not info.get("available"):
            self.assertIn("error", info)
            self.assertNotIn("verdict", info)
            self.assertIn("not a statement about any gate", info["meaning"])

    def test_readiness_lists_what_each_gate_would_need(self):
        spec = {"gates": [{"id": "g", "required_execution": True,
                           "requires": {"capabilities": ["gpu.present"]}}]}
        info = P.collect_readiness(REPO_ROOT, spec)
        self.assertEqual(len(info["gates"]), 1)
        row = info["gates"][0]
        self.assertIn("missing_requirements", row)
        self.assertEqual(row["runnable"], not row["missing_requirements"])


class TestReadinessCannotForgeAVerdict(unittest.TestCase):
    """Collecting readiness must not touch a single gate outcome."""

    def test_outcomes_are_identical_with_and_without_readiness(self):
        # The contradictory row is deliberate. With only clean rows both
        # reports agree no matter what readiness does to the accounting, and a
        # mutation that suppressed the check whenever readiness data is present
        # went unnoticed for exactly that reason.
        gate_report = {"status": "NEEDS_REVIEW",
                       "gates": [{"gate": "unit", "outcome": "PASS",
                                  "executed": 251, "exit_code": 0,
                                  "required_execution": True},
                                 {"gate": "integration", "outcome": "PASS",
                                  "executed": 63, "exit_code": 3221225477,
                                  "required_execution": True}]}
        without = P.build_report({}, 4, gate_report, [])
        with_readiness = P.build_report(
            {}, 4, gate_report, [], readiness={"available": True,
                                               "executes_anything": False})
        self.assertEqual(without["gates"], with_readiness["gates"])
        self.assertEqual(without["overall"], with_readiness["overall"])
        self.assertEqual(without["accounting_inconsistencies"],
                         with_readiness["accounting_inconsistencies"])
        self.assertTrue(with_readiness["accounting_inconsistencies"],
                        "attaching readiness must not switch the accounting "
                        "check off")
        self.assertFalse(with_readiness["accounting_consistent"])

    def test_probe_exception_is_reported_not_swallowed(self):
        # Patched on the module the adapter actually resolves. This suite
        # loads its own copy of pipeline_readiness through a file spec, and
        # that copy is a different object from the one ci_pipeline imports, so
        # patching R here would prove nothing about the code under test.
        live = importlib.import_module("pipeline_readiness")
        original = live.probe_environment

        def boom(*args, **kwargs):
            raise RuntimeError("probe exploded")

        try:
            live.probe_environment = boom
            info = P.collect_readiness(REPO_ROOT, {"gates": []})
        finally:
            live.probe_environment = original
        self.assertFalse(info["available"])
        self.assertIn("probe exploded", info["error"])


if __name__ == "__main__":
    unittest.main()
