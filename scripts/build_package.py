"""Build the distribution and check what actually went into it.

A build that exits zero says very little. `python -m build` reports success for a
wheel that omits the IDE page, for a wheel with no licence file, and for a
wheel whose console scripts do not exist, because none of those are build
errors -- they are packaging decisions that nobody looked at. This script
therefore builds, then opens the artifacts and asserts the members a working
install needs.

That is not hypothetical here. This repository shipped an unbuildable
pyproject.toml for as long as nobody ran a build: PEP 639 had superseded the
MIT classifier and setuptools >= 78 refused to build at all. It also shipped a
wheel with no `rdebug_ide/static/index.html`, so `pip install` succeeded and
`rdebug-ide` served nothing. Both were invisible to the test suite.

It separates its own failures from the artifacts' condition. A missing build
backend, an unreadable artifact or a backend that will not run is
INFRASTRUCTURE; a wheel that built cleanly and is missing something is a
REGRESSION. Those must not share an exit code, because "the machine could not
answer" and "the answer is no" are not the same report.

It fabricates nothing. There is no simulated success path, and an absent
backend is reported as infrastructure failure rather than skipped, because a
green line here is supposed to mean a real artifact was inspected.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

SCHEMA = "rdebug-build-report/1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE = os.path.join(ROOT, "build", "_staged_source")

PASS = 0
REGRESSION = 2
INFRA = 3

# What a working install of this project needs. Named by module role rather than
# by a version string so a version bump does not silently edit the requirement.
WHEEL_REQUIRED = (
    "rdebug_ide/static/index.html",     # the IDE serves this; without it: no page
    "rdebug_ide/app.py",
    "rdebug/cli.py",
    "rdebug_mcp/server.py",
)

CONSOLE_SCRIPTS = ("rdebug", "rdebug-mcp", "rdebug-ide")

SDIST_REQUIRED = (
    "pyproject.toml",
    "LICENSE",
    "README.md",
    "src/rdebug_ide/static/index.html",
)


class Infra(Exception):
    """This layer could not answer. Never a statement about the artifacts."""


def wheel_members(path):
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise Infra("wheel is not a readable archive: " + str(exc)) from exc


def sdist_members(path):
    try:
        with tarfile.open(path) as tf:
            return tf.getnames()
    except (tarfile.TarError, OSError) as exc:
        raise Infra("sdist is not a readable archive: " + str(exc)) from exc


def check_wheel(path):
    members = wheel_members(path)
    present = set(members)
    missing = [m for m in WHEEL_REQUIRED if m not in present]
    licences = [m for m in members if "LICENSE" in m.split("/")[-1]]
    if not licences:
        missing.append("LICENSE (any dist-info/licenses entry)")
    entry = next((m for m in members if m.endswith("entry_points.txt")), None)
    scripts = []
    if entry is None:
        missing.append("entry_points.txt")
    else:
        with zipfile.ZipFile(path) as zf:
            body = zf.read(entry).decode("utf-8", "replace")
        scripts = [s for s in CONSOLE_SCRIPTS
                   if ("=" + s) not in body and (s + " =") not in body]
        missing += ["console script " + s for s in scripts]
    return {"artifact": os.path.basename(path),
            "members": len(members),
            "licence": licences,
            "missing": missing,
            "ok": not missing}


def check_sdist(path):
    members = sdist_members(path)
    tails = set()
    for n in members:
        parts = n.split("/", 1)
        tails.add(parts[1] if len(parts) == 2 else n)
    missing = [m for m in SDIST_REQUIRED if m not in tails]
    return {"artifact": os.path.basename(path),
            "members": len(members),
            "missing": missing,
            "ok": not missing}


def stage_source(dest):
    """Copy the build inputs into a clean directory, from an explicit list.

    Building in place is not reproducible here. setuptools caches the file
    manifest in `src/*.egg-info/SOURCES.txt` and reuses `build/lib`, so a
    declaration that was removed can still appear in the wheel simply because an
    earlier build put it there. That was observed: dropping the package-data
    section still produced a wheel containing index.html, and the check passed.

    The inputs are listed rather than globbed so that "what goes into a release"
    is readable in one place, and so that build state, caches and reports can
    never leak into an artifact.
    """
    os.makedirs(dest, exist_ok=True)
    staged = []
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        src = os.path.join(ROOT, name)
        if not os.path.isfile(src):
            raise Infra("missing build input: " + name)
        shutil.copy2(src, os.path.join(dest, name))
        staged.append(name)
    shutil.copytree(os.path.join(ROOT, "src"), os.path.join(dest, "src"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                  "*.egg-info"))
    staged.append("src/")
    return staged


def build(outdir, workdir):
    """Run the PEP 517 build against a staged copy."""
    try:
        import build  # noqa: F401 - probed for presence only; the build runs as a subprocess
    except ImportError as exc:
        raise Infra("the `build` backend is not installed; "
                    "this is not a pass and not a regression") from exc
    stage_source(workdir)
    cmd = [sys.executable, "-m", "build", "--outdir", outdir, workdir]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        raise Infra("`python -m build` exited " + str(proc.returncode) +
                    "; the package does not build:\n" +
                    (proc.stderr or proc.stdout)[-2000:])
    wheels = [f for f in os.listdir(outdir) if f.endswith(".whl")]
    sdists = [f for f in os.listdir(outdir) if f.endswith(".tar.gz")]
    if not wheels or not sdists:
        raise Infra("the build reported success but produced "
                    + repr({"wheel": wheels, "sdist": sdists}))
    return ([os.path.join(outdir, w) for w in wheels],
            [os.path.join(outdir, s) for s in sdists])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outdir", default="dist")
    ap.add_argument("--json", dest="report")
    ap.add_argument("--clean", action="store_true",
                    help="remove the output directory first")
    args = ap.parse_args(argv)

    if args.clean and os.path.isdir(args.outdir):
        shutil.rmtree(args.outdir)
    os.makedirs(args.outdir, exist_ok=True)
    # The staged copy is discarded every run; reusing it would reintroduce
    # exactly the staleness this staging exists to remove.
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)

    report = {"schema": SCHEMA, "outdir": args.outdir, "staged": STAGE}
    try:
        wheels, sdists = build(args.outdir, STAGE)
    except Infra as exc:
        report.update(state="infrastructure_failure", detail=str(exc),
                      wheels=[], sdists=[])
        _write(args.report, report)
        print("INFRASTRUCTURE FAILURE: " + str(exc), file=sys.stderr)
        return INFRA

    checked = ([check_wheel(w) for w in wheels] +
               [check_sdist(s) for s in sdists])
    report.update(state="pass" if all(c["ok"] for c in checked) else "regression",
                  wheels=[c for c in checked if c["artifact"].endswith(".whl")],
                  sdists=[c for c in checked if c["artifact"].endswith(".tar.gz")])
    _write(args.report, report)

    for c in checked:
        mark = "ok  " if c["ok"] else "MISS"
        print(mark + " " + c["artifact"] + "  " + str(c["members"]) + " members")
        for m in c["missing"]:
            print("       missing: " + m)
    if report["state"] == "pass":
        print("PASS: both artifacts contain what an install needs")
        return PASS
    print("REGRESSION: the build succeeded and the artifacts are incomplete",
          file=sys.stderr)
    return REGRESSION


def _write(path, report):
    if not path:
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
