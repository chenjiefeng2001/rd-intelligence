"""Release gate runner for DESIGN_SPEC section 4.

This is the enforcement half of I1 and I2. The reasoning it exists for is
A2-1: with RenderDoc and the capture environment variables absent, the
integration suite skips about 60 of 63 tests, and the process exit code
happens to be non-zero only because one unguarded test errors. Fix that
error, which would be a reasonable cleanup, and the suite reports OK with 60
skipped and exit 0. A gate that treats that as a pass has verified nothing.

So the rules are narrow and mechanical:

  I1  a gate whose executed count is zero, or below its declared floor, is
      not a pass. It is an infrastructure failure.
  I2  a gate whose required environment is missing is not a skip-and-pass.
      It is an infrastructure failure, and it blocks.

The four outcomes are kept distinct on purpose, per the Q3 ruling:

  PASS                   checks executed, all passed          may pass
  REGRESSION             checks executed, a difference found  blocks
  UNKNOWN                no content conclusion could be formed  does not pass
  INFRASTRUCTURE_FAILURE the gate could not execute            blocks, reported
                                                                 separately
                                                                 from REGRESSION

An infrastructure failure is deliberately never converted into a
regression, and never into a pass. Skips inside the test suites are left
alone: skipping is legitimate for a developer without a GPU, and the gate
is a separate artifact from the tests for exactly that reason.

What this is not: a pipeline. It schedules nothing and blocks no pull
request. Running it is still a manual action.
"""

import argparse
import json
import os
import re
import subprocess
import sys

SCHEMA = "rdebug-release-gates/6"

PASS = "PASS"
REGRESSION = "REGRESSION"
UNKNOWN = "UNKNOWN"
INFRA = "INFRASTRUCTURE_FAILURE"
BLOCKING = (REGRESSION, UNKNOWN, INFRA)

RAN = re.compile(r"^Ran (\d+) tests?", re.M)
SKIPPED = re.compile(r"skipped=(\d+)")
FAILED = re.compile(r"^(?:FAILED|OK)\b.*", re.M)
FAILURES = re.compile(r"failures=(\d+)")
ERRORS = re.compile(r"errors=(\d+)")

# G2. A discovery failure is reported by unittest with a synthetic test id of
# the form "unittest.loader._FailedTest.<module>". A real test id looks like
# "test_mod.Class.test_name" and never carries that prefix. Matching the full
# id, rather than searching the output text, is what keeps this narrow: a real
# failure cannot be swallowed, and a traceback that merely mentions the loader
# is not what is being matched.
RESULT_HEADER = re.compile(r"^(ERROR|FAIL): (.+)$", re.M)
DISCOVERY_MARKER = "unittest.loader._FailedTest"


class GateError(Exception):
    pass


def _result_identities(stream):
    """Test ids of every reported ERROR and FAIL, as unittest printed them."""
    return [m.group(2).strip() for m in RESULT_HEADER.finditer(stream)]


def _discovery_anomalies(stream):
    """Ids that are discovery failures rather than test outcomes."""
    return [i for i in _result_identities(stream) if DISCOVERY_MARKER in i]


def _parse_unittest(stream):
    """Extract total, skipped, failures and errors from unittest output."""
    ran = RAN.search(stream)
    if not ran:
        raise GateError("could not parse test counts from unittest output")
    total = int(ran.group(1))
    skipped = int(SKIPPED.search(stream).group(1)) if SKIPPED.search(stream) else 0
    failures = int(FAILURES.search(stream).group(1)) if FAILURES.search(stream) else 0
    errors = int(ERRORS.search(stream).group(1)) if ERRORS.search(stream) else 0
    summary = FAILED.search(stream)
    verdict = "OK" if (summary and summary.group(0).startswith("OK")) else "FAILED"
    return {
        "total": total,
        "skipped": skipped,
        "failures": failures,
        "errors": errors,
        "verdict": verdict,
        "executed": total - skipped,
        "discovery_anomalies": _discovery_anomalies(stream),
        "result_identities": _result_identities(stream),
    }


def check_requires(gate, repo_root, env):
    """Report declared-but-missing prerequisites as an infrastructure failure.

    Checked before the gate runs, so a missing environment never produces a
    skip storm that could be misread.
    """
    req = gate.get("requires") or {}
    missing = []
    for name in req.get("env", []):
        if not env.get(name):
            missing.append(f"env:{name}")
    if req.get("module"):
        try:
            from rdebug.adapter.locator import find_module_dir

            have = find_module_dir() is not None
        except Exception:
            have = False
        if not have:
            missing.append("module:{}".format(req["module"]))
    if req.get("capture"):
        cap = env.get("RDEBUG_INTEGRATION_CAPTURE")
        if not cap or not os.path.isfile(cap):
            missing.append("capture:RDEBUG_INTEGRATION_CAPTURE")
    if req.get("sibling_fork"):
        fork = os.path.normpath(os.path.join(repo_root, "..", "renderdoc"))
        if not os.path.isdir(os.path.join(fork, ".git")):
            missing.append("sibling_fork:../renderdoc")
    return missing


def _verdict_path(gate, repo_root, env):
    """Where a verdict_json gate was told to write its report.

    Declared on the gate, with {capture} substituted from the spec's capture
    table so the gate command and the report path cannot drift apart.
    """
    template = gate.get("verdict_path")
    if not template:
        return None
    return os.path.join(repo_root, template)


def _substitute_capture(command, spec_captures, key):
    path = (spec_captures or {}).get(key)
    if not path:
        return None
    return [path if part == "CAPTURE_PLACEHOLDER" else part for part in command]


def _verdict_detail(verdict):
    """One line, plus the execution accounting a reviewer needs."""
    outcome = verdict.get("outcome")
    cases = verdict.get("cases") or {}
    if not cases:
        return "{} ({})".format(outcome, (verdict.get("evidence") or {}).get(
            "abort", "no case detail"))
    bits = []
    for cid in sorted(cases):
        c = cases[cid]
        bits.append(f"{cid}={c.get('verdict')}"
                    f"({c.get('available_at', 0)}/{c.get('attempted', 0)})")
    ev = verdict.get("evidence") or {}
    workers = ev.get("workers") or {}
    suffix = ""
    if workers:
        suffix = f" workers={sorted(set(workers.values()))}"
    return "{}: {}{}".format(outcome, ", ".join(bits), suffix)


def run_gate(gate, repo_root, env=None, timeout=None, runner=None,
             spec_captures=None):
    """Run one gate and classify it. Never raises for a gate-level failure."""
    env = dict(os.environ if env is None else env)
    kind = runner or gate.get("runner") or "exit_code"
    gate = dict(gate)
    if "CAPTURE_PLACEHOLDER" in (gate.get("command") or []):
        resolved = _substitute_capture(gate["command"], spec_captures,
                                       gate["id"])
        if resolved:
            gate["command"] = resolved

    def record(outcome, detail, executed=None, exit_code=None, **extra):
        """Every gate record carries the same accounting fields.

        A report that omits state or required_execution cannot answer whether
        a gate was expected to run, which is the question that distinguishes
        verified from merely reported.

        The test result and the process exit are two independent facts about one
        run, so both are recorded side by side rather than one replacing the
        other. A gate whose 63 tests passed and which then died on the way out
        is not "63 failed" and is not "passed"; INFRASTRUCTURE_FAILURE is only
        honest if the row still says the tests passed.

        execution_clean is derived from the process exit code and never set
        independently. Two names for one number drift the moment one of them is
        edited alone.
        """
        out = {
            "gate": gate["id"],
            "spec_gate": gate.get("spec_gate"),
            "state": gate.get("state", "IMPLEMENTED"),
            "outcome": outcome,
            "required_execution": bool(gate.get("required_execution", True)),
            "blocking": bool(gate.get("blocking", True)),
            "attempted": True,
            "executed": executed,
            "command": gate.get("command"),
            "exit_code": exit_code,
            "process_exit_code": exit_code,
            "execution_clean": exit_code == 0,
            "detail": detail,
        }
        if "failures" in extra or "errors" in extra:
            out.update({
                "tests_executed": extra.get("executed", executed),
                "tests_failed": extra.get("failures"),
                "tests_errors": extra.get("errors"),
                "test_result": extra.get("verdict"),
            })
        out.update(extra)
        return out

    missing = check_requires(gate, repo_root, env)
    if missing:
        return record(INFRA,
                      "missing prerequisites: " + ", ".join(missing),
                      executed=0)

    # Marker so a test that exercises the whole pipeline can detect that it is
    # being run from inside the gate it exercises, and stand down. Without it
    # that test re-enters this runner, which re-enters the suite, which re-enters
    # the test, and the run times out having proved nothing.
    # Set the recursion marker once, before any child is spawned. Adding the
    # lint precondition put a subprocess.run above this line, which broke
    # test_orchestrator_marks_child_processes -- and the control was right to.
    # Ruff does not execute the suite, so nothing was actually recursing, but
    # the guard's purpose is that every child of the orchestrator sees the
    # marker, and a lint command that grew a step would have quietly escaped it.
    env["RDEBUG_GATE_RUN"] = "1"

    # Lint is a precondition of this gate, not a gate. It runs before the gate's
    # own command and short-circuits it, so a violation is reported without
    # spending the run on tests whose result cannot change the verdict.
    lint_spec = gate.get("lint")
    if lint_spec:
        lint_outcome, lint_detail, lint_exit, lint_cmd = run_lint(
            lint_spec, repo_root, env, timeout=timeout)
        if lint_outcome != PASS:
            # The gate's own process never ran, so its exit code is honestly
            # None rather than lint's. Folding lint's exit into the gate row
            # would make a legitimate REGRESSION look like a gate that ignored
            # its own non-zero exit, and accounting_inconsistencies would then
            # report a contradiction that does not exist.
            return record(lint_outcome, lint_detail, executed=0, exit_code=None,
                          lint={"command": lint_cmd, "outcome": lint_outcome,
                                "exit_code": lint_exit, "detail": lint_detail})

    proc = subprocess.run(
        gate["command"], cwd=repo_root, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    stream = (proc.stdout or "") + (proc.stderr or "")

    if kind == "verdict_json":
        # A gate that produces its own four-state verdict. exit_code would
        # collapse that verdict into pass or non-zero, which is the G1 defect,
        # so the verdict is read from the JSON the gate wrote.
        report_path = _verdict_path(gate, repo_root, env)
        if not report_path or not os.path.isfile(report_path):
            return record(INFRA, "gate produced no verdict file at %s"
                          % (report_path or "<unset>"))
        try:
            with open(report_path, encoding="utf-8") as fh:
                verdict = json.load(fh)
        except Exception as e:  # noqa: BLE001 - an unreadable verdict is INFRASTRUCTURE_FAILURE with the parse error as detail; the type adds nothing
            return record(INFRA, f"unreadable verdict: {e}")
        return record(verdict.get("outcome", INFRA),
                      _verdict_detail(verdict),
                      verdict=verdict, exit_code=proc.returncode)

    if kind == "unittest":
        try:
            counts = _parse_unittest(stream)
        except GateError as e:
            return record(INFRA, str(e), executed=0)
        floor = gate.get("min_executed")
        if counts["executed"] == 0:
            return record(INFRA,
                          f"I1: 0 of {counts['total']} tests executed; a gate "
                          f"that verified nothing is not a pass",
                          exit_code=proc.returncode, **counts)
        if floor is not None and counts["executed"] < floor:
            return record(INFRA,
                          f"I1: only {counts['executed']} tests executed, "
                          f"declared floor is {floor}",
                          exit_code=proc.returncode, **counts)
        if counts["discovery_anomalies"]:
            return record(INFRA,
                          "G2: test discovery failed for "
                          + ", ".join(counts["discovery_anomalies"])
                          + "; a module that cannot be imported is a "
                            "test-infrastructure problem, not a content "
                            "regression",
                          exit_code=proc.returncode, **counts)
        if counts["failures"] or counts["errors"]:
            # Content outranks the process exit, deliberately and first. A real
            # failure also exits non-zero, so a rule of the form "non-zero exit
            # implies infrastructure" would relabel every genuine regression as
            # a broken runner and hide it.
            return record(REGRESSION,
                          f"{counts['failures']} failure(s), "
                          f"{counts['errors']} error(s) with "
                          f"{counts['executed']} executed",
                          exit_code=proc.returncode, **counts)
        if proc.returncode != 0:
            # Only reachable once failures and errors are both zero, which is
            # what makes INFRASTRUCTURE_FAILURE honest here rather than a
            # cover for a red test. The tests reported a result and the
            # process then failed to exit cleanly; neither fact is allowed to
            # overwrite the other.
            #
            # This is the only new verdict path, and it can withhold PASS. No
            # compatibility branch returns PASS on a non-zero exit.
            return record(INFRA,
                          f"{counts['executed']} checks reported "
                          f"{counts['verdict']}, but the process did not exit "
                          f"cleanly (exit {proc.returncode}); the test result "
                          f"and the exit status are separate facts",
                          exit_code=proc.returncode, **counts)
        if counts["skipped"]:
            return record(UNKNOWN,
                          f"{counts['skipped']} of {counts['total']} tests "
                          f"skipped; no content conclusion for the skipped part",
                          exit_code=proc.returncode, **counts)
        return record(PASS,
                      f"{counts['executed']} checks executed, all passed",
                      exit_code=proc.returncode, **counts)

    if proc.returncode != 0:
        tail = (stream.strip().splitlines() or ["<no output>"])[-1]
        return record(REGRESSION, f"exit {proc.returncode}: {tail[:120]}",
                      exit_code=proc.returncode)
    return record(PASS, "exit 0", exit_code=proc.returncode)


LINT_DETAIL_LINES = 12


def classify_lint(exit_code=None, stdout="", stderr="", launch_error=None):
    """Map a lint run onto the existing four states. No fifth state.

    Ruled in docs/LINT-EXECUTION-CONTRACT.md and unchanged from there:

      ruff absent, not run, or unable to read its config -> INFRA
      ruff ran and found violations                     -> REGRESSION

    The split is whether anything was concluded about the code. A gate that
    could not run has no conclusion, and recording one anyway is how a missing
    tool turns into an accusation. This is the same distinction the integration
    gate is being held to when its 63 tests pass and its process dies.

    Exit codes: 0 clean, 1 violations. Anything else is INFRA, including
    2 and 127, because only those two carry a meaning and guessing at the rest
    would fail open.
    """
    if launch_error:
        return INFRA, f"lint precondition could not run: {launch_error}"
    stream = (stdout or "") + (stderr or "")
    if exit_code == 0:
        return PASS, "lint precondition: no violations"
    if exit_code == 1:
        lines = [ln for ln in stream.splitlines() if ln.strip()]
        detail = f"lint precondition: {len(lines)} violation line(s)"
        for ln in lines[:LINT_DETAIL_LINES]:
            detail += "\n  " + ln
        return REGRESSION, detail
    return INFRA, (f"lint precondition exited {exit_code!r}, which is "
                   "neither 0 (clean) nor 1 (violations); the gate could "
                   "not reach a conclusion")


def _lint_probe_cmd(cmd):
    """Derive an availability probe from the check command.

    Mapping the exit code alone is not enough. A missing ruff launched as
    `python -m ruff` exits 1, which is the same code ruff uses for "found
    violations" -- so an absent tool was being reported as a content
    regression. Found by driving run_gate rather than classify_lint, which is
    why the mapping alone was not enough of a control.
    """
    return ["--version" if part == "check" else part for part in cmd]


def run_lint(lint_spec, repo_root, env, timeout=None):
    """Run the lint precondition. Returns (outcome, detail, exit_code, cmd)."""
    cmd = list(lint_spec.get("command") or [])

    probe = list(lint_spec.get("probe_command") or []) or _lint_probe_cmd(cmd)
    if probe and probe != cmd:
        try:
            probe_proc = subprocess.run(
                probe, cwd=repo_root, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, ValueError) as exc:
            outcome, detail = classify_lint(launch_error=str(exc))
            return outcome, detail, None, cmd
        if probe_proc.returncode != 0:
            outcome, detail = classify_lint(
                launch_error=(f"lint is not runnable here "
                              f"({' '.join(probe)} exited "
                              f"{probe_proc.returncode!r})"))
            return outcome, detail, None, cmd

    try:
        proc = subprocess.run(cmd, cwd=repo_root, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except (OSError, ValueError) as exc:
        outcome, detail = classify_lint(launch_error=str(exc))
        return outcome, detail, None, cmd
    outcome, detail = classify_lint(exit_code=proc.returncode,
                                    stdout=proc.stdout, stderr=proc.stderr)
    return outcome, detail, proc.returncode, cmd


def run_all(spec, repo_root, env=None, only=None, timeout=None, runner=None):
    # spec.get("captures") maps a gate id to the capture it must run against.
    results = []
    for gate in spec["gates"]:
        if only and gate["id"] not in only:
            continue
        if gate.get("state", "IMPLEMENTED") != "IMPLEMENTED":
            # Nothing to run. Reported by declare_unimplemented so the gate
            # stays visible in the report instead of silently disappearing.
            continue
        results.append(run_gate(gate, repo_root, env=env, timeout=timeout,
                                runner=runner,
                                spec_captures=spec.get("captures")))
    return results


# Overall states. Each maps to its own exit code so an outer layer can branch
# without parsing text, which was the defect G1 described: a binary exit 1
# could not tell a regression from an infrastructure failure.
PASS_OVERALL = "PASS"
FAIL_REGRESSION = "FAIL_REGRESSION"
BLOCKED_INFRA = "BLOCKED_INFRA"
NEEDS_REVIEW = "NEEDS_REVIEW"

DEFAULT_EXIT_CODES = {
    PASS_OVERALL: 0,
    FAIL_REGRESSION: 2,
    BLOCKED_INFRA: 3,
    NEEDS_REVIEW: 4,
}


def declare_unimplemented(spec):
    """Gates with nothing to run, reported rather than omitted.

    A declared gate in state NOT_IMPLEMENTED or PROCESS_ONLY has no command,
    so it never reaches run_gate. It still has to appear in the report and it
    still has to hold the aggregate off PASS, because a required gate that
    never ran is exactly what I1 forbids treating as a pass.
    """
    out = []
    for gate in spec["gates"]:
        state = gate.get("state", "IMPLEMENTED")
        if state == "IMPLEMENTED":
            continue
        out.append({
            "gate": gate["id"],
            "spec_gate": gate.get("spec_gate"),
            "outcome": gate.get("contributes", UNKNOWN),
            "state": state,
            "required_execution": bool(gate.get("required_execution")),
            "blocking": bool(gate.get("blocking")),
            "attempted": False,
            "executed": 0,
            "skipped": None,
            "failures": None,
            "errors": None,
            "discovery_anomalies": [],
            "exit_code": None,
            "duration_s": None,
            "detail": gate.get("rationale", ""),
            "spec_ref": gate.get("spec_ref"),
        })
    return out


def overall(spec, results, exit_codes=None):
    """Reduce per-gate outcomes to one overall state, in the ruled order.

    REGRESSION outranks infrastructure failure, which outranks unknown, and
    PASS is reachable only when every required gate both ran and passed and
    every declared section 4 gate is implemented.
    """
    codes = dict(DEFAULT_EXIT_CODES)
    codes.update(exit_codes or {})

    records = list(results) + declare_unimplemented(spec)
    reasons = []
    for r in records:
        state = r.get("state", "IMPLEMENTED")
        reason = f"{r['gate']}={r['outcome']}"
        if state != "IMPLEMENTED":
            reason += f" ({state})"
        reasons.append(reason)

    outcomes = [r["outcome"] for r in records]
    if REGRESSION in outcomes:
        status = FAIL_REGRESSION
    elif INFRA in outcomes:
        status = BLOCKED_INFRA
    elif UNKNOWN in outcomes:
        status = NEEDS_REVIEW
    else:
        required_unimplemented = [
            r for r in records
            if r.get("required_execution") and r.get("state") != "IMPLEMENTED"
        ]
        not_run = [
            r for r in records
            if r.get("required_execution") and r.get("state", "IMPLEMENTED") == "IMPLEMENTED"
            and not r.get("executed")
        ]
        if required_unimplemented or not_run:
            status = NEEDS_REVIEW
        else:
            status = PASS_OVERALL

    return {
        "status": status,
        "exit_code": codes[status],
        "reasons": reasons,
        "gates": records,
    }


def load_spec(path):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if doc.get("schema") != SCHEMA:
        raise GateError("gate spec schema {!r} is not {!r}".format(doc.get("schema"), SCHEMA))
    return doc


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spec", default=os.path.join(repo_root, "release-gates.json"))
    ap.add_argument("--only", action="append", default=None,
                    help="run only the named gate (repeatable)")
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--list", action="store_true",
                    help="list declared gates and exit")
    ap.add_argument("--json", metavar="PATH", default=None,
                    help="also write the machine-readable report to PATH")
    args = ap.parse_args(argv)

    spec = load_spec(args.spec)
    if args.list:
        for g in spec["gates"]:
            print(f"  {g['id']:<24} {g.get('spec_gate', '-'):<5} "
                  f"{g.get('state', 'IMPLEMENTED')}")
        return 0

    print("release gates (DESIGN_SPEC 4; I1/I2 enforcement, G1/G2 verdicts)")
    results = run_all(spec, repo_root, only=set(args.only) if args.only else None,
                      timeout=args.timeout)
    report = overall(spec, results, spec.get("exit_codes"))
    for r in report["gates"]:
        print(f"  {r['gate']:<24} {r['outcome']:<24} {r['detail'][:72]}")
    print(f"  RESULT: {report['status']} (exit {report['exit_code']})")
    for reason in report["reasons"]:
        print(f"    - {reason}")
    if report["status"] == NEEDS_REVIEW:
        print("  note: unknown is not a pass; per the Q3 ruling it needs a "
              "human and must not be auto-promoted")
    if report["status"] == BLOCKED_INFRA:
        print("  note: an infrastructure failure is not a regression and is "
              "not a content conclusion; fix the environment or the gate")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, default=str)
        print(f"  report: {args.json}")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
