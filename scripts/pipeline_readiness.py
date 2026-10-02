"""Pipeline readiness: declare what a runner must have, and report honestly when it
does not have it.

DESIGN_SPEC 4.2. This is an execution-prerequisite layer, deliberately
separate from the gate verdicts of 4.1. A gate answers "does this rendering
result match"; readiness answers "can this machine answer that question at
all". Mixing the two is how a machine with no GPU ends up reported as a
rendering regression.

Nothing here provisions anything. It reads state and reports it. There is no
install, no download and no clone, and a control asserts their absence,
because a readiness contract that quietly fixed its own environment would
report the environment it created rather than the one it was given.

Section 4.2.5 is the reason the probes return booleans rather than
assertions. This repository currently has no tracked capture and no GPU
runner. Those are facts about today, not premises of the contract: a later
machine that does have a capture must not be reported as broken by a probe
that hardcoded its expectation. So the probe observes, and the classification
below decides what an observation means for a particular gate.
"""

import json
import os
import subprocess
import sys

PASS = "PASS"
REGRESSION = "REGRESSION"
UNKNOWN = "UNKNOWN"
INFRA = "INFRASTRUCTURE_FAILURE"

# Overall states and their exit codes, as frozen by DESIGN_SPEC 4.1.
OVERALL_EXIT = {
    "PASS": 0,
    "FAIL_REGRESSION": 2,
    "BLOCKED_INFRA": 3,
    "NEEDS_REVIEW": 4,
}

GATE_FIELDS = ("gate_id", "required_execution", "attempted", "executed",
               "state", "reason", "missing_requirements")
ENVIRONMENT_FIELDS = ("renderdoc", "gpu", "corpus", "runtime")


class ReadinessViolation(Exception):
    """A report that would let 'did not run' be read as 'passed'."""


# --------------------------------------------------------------- probes
def _probe_renderdoc(repo_root, env):
    """Three independent observations, deliberately not sharing a try block.

    They were merged at first and it produced a wrong answer: the version query
    called a method the Python module does not expose, the exception unwound
    into the importability flag, and a machine that imports RenderDoc perfectly
    well was reported as lacking it. Absence of one observation is not evidence
    about the others, so each gets its own.
    """
    fork = os.path.normpath(os.path.join(repo_root, "..", "renderdoc"))
    fork_present = os.path.isdir(os.path.join(fork, ".git"))

    module_importable = False
    rd = None
    try:
        from rdebug.adapter.locator import find_module_dir, import_renderdoc

        module_importable = find_module_dir() is not None
        if module_importable:
            rd = import_renderdoc()
            module_importable = rd is not None
    except Exception:  # noqa: BLE001 - absence is the observation
        module_importable = False

    version = None
    if rd is not None:
        try:
            version = str(rd.GetVersionString())
        except Exception:  # noqa: BLE001 - a version is not an import
            version = None

    commit = None
    if fork_present:
        try:
            out = subprocess.run(
                ["git", "-C", fork, "rev-parse", "--short=9", "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            commit = out.stdout.strip() or None
        except Exception:  # noqa: BLE001 - no git means no commit to report; absence is the answer, not an error
            commit = None

    return {"fork_present": fork_present,
            "module_importable": bool(module_importable),
            "version": version,
            "commit": commit}


def _probe_gpu(repo_root, env):
    """Observed replay capability, not a claim about hardware."""
    present, driver, replay_supported = False, None, None
    path = env.get("RDEBUG_INTEGRATION_CAPTURE")
    if path and os.path.isfile(path):
        try:
            from rdebug.adapter.core import CaptureSession

            s = CaptureSession(path)
            try:
                present = True
                driver = s.driver
                replay_supported = bool(s._cap.LocalReplaySupport())
            finally:
                s.close()
        except Exception:  # noqa: BLE001 - the probe closes over whatever the import left behind
            present = False
    return {"present": present, "driver": driver,
            "replay_supported": replay_supported,
            "probe_capture": path}


def _probe_corpus(repo_root, env):
    corpus = os.path.join(repo_root, "tests", "workload", "corpus")
    present = os.path.isdir(corpus) and bool(
        [n for n in os.listdir(corpus) if n.endswith(".rdc")]
    ) if os.path.isdir(corpus) else False
    count = len([n for n in os.listdir(corpus) if n.endswith(".rdc")]) \
        if os.path.isdir(corpus) else 0
    tracked = 0
    try:
        out = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "tests/workload/corpus"],
            capture_output=True, text=True, timeout=60,
        )
        tracked = len([ln for ln in out.stdout.splitlines() if ln.strip()])
    except Exception:  # noqa: BLE001 - an unrunnable git means tracked count is unknown, which the caller treats as unavailable rather than fatal
        tracked = 0
    manifest_path = os.path.normpath(
        os.path.join(repo_root, "..", "rdebug-validation", "reports", "n3",
                     "N3-05A-freeze-manifest.json"))
    manifest_match = None
    if os.path.isfile(manifest_path):
        try:
            import hashlib

            with open(manifest_path, encoding="utf-8") as fh:
                manifest = json.load(fh)
            root = os.path.dirname(
                os.path.dirname(os.path.dirname(manifest_path)))
            bad = []
            for name, rec in (manifest.get("artifacts") or {}).items():
                full = os.path.join(root, name)
                if not os.path.isfile(full):
                    bad.append(name)
                    continue
                h = hashlib.sha256()
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                if h.hexdigest() != rec.get("sha256"):
                    bad.append(name)
            manifest_match = not bad
        except Exception:  # noqa: BLE001 - an unreadable manifest means the corpus cannot be verified; that is reported as an unmet requirement
            manifest_match = None
    return {"captures_present": bool(present), "capture_count": count,
            "tracked_captures": tracked, "manifest_match": manifest_match,
            # Declarations, not observations. These do not change with the
            # machine; they state what the corpus IS, so that its presence is
            # never mistaken for a repository guarantee. See
            # docs/CAPTURE-CORPUS-CONTRACT.md.
            "required": True,
            "source": "external",
            "tracked": bool(tracked),
            "provenance_required": True}


def _probe_runtime(repo_root, env):
    python_ok = sys.version_info >= (3, 9)
    dependencies_ok, missing = True, []
    for mod in ("rdebug", "rdebug_mcp", "rdebug_ide"):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001 - capability detection is the question -- 'can this import' is answered by any failure, not by one exception type
            dependencies_ok = False
            missing.append(mod)
    version = sys.version_info[:3]
    return {"python_version": f"{version[0]}.{version[1]}.{version[2]}",
            "python_ok": bool(python_ok),
            "dependencies_ok": bool(dependencies_ok),
            "missing_dependencies": missing}


def probe_environment(repo_root, env=None):
    """Observe the four capability classes. Declares, never provisions."""
    env = dict(os.environ if env is None else env)
    return {
        "renderdoc": _probe_renderdoc(repo_root, env),
        "gpu": _probe_gpu(repo_root, env),
        "corpus": _probe_corpus(repo_root, env),
        "runtime": _probe_runtime(repo_root, env),
    }


# ------------------------------------------------- missing-requirement model
def capability_satisfied(environment, requirement):
    """Resolve a dotted requirement against the probed environment.

    An unknown requirement is treated as NOT satisfied. Guessing satisfied
    would let a typo in a gate declaration read as a working runner.
    """
    node = environment
    for part in requirement.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    if isinstance(node, bool):
        return node
    if node is None:
        return False
    if isinstance(node, (int, float, str)):
        return True
    if isinstance(node, list):
        return bool(node)
    return bool(node)


def missing_requirements(gate, environment):
    """What this gate asked for that the machine does not have."""
    out = []
    for name in (gate.get("requires") or {}).get("capabilities") or []:
        if not capability_satisfied(environment, name):
            out.append(name)
    return out


def classify_missing(missing, required, attempted=True, executed=0,
                     failure_type=None):
    """4.2.2 and 4.2.3 in one place.

    Precedence is fixed and narrow: a reported content failure outranks an
    execution problem, because a gate that ran and found something is more
    informative than one that could not run. Absent that, a required gate
    that did not run is infrastructure, an optional one is unknown, and
    nothing missing with real execution behind it is a pass.
    """
    if failure_type == "regression":
        return REGRESSION
    if failure_type in ("infrastructure", "discovery", "unreadable"):
        return INFRA
    if missing:
        return INFRA if required else UNKNOWN
    if not attempted or not executed:
        return INFRA if required else UNKNOWN
    return PASS


# ------------------------------------------------------------- report layer
def build_gate_row(gate, environment, missing=None):
    """One capability row.

    This layer never runs a gate, so it must not pretend to. attempted is
    always False and executed always 0, and the verdict means runnable or
    blocked rather than passed or failed. Reporting attempted=True with
    executed=0 here would be the same confusion the contract forbids, just
    inverted: the gate did not run, and this layer never tried.
    """
    req = bool(gate.get("required_execution", True))
    state = gate.get("state", "IMPLEMENTED")
    miss = missing_requirements(gate, environment) if missing is None \
        else list(missing)

    if state != "IMPLEMENTED":
        verdict = UNKNOWN
        reason = f"declared {state}; no executable check exists"
    elif miss:
        verdict = INFRA if req else UNKNOWN
        reason = "missing: " + ", ".join(miss)
    else:
        verdict = PASS
        reason = "required capabilities present; not executed by this layer"

    return {
        "gate_id": gate.get("id"),
        "spec_gate": gate.get("spec_gate"),
        "state": state,
        "required_execution": req,
        "attempted": False,
        "executed": 0,
        "verdict": verdict,
        "reason": reason,
        "missing_requirements": miss,
    }


def overall_from_rows(rows, scope="capability"):
    """Overall state, with the same precedence as 4.1.

    In capability scope the verdicts mean runnable rather than passed, so the
    aggregate is reported under a scope tag and never as a CI verdict.
    """
    verdicts = [r["verdict"] for r in rows]
    if REGRESSION in verdicts:
        return "FAIL_REGRESSION"
    if INFRA in verdicts:
        return "BLOCKED_INFRA"
    if UNKNOWN in verdicts:
        return "NEEDS_REVIEW"
    return "PASS"


def validate_report(report, scope="execution"):
    """V1 to V3. Raises rather than warns, because a warning is read past."""
    for field in ("environment", "gates", "overall"):
        if field not in report:
            raise ReadinessViolation(
                f"report is missing the {field!r} section; without it "
                "'did not run' can be read as 'passed'")
    for field in ENVIRONMENT_FIELDS:
        if field not in report["environment"]:
            raise ReadinessViolation(
                f"environment is missing the {field!r} capability class")
    if not isinstance(report["gates"], list) or not report["gates"]:
        raise ReadinessViolation("gates must be a non-empty list")
    for row in report["gates"]:
        for field in GATE_FIELDS:
            if field not in row:
                raise ReadinessViolation(
                    f"gate row {row.get('gate_id')!r} is missing {field!r}")
        # V2
        if not row["attempted"] and row["executed"]:
            raise ReadinessViolation(
                f"gate {row['gate_id']} reports attempted=false but "
                f"executed={row['executed']}; the command did not run")
        if (not row["attempted"] and row["required_execution"]
                and scope == "execution" and not row["missing_requirements"]):
            raise ReadinessViolation(
                f"gate {row['gate_id']} is required and did not run but "
                "records no missing requirement")
    overall = report["overall"]
    for field in ("state", "exit_code"):
        if field not in overall:
            raise ReadinessViolation(f"overall is missing {field!r}")
    state = overall["state"]
    expected = OVERALL_EXIT.get(state)
    if expected is None:
        raise ReadinessViolation(f"unknown overall state {state!r}")
    if overall["exit_code"] != expected:
        raise ReadinessViolation(
            f"overall state {state!r} must carry exit code {expected!r}, "
            f"not {overall['exit_code']!r}")
    if state == "PASS" and scope == "execution":
        for row in report["gates"]:
            if row["required_execution"] and (
                    not row["attempted"] or not row["executed"]):
                raise ReadinessViolation(
                    f"overall is PASS but required gate {row['gate_id']} "
                    "did not execute")
    return True


def cross_check_exit(report, process_exit):
    """V3: the process and the report must agree.

    The check that matters most on a machine where something is missing. A
    report is easy to write and easy to misread; an exit code that disagrees
    with it is caught by whoever runs the command, not by whoever reads it.
    """
    validate_report(report)
    state = report["overall"]["state"]
    expected = OVERALL_EXIT[state]
    if process_exit != expected:
        raise ReadinessViolation(
            f"process exit {process_exit!r} disagrees with report state "
            f"{state!r}, which implies {expected!r}")
    return True


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    import argparse

    ap = argparse.ArgumentParser(description="Declare runner capabilities")
    ap.add_argument("--gate-spec", default=os.path.join(repo_root,
                                                         "release-gates.json"))
    ap.add_argument("--json", metavar="PATH", default=None)
    args = ap.parse_args(argv)

    with open(args.gate_spec, encoding="utf-8") as fh:
        gates = json.load(fh)
    environment = probe_environment(repo_root)
    rows = [build_gate_row(g, environment) for g in gates["gates"]]
    state = overall_from_rows(rows, scope="capability")
    report = {"schema": "rdebug-pipeline-readiness/1",
              "scope": "capability",
              "scope_note": ("This layer declares whether each gate could run on "
                              "this machine. It runs nothing, so every verdict here "
                              "means runnable or blocked, never passed or failed."),
              "environment": environment,
              "gates": rows,
              "overall": {"state": state, "exit_code": OVERALL_EXIT[state]}}
    validate_report(report, scope="capability")

    print(f"pipeline readiness (capability, nothing executed): {state} "
          f"(exit {OVERALL_EXIT[state]})")
    for row in rows:
        runnable = "no" if row["missing_requirements"] else "yes"
        print(f"  {row['gate_id']:<24} "
              f"required={str(row['required_execution']):<5} "
              f"runnable={runnable:<5} {row['verdict']}")
        for miss in row["missing_requirements"]:
            print(f"      missing: {', '.join(miss)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, default=str)
        print(f"  report: {args.json}")
    return OVERALL_EXIT[state]


if __name__ == "__main__":
    sys.exit(main())
