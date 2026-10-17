"""Mechanical verifier for DESIGN_SPEC 4.4: the benchmark archive gate.

Section 4.4 says session/latency data changes must be archived under
docs/validation. Read as a process rule it has no decision path, which is why
this gate was PROCESS_ONLY. The mechanical reading has exactly one: the
archive manifest (docs/validation/benchmark-archive-manifest.json) declares
(a) the commit whose code the archived measurements were taken on and
(b) the files whose changes plausibly alter session/latency behavior. The
gate then answers one question -- does the archive still cover the code it
is attached to?

  manifest missing / unreadable / wrong schema         INFRASTRUCTURE_FAILURE
  archived_at_commit not a real ancestor of HEAD       INFRASTRUCTURE_FAILURE
  a declared archive file is absent from HEAD         INFRASTRUCTURE_FAILURE
  nothing is monitored                                 INFRASTRUCTURE_FAILURE
  a declared archive file's blob hashes differently    REGRESSION
  a monitored file changed since the archive          REGRESSION (names them)
  otherwise                                           PASS

The archive files are hashed as **blobs at HEAD**, not as working-tree
bytes. The first version hashed the files on disk, and the first remote
run caught it: bench output written through Python's Windows text-mode
stdout carried CRLF, git cleaned it to LF on the way into the tree, and
a fresh checkout on another platform hashed to something the manifest
could not describe -- the gate went REGRESSION on evidence nobody had
touched. Version-controlled content is the identity of archived evidence,
and a blob hash is the same on every checkout regardless of line-ending
configuration. The gate therefore answers a question about the tree: a
worktree edit that is not committed is outside what it verifies (git
status already reports that), and a committed change to archived
evidence is what REGRESSION exists for.

A missing manifest or archive file is infrastructure rather than regression:
a gate that cannot find its own control input has concluded nothing about the
content, the same discrimination the fork audit's F3 makes for an absent
external corpus. A modified archive file or a code change without a new
archive is the opposite: the evidence exists and disagrees with the claim
that it covers this tree, which is a content fact.

The verdict is written as its own four-state JSON (consumed by the gate
runner's verdict_json kind) rather than expressed through the exit code,
because an exit code cannot tell "the archive is stale" from "the manifest
is unreadable", and collapsing them is the G1 defect.

Usage:
    python scripts/benchmark_archive_gate.py [--repo-root PATH]
        [--manifest PATH] --json OUT
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

SCHEMA = "rdebug-benchmark-archive/1"
VERDICT_SCHEMA = "rdebug-benchmark-archive-verdict/1"

PASS = "PASS"
REGRESSION = "REGRESSION"
INFRA = "INFRASTRUCTURE_FAILURE"


class GateFailure(Exception):
    """The archive cannot be decided, or disagrees with the tree."""

    def __init__(self, outcome, detail):
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail


def _git(repo_root, *args):
    return subprocess.run(["git", "-C", repo_root, *args],
                          capture_output=True, text=True)


def verify(repo_root, manifest_path):
    """Raise GateFailure on the first problem. Returns a PASS summary."""
    if not os.path.isfile(manifest_path):
        raise GateFailure(
            INFRA,
            f"archive manifest not found: {manifest_path}; a gate that "
            "cannot find its own control input has no verdict to report")
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as e:  # noqa: BLE001 - the parse error is the whole finding
        raise GateFailure(INFRA, f"archive manifest unreadable: {e}")
    if doc.get("schema") != SCHEMA:
        raise GateFailure(
            INFRA,
            f"archive manifest schema {doc.get('schema')!r} is not {SCHEMA!r}")

    base = doc.get("archived_at_commit")
    if not isinstance(base, str) or len(base) != 40 \
            or any(c not in "0123456789abcdef" for c in base.lower()):
        raise GateFailure(
            INFRA, f"archived_at_commit {base!r} is not a full commit id")
    kind = _git(repo_root, "cat-file", "-t", base).stdout.strip()
    if kind != "commit":
        raise GateFailure(
            INFRA,
            f"archived_at_commit {base[:12]} is not a commit in this "
            "repository; the manifest describes a repository that no "
            "longer exists")
    if _git(repo_root, "merge-base", "--is-ancestor", base, "HEAD").returncode:
        raise GateFailure(
            INFRA,
            f"archived_at_commit {base[:12]} is not an ancestor of HEAD; "
            "the archive was taken on a line of history this tree does not "
            "contain")

    monitored = doc.get("monitored_paths") or []
    if not monitored:
        raise GateFailure(
            INFRA,
            "the manifest monitors no paths; a gate that watches nothing "
            "would verify coverage vacuously")
    for rel in monitored:
        # A typo'd path would make the coverage diff below silently empty,
        # which is a vacuous PASS wearing the shape of a verdict. Every
        # monitored path must therefore exist at HEAD, not merely in the
        # manifest.
        probe = _git(repo_root, "cat-file", "-e", f"HEAD:{rel}")
        if probe.returncode:
            raise GateFailure(
                INFRA,
                f"monitored path {rel} does not exist at HEAD; a watch on a "
                "path that is not there verifies nothing")

    files = doc.get("archive_files") or []
    if not files:
        raise GateFailure(
            INFRA,
            "the manifest declares no archive files; there is nothing to "
            "say the measurements are attached to")
    for rec in files:
        rel = rec.get("path")
        want = rec.get("sha256")
        if not rel or not want:
            raise GateFailure(
                INFRA,
                f"archive_files entry {rec!r} must carry both path and sha256")
        # The blob at HEAD, not the bytes on disk: the same version-controlled
        # content on every checkout, whatever the local line-ending
        # configuration does to the working tree.
        blob = subprocess.run(
            ["git", "-C", repo_root, "show", f"HEAD:{rel}"],
            capture_output=True)
        if blob.returncode:
            raise GateFailure(
                INFRA,
                f"declared archive file {rel} is absent from HEAD; a gate "
                "that cannot read its declared evidence is not a pass")
        got = hashlib.sha256(blob.stdout).hexdigest()
        if got != want:
            raise GateFailure(
                REGRESSION,
                f"archive file {rel} hashes to {got} but the manifest "
                f"declares {want}; archived evidence was modified without "
                "re-archiving")

    diff = _git(repo_root, "diff", "--name-only", base, "HEAD", "--",
                *monitored)
    changed = [ln for ln in diff.stdout.splitlines() if ln.strip()]
    if changed:
        raise GateFailure(
            REGRESSION,
            "monitored session/latency surface changed since the archived "
            f"benchmark ({base[:12]}): {sorted(changed)}; re-run "
            "scripts/bench.py, archive the raw output under docs/validation "
            "and advance archived_at_commit")

    return {
        "archived_at_commit": base,
        "monitored": len(monitored),
        "archive_files": len(files),
        "detail": "archive covers HEAD; no monitored session/latency "
                  f"change since {base[:12]}",
    }


def _write_verdict(path, outcome, detail):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "schema": VERDICT_SCHEMA,
            "outcome": outcome,
            "detail": detail,
            "cases": {},
            "evidence": {},
        }, fh, indent=1)


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=repo_root)
    ap.add_argument("--manifest", default=os.path.join(
        repo_root, "docs", "validation", "benchmark-archive-manifest.json"))
    ap.add_argument("--json", default=None,
                    help="write the four-state verdict here for the gate runner")
    args = ap.parse_args(argv)

    print("benchmark archive gate (DESIGN_SPEC 4.4)")
    print(f"  repo root  : {args.repo_root}")
    print(f"  manifest   : {args.manifest}")
    try:
        summary = verify(args.repo_root, args.manifest)
    except GateFailure as f:
        print(f"  FAIL  {f.detail}")
        print(f"  outcome  {f.outcome}")
        if args.json:
            _write_verdict(args.json, f.outcome, f.detail)
        return 1
    print(f"  PASS  {summary['detail']}")
    print(f"        monitored files: {summary['monitored']}, "
          f"archive files: {summary['archive_files']}")
    if args.json:
        _write_verdict(args.json, PASS, summary["detail"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
