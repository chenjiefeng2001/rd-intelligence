"""CI pipeline adapter: the layer between a CI system and the gate orchestrator.

The orchestrator in release_gate.py already reduces the section 4 gates to a
four-state verdict with distinct exit codes. This adapter exists because a
pipeline needs three things the orchestrator deliberately does not do.

It separates the pipeline's own failures from the gates' verdicts. If the
spec is missing, a required script is absent, or the declared environment
cannot be provided, that is INFRASTRUCTURE. It is not a regression and it is
not a pass, and conflating the two is the failure mode this adapter is built
to prevent.

It records the evidence a reviewer needs: per gate, the state, whether
required execution applied, what was executed, the command, the result and
the overall state. "Everything executable passed" is not an acceptable
summary on its own, because it is indistinguishable from "most of it never
ran".

It maps the verdict to a CI conclusion without reinterpreting it. Exit 0 is a
success, 2 and 3 are failures for different reasons, and 4 is neutral
because unknown is not a pass and not a failure either. The mapping is
declared in ci-pipeline.json rather than embedded here, so it can be audited
as data.

It does not copy any gate logic. The fork integrity audit in particular is
invoked through the orchestrator's declared command, and this adapter never
reimplements any part of it. Duplicating that logic would create a second
copy with none of the controls the original carries, and the original's
discriminating power came from staying coupled to the frozen artifacts.

Nothing here schedules anything. Wiring a forge is a separate decision, and
release blocking is explicitly not enabled.
"""

import argparse
import json
import os
import subprocess
import sys

SCHEMA = "rdebug-ci-pipeline/2"

PASS_EXIT = 0
REGRESSION_EXIT = 2
INFRA_EXIT = 3
UNKNOWN_EXIT = 4

VALID_EXITS = (PASS_EXIT, REGRESSION_EXIT, INFRA_EXIT, UNKNOWN_EXIT)


class PipelineAbort(Exception):
    """The pipeline layer itself could not run. Never a content verdict."""

    def __init__(self, detail, missing=None):
        super().__init__(detail)
        self.detail = detail
        self.missing = list(missing or [])


def load_pipeline_spec(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise PipelineAbort(f"pipeline spec not found: {path}", [path])
    except Exception as e:  # noqa: BLE001
        raise PipelineAbort(f"pipeline spec unreadable: {e}", [path])
    if doc.get("schema") != SCHEMA:
        raise PipelineAbort(f"pipeline spec schema {doc.get('schema')!r} "
                            f"is not {SCHEMA!r}")
    return doc


def check_preconditions(spec, repo_root):
    """Everything the pipeline needs to exist before any gate is consulted.

    A miss here is INFRASTRUCTURE by construction: the pipeline could not
    start, so it has no verdict of its own to report.
    """
    missing = []
    for rel in (spec.get("pipeline_preconditions", {})
                .get("files_required") or []):
        if not os.path.exists(os.path.join(repo_root, rel)):
            missing.append(rel)
    if spec.get("pipeline_preconditions", {}).get("python_package_importable"):
        probe = subprocess.run(
            [sys.executable, "-c", "import rdebug"],
            cwd=repo_root, capture_output=True, text=True,
        )
        if probe.returncode != 0:
            missing.append("importable rdebug package")
    if missing:
        raise PipelineAbort("pipeline preconditions unmet: "
                            + ", ".join(missing), missing)
    return True


def check_environment(spec, repo_root):
    """Report which declared environment requirements the runner does not meet.

    This does not abort. A runner that cannot provide a GPU must still run
    and still produce a report; the gates themselves report
    INFRASTRUCTURE_FAILURE, and suppressing that in favour of a pipeline-level
    abort would hide which gate was the problem.
    """
    unmet = []
    for req in spec.get("environment_requirements") or []:
        gate = req.get("gate")
        for name in req.get("env") or []:
            if not os.environ.get(name):
                unmet.append({"gate": gate,
                              "requirement": f"env:{name}"})
        requires = " ".join(req.get("requires") or [])
        if "sibling RenderDoc fork checkout" in requires:
            fork = os.path.normpath(os.path.join(repo_root, "..", "renderdoc"))
            if not os.path.isdir(os.path.join(fork, ".git")):
                unmet.append({"gate": gate, "requirement": "sibling_fork"})
    return unmet


def run_orchestrator(spec, repo_root, timeout=None, extra_env=None):
    """Run release_gate.py and return its exit code plus the JSON report."""
    entry = spec.get("entry") or {}
    cmd = list(entry.get("command") or [])
    report_path = os.path.join(
        repo_root, (spec.get("artifacts") or {}).get("gate_report",
                                                     "gate_report.json"))
    cmd = cmd + ["--json", report_path]
    env = dict(os.environ)
    env.update(extra_env or {})
    proc = subprocess.run(
        cmd, cwd=repo_root, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if not os.path.isfile(report_path):
        # The orchestrator ran but produced no report. An exit code with no
        # report is not a verdict: nothing was recorded about which gates ran,
        # so the pipeline has no conclusion to forward. Reporting the raw exit
        # code here would let a silent orchestrator look like a passing build.
        raise PipelineAbort(
            f"orchestrator wrote no gate report at {report_path} "
            f"(exit {proc.returncode!r})", [report_path])
    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception as e:  # noqa: BLE001
        raise PipelineAbort(f"gate report unreadable: {e}", [report_path])
    return proc.returncode, report, proc


def accounting_inconsistencies(gates):
    """Rows whose own numbers contradict their own verdict.

    This reports, it does not reclassify. A gate row that says PASS while its
    process exit was non-zero is exactly the shape that must not reach a
    reader as a pass, and it has been observed for real here: the integration
    suite prints OK for every test and then dies during interpreter shutdown
    with 0xC0000005. The gate classifier has always looked at test counts and
    never at the exit code, so the row reads PASS.

    Changing that is a gate semantics change and is out of scope for this
    contract. Making it visible is not, so the contradiction is named here and
    surfaced at the top of the report.
    """
    out = []
    for g in gates or []:
        exit_code = g.get("exit_code")
        outcome = g.get("outcome")
        if exit_code in (None, 0):
            continue
        if outcome == "PASS":
            out.append({"gate": g.get("gate"), "kind": "pass_with_nonzero_exit",
                        "outcome": outcome, "exit_code": exit_code,
                        "meaning": "reported as passing but the process did "
                                   "not exit cleanly"})
        elif outcome not in ("INFRASTRUCTURE_FAILURE", "BLOCKED", "UNKNOWN"):
            out.append({"gate": g.get("gate"), "kind": "nonzero_exit",
                        "outcome": outcome, "exit_code": exit_code,
                        "meaning": "non-zero exit with a verdict that does "
                                   "not acknowledge it"})
    return out


def build_report(spec, exit_code, gate_report, unmet, stdout_tail="",
                 readiness=None):
    """Per-gate accounting plus the overall state, in machine-readable form."""
    mapping = spec.get("conclusion_mapping") or {}
    entry = mapping.get(str(exit_code)) or {}
    gates = []
    for g in (gate_report or {}).get("gates") or []:
        gates.append({
            "gate": g.get("gate"),
            "state": g.get("state"),
            "outcome": g.get("outcome"),
            "required_execution": g.get("required_execution"),
            "attempted": g.get("attempted"),
            "executed": g.get("executed"),
            "command": g.get("command"),
            "exit_code": g.get("exit_code"),
            "blocking": g.get("blocking"),
            "detail": g.get("detail"),
            "spec_ref": g.get("spec_ref"),
        })
    inconsistencies = accounting_inconsistencies(gates)
    return {
        "schema": "rdebug-ci-pipeline-report/2",
        "overall": {
            "exit_code": exit_code,
            "status": (gate_report or {}).get("status"),
            "conclusion": entry.get("conclusion"),
            "meaning": entry.get("meaning"),
        },
        "release_blocking_enabled": bool(
            (spec.get("release_blocking") or {}).get("enabled")
        ),
        "unmet_environment_requirements": unmet,
        "accounting_inconsistencies": inconsistencies,
        "accounting_consistent": not inconsistencies,
        "readiness": readiness,
        "gates": gates,
        "gate_count": len(gates),
        "stdout_tail": stdout_tail,
    }


def collect_readiness(repo_root, spec, report_path=None):
    """Capability declaration for this machine, from the readiness module.

    Purely additive. It runs no gate and changes no verdict; it states what the
    runner has and what each gate would therefore need. A failure to probe is
    reported as a failure to probe, not swallowed into a pass.
    """
    try:
        import pipeline_readiness as readiness_mod
    except Exception as exc:  # noqa: BLE001
        return {"available": False,
                "error": f"{type(exc).__name__}: {exc}",
                "meaning": "readiness could not be observed; this is not a "
                           "statement about any gate"}
    try:
        environment = readiness_mod.probe_environment(repo_root, os.environ)
        gates = []
        for gate in (spec or {}).get("gates") or []:
            missing = readiness_mod.missing_requirements(gate, environment)
            gates.append({"gate": gate.get("id"),
                          "missing_requirements": missing,
                          "runnable": not missing})
        return {"available": True, "scope": "capability",
                "executes_anything": False,
                "environment": environment, "gates": gates}
    except Exception as exc:  # noqa: BLE001
        return {"available": False,
                "error": f"{type(exc).__name__}: {exc}",
                "meaning": "readiness probe failed; no gate verdict is implied"}


def run(spec_path, repo_root, timeout=None, extra_env=None, report_path=None):
    try:
        spec = load_pipeline_spec(spec_path)
        check_preconditions(spec, repo_root)
        unmet = check_environment(spec, repo_root)
        readiness = collect_readiness(repo_root, spec)
        code, gate_report, proc = run_orchestrator(spec, repo_root, timeout,
                                                   extra_env)
    except PipelineAbort as e:
        report = {
            "schema": "rdebug-ci-pipeline-report/2",
            "overall": {"exit_code": INFRA_EXIT, "status": "INFRASTRUCTURE",
                        "conclusion": "failure",
                        "meaning": "the pipeline layer could not run"},
            "release_blocking_enabled": False,
            "unmet_environment_requirements": [],
            "accounting_inconsistencies": [],
            "accounting_consistent": True,
            "readiness": None,
            "gates": [],
            "gate_count": 0,
            "pipeline_abort": e.detail,
            "missing": e.missing,
        }
        _write(report_path, report)
        return INFRA_EXIT, report

    if code not in VALID_EXITS:
        # An exit the frozen mapping does not define is the orchestrator
        # misbehaving. That is infrastructure, not a verdict.
        report = {
            "schema": "rdebug-ci-pipeline-report/2",
            "overall": {"exit_code": INFRA_EXIT, "status": "INFRASTRUCTURE",
                        "conclusion": "failure",
                        "meaning": "orchestrator returned an undefined exit"},
            "release_blocking_enabled": False,
            "gates": [], "gate_count": 0,
            "orchestrator_exit": code,
            "pipeline_abort": f"undefined orchestrator exit {code!r}",
            "unmet_environment_requirements": unmet,
        }
        _write(report_path, report)
        return INFRA_EXIT, report

    tail = (proc.stdout or "")[-400:]
    report = build_report(spec, code, gate_report, unmet, tail, readiness)
    _write(report_path, report)
    return code, report


def _write(path, report):
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, default=str)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    ap = argparse.ArgumentParser(description="CI pipeline adapter")
    ap.add_argument("--spec", default=os.path.join(repo_root,
                                                    "ci-pipeline.json"))
    ap.add_argument("--json", metavar="PATH", default=None)
    ap.add_argument("--timeout", type=int, default=None)
    args = ap.parse_args(argv)

    spec_for_artifacts = {}
    try:
        spec_for_artifacts = load_pipeline_spec(args.spec)
    except PipelineAbort:
        pass
    default_report = os.path.join(
        repo_root,
        (spec_for_artifacts.get("artifacts") or {}).get(
            "pipeline_report", "ci_pipeline_report.json"))
    report_path = args.json or default_report

    code, report = run(args.spec, repo_root, timeout=args.timeout,
                        report_path=report_path)
    overall = report["overall"]
    print(f"ci pipeline: {overall['status']} (exit {overall['exit_code']}, "
          f"conclusion {overall['conclusion']})")
    for g in report.get("gates") or []:
        print(f"  {g['gate']:<24} {g['outcome']:<24} "
              f"executed={g['executed']} required={g['required_execution']}")
    for u in report.get("unmet_environment_requirements") or []:
        print("  unmet: {} needs {}".format(u["gate"], u["requirement"]))
    for bad in report.get("accounting_inconsistencies") or []:
        print("  accounting: {} {} (exit {!r}) {}".format(
            bad["gate"], bad["kind"], bad["exit_code"], bad["meaning"]))
    readiness = report.get("readiness") or {}
    if readiness.get("available"):
        print("  readiness: capability only, nothing executed; "
              "not a gate verdict")
        for row in readiness.get("gates") or []:
            if not row["runnable"]:
                print("    not runnable: {} missing {}".format(
                    row["gate"], ", ".join(row["missing_requirements"])))
    elif readiness:
        print("  readiness: unavailable ({})".format(
            readiness.get("error")))
    if report.get("pipeline_abort"):
        print("  pipeline abort: {}".format(report["pipeline_abort"]))
    print("  release blocking enabled: {}".format(report.get("release_blocking_enabled")))
    if report_path:
        print(f"  report: {report_path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
