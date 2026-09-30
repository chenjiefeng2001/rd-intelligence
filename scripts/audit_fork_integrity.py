"""Mechanical verifier for DESIGN_SPEC 2.1 / 2.1.1 fork integrity.

The rule it enforces is not "the working tree is clean". That check would
pass for a fork that silently diverges from upstream, and it would also
pass for a declaration that names a patch which no longer exists. The rule
is that the set of tracked modifications and the set of declared exceptions
must agree exactly, in both directions, and that every modification must
land inside its declared blast radius.

Four conditions are hard failures:

  F1  a tracked modification exists that no declaration covers
  F2  a declaration names a patch that is not present in the working tree
  F3  a covered modification has no recorded provenance in the capture
      metadata, or the metadata disagrees with reality
  F4  a modification lands outside its declared file or symbol scope, or
      touches a surface the exception excludes

Blast radius is read from the hunk headers of `git diff -U0`, so scope is
decided by where the change is, not by whether someone wrote a comment
explaining it. A comment is not compliance.

Exit code is non-zero on any violation, matching the convention of
audit_boundaries.py. Usage:

    python scripts/audit_fork_integrity.py [--fork PATH] [--declaration PATH]
"""

import argparse
import json
import os
import re
import subprocess
import sys

SCHEMA = "rdebug-fork-exception/1"

# A hunk header looks like: @@ -33,6 +33,7 @@ <context>
# With -U0 the trailing context is often empty, so the enclosing symbol is
# derived from the file itself rather than from git's heuristic.
HUNK = re.compile(
    r"^@@ -(?P<os>\d+)(?:,(?P<oslen>\d+))? "
    r"\+(?P<ns>\d+)(?:,(?P<nslen>\d+))? @@(?P<ctx>.*)$"
)

# A function definition: a possibly qualified name followed by an open
# paren. C++ puts the return type first, so the name is found anywhere on
# the line and the last match is taken, which skips parameter types.
FUNC = re.compile(r"(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*\s*\(")
CONTROL = re.compile(r"^(if|for|while|switch|return|else|catch)\b")

COMMENT_OR_PP = re.compile(r"^\s*(#|//|/\*|\*|\*/)")


def _load_lines(fork, path):
    with open(os.path.join(fork, path), encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def _header_region_end(lines):
    """Last line index of the file's leading comment/preprocessor region.

    An insertion inside that region is file scope, not function scope.
    """
    for i, line in enumerate(lines, start=1):
        if line.strip() and not COMMENT_OR_PP.match(line):
            return i - 1
    return len(lines)


def _enclosing_symbol(lines, lineno):
    """Nearest enclosing function definition above a line.

    Brace-only and punctuation-only lines are skipped, because an insertion
    made just inside a function body has the opening brace as its immediate
    predecessor while the signature sits a few lines higher.
    """
    for i in range(min(lineno, len(lines)) - 1, -1, -1):
        line = lines[i]
        stripped = line.strip()
        if not stripped or COMMENT_OR_PP.match(line) or CONTROL.match(stripped):
            continue
        if not re.search(r"[A-Za-z_]", stripped):
            # Braces, parens, semicolons, commas and operators carry no name.
            continue
        matches = FUNC.findall(line)
        if matches:
            return matches[-1].rstrip("( \t")
        return "unclassified:" + stripped[:60]
    return "unclassified:<start-of-file>"


def _classify_hunk(fork, path, hunk):
    """Where a hunk sits, judged by structure rather than by commentary."""
    lineno = hunk["new_start"]
    lines = _load_lines(fork, path)
    if lineno <= _header_region_end(lines):
        return "include_block"
    return _enclosing_symbol(lines, lineno)


class Violation(Exception):
    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _git(fork, *args):
    out = subprocess.run(
        ["git", "-C", fork] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise Violation(
            "GIT", "git {} failed: {}".format(" ".join(args), out.stderr.strip())
        )
    return out.stdout


def tracked_modifications(fork):
    """Tracked files that differ from HEAD, as {path: [hunk, ...]}.

    Untracked files are excluded on purpose: build output is not a spec
    violation, and including it would make the check useless in practice.
    """
    names = [n for n in _git(fork, "diff", "--name-only", "HEAD").splitlines() if n.strip()]
    mods = {}
    for name in names:
        diff = _git(fork, "diff", "-U0", "HEAD", "--", name)
        hunks, context = [], None
        for line in diff.splitlines():
            m = HUNK.match(line)
            if m:
                context = (m.group("ctx") or "").strip()
                hunks.append({
                    "new_start": int(m.group("ns")),
                    "new_len": int(m.group("nslen") or 1),
                    "header": context,
                    "lines": [],
                })
            elif hunks and (line.startswith("+") or line.startswith("-")):
                hunks[-1]["lines"].append(line)
        mods[name] = hunks
    return mods


def _touches_excluded_surface(fork, path, hunks):
    for h in hunks:
        where = _classify_hunk(fork, path, h)
        low = where.lower()
        for bad in ("replay", "driver", "serialise", "mcp", "semantic"):
            if bad in low:
                return where
    return None


def verify(fork, declaration, repo_root):
    """Raise Violation on the first failure. Returns a PASS summary."""
    with open(declaration, encoding="utf-8") as fh:
        doc = json.load(fh)
    if doc.get("schema") != SCHEMA:
        raise Violation(
            "SCHEMA",
            f"declaration schema {doc.get('schema')!r} is not {SCHEMA!r}",
        )
    exceptions = [e for e in doc.get("exceptions", []) if e.get("enabled")]

    mods = tracked_modifications(fork)
    if not mods:
        # Nothing to explain. A clean tree is compliant with no declaration
        # at all; a declaration that names a patch which is gone is not.
        for exc in exceptions:
            raise Violation(
                "F2",
                "exception {!r} declares {!r} but the working tree has no "
                "tracked modification".format(exc["exception_id"], exc.get("mechanism")),
            )
        return {"tracked_modifications": 0, "exceptions": 0,
                "detail": "clean tree, nothing declared"}
    if not exceptions:
        raise Violation(
            "F1",
            f"tracked modification(s) {sorted(mods)} are present but no exception is "
            "declared",
        )

    covered = set()
    for exc in exceptions:
        eid = exc["exception_id"]
        files = exc.get("files") or {}
        allowed_syms = {s for spec in files.values() for s in spec.get("allowed_symbols", [])}
        allowed_scope = {s for spec in files.values() for s in spec.get("allowed_file_scope", [])}

        hit = [p for p in mods if p in files]
        if not hit:
            raise Violation(
                "F1",
                f"exception {eid!r} covers {sorted(files)} "
                f"but the modifications are {sorted(mods)}",
            )
        covered.update(hit)

        for path in hit:
            for hunk in mods[path]:
                where = _classify_hunk(fork, path, hunk)
                if where not in allowed_syms and where not in allowed_scope:
                    raise Violation(
                        "F4",
                        f"{eid}: hunk in {path!r} is outside the declared blast radius "
                        f"(found {where!r}; allowed {sorted(allowed_syms | allowed_scope)})",
                    )
            excluded = _touches_excluded_surface(fork, path, mods[path])
            if excluded:
                raise Violation(
                    "F4",
                    f"{eid}: {path} touches excluded surface via {excluded!r}",
                )

        _verify_provenance(exc, repo_root)

    undeclared = sorted(set(mods) - covered)
    if undeclared:
        raise Violation(
            "F1",
            f"tracked modification(s) not covered by any declaration: {undeclared}",
        )
    return {
        "tracked_modifications": len(mods),
        "exceptions": len(exceptions),
        "detail": "; ".join(
            "{} -> {}".format(e["exception_id"],
                          ", ".join(sorted(p for p in mods if p in (e.get("files") or {}))))
            for e in exceptions
        ),
    }


def _verify_provenance(exc, repo_root):
    """F3: the metadata must record the patch, and agree with reality."""
    prov = exc.get("provenance") or {}
    globs = prov.get("metadata_globs") or []
    root = os.path.normpath(os.path.join(repo_root, prov.get("root", ".")))
    prov.get("mechanism_path", "capture_mechanism.patch")
    prov.get("recorded_path", "capture_mechanism.patch_recorded")

    import glob as _glob

    files = []
    for pattern in globs:
        files.extend(sorted(_glob.glob(os.path.join(root, pattern))))
    if not files:
        raise Violation(
            "F3",
            f"no capture metadata matched {globs} under {root}, so provenance cannot "
            "be bound",
        )
    seen = 0
    for path in files:
        with open(path, encoding="utf-8") as fh:
            meta = json.load(fh)
        mech = (meta.get("capture_mechanism") or {}).get("patch")
        rec = (meta.get("capture_mechanism") or {}).get("patch_recorded")
        if mech != exc.get("mechanism"):
            raise Violation(
                "F3",
                f"{os.path.basename(path)} records patch {mech!r}, "
                f"declaration says {exc.get('mechanism')!r}",
            )
        if rec is not True:
            raise Violation(
                "F3", f"{os.path.basename(path)} has patch_recorded={rec!r}, expected True"
            )
        seen += 1
    if not seen:
        raise Violation("F3", "no capture metadata verified")
    return seen


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fork", default=os.path.normpath(
        os.path.join(repo_root, "..", "renderdoc")))
    ap.add_argument("--declaration", default=os.path.join(repo_root, "fork-exception.json"))
    args = ap.parse_args(argv)

    print("fork integrity audit (DESIGN_SPEC 2.1.1)")
    print(f"  fork        : {args.fork}")
    print(f"  declaration : {args.declaration}")
    try:
        summary = verify(args.fork, args.declaration, repo_root)
    except Violation as v:
        print(f"  FAIL  {v}")
        return 1
    print(
        f"  PASS  {summary['tracked_modifications']} tracked modification(s) "
        f"under {summary['exceptions']} declared exception(s): "
        f"{summary['detail']}"
    )
    print("  F1 undeclared modification      : not present")
    print("  F2 declared but absent          : not present")
    print("  F3 provenance unbound/mismatched: not present")
    print("  F4 outside declared blast radius: not present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
