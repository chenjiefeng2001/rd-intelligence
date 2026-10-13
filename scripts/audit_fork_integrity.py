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


#: An external artefact the declaration names is simply not here. Not a
#: statement about the work: CAPTURE-CORPUS-CONTRACT section 5 forbids turning
#: an absence into REGRESSION. Marked at the raise site rather than recovered
#: from the message, because a string match would guess.
ABSENCE_EXTERNAL = "absence_external"
VIOLATION = "violation"


class Violation(Exception):
    def __init__(self, code, detail, kind=VIOLATION):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.kind = kind


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
    scope = []
    for exc in exceptions:
        files = exc.get("files") or {}
        hit = [p for p in mods if p in files]
        covered.update(hit)
        scope.append((exc, files, hit))

    # Order matters when a declaration is wrong in both directions at once.
    # An undeclared modification is the primary finding: it is a change in the
    # fork that nobody claims. A declaration naming a modification that is not
    # there is a secondary fact about the declaration, and reporting it first
    # would hide the breach behind bookkeeping. F1 is also decided before any
    # provenance check, deliberately: provenance used to run inside the loop
    # above, so a declaration whose metadata had gone missing reported F3 and
    # the real violation -- a file no declaration covers -- never surfaced.
    # A gate that reports the wrong code for a real breach is not auditing it.
    undeclared = sorted(set(mods) - covered)
    if undeclared:
        raise Violation(
            "F1",
            f"tracked modification(s) not covered by any declaration: {undeclared}",
        )

    for exc, files, hit in scope:
        eid = exc["exception_id"]
        if not hit:
            # F2, not F1. This is "a declaration names a patch that is not
            # present in the working tree", which is what F2 was defined to
            # mean at the top of this file. F1 is the opposite, and is decided
            # above from the set difference. With one exception the two
            # situations coincide and the code could not tell them apart; with
            # two they do not. It matters now: the sibling checkout carries the
            # driver fix as a commit, so it is absent from the working tree
            # this reads, and reporting that as an undeclared modification
            # would name a file the fork never touched.
            raise Violation(
                "F2",
                f"exception {eid!r} declares {sorted(files)} but no such "
                f"modification is present in the working tree {sorted(mods)}",
            )

        allowed_syms = {s for spec in files.values()
                        for s in spec.get("allowed_symbols", [])}
        allowed_scope = {s for spec in files.values()
                         for s in spec.get("allowed_file_scope", [])}
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

    for exc in exceptions:
        _verify_provenance(exc, fork, repo_root)

    return {
        "tracked_modifications": len(mods),
        "exceptions": len(exceptions),
        "detail": "; ".join(
            "{} -> {}".format(e["exception_id"],
                          ", ".join(sorted(p for p in mods if p in (e.get("files") or {}))))
            for e in exceptions
        ),
    }


def _verify_patch_identity(exc, fork, repo_root):
    """F3: the patch artefact and the base it applies to must be the real ones.

    Three facts, all optional in the declaration so a synthetic fixture that
    declares none is unaffected, and all enforced when declared:

      the artefact named by `patch_artifact` exists and hashes to
      `patch_sha256`; the fork's HEAD is `base_commit`; and every file the fork
      differs from `base_commit` by is one the declaration covers.

    The third is the one that matters most and the reason this exists at all.
    tracked_modifications compares the working tree against HEAD, so it is blind
    to anything already committed. That check is exactly the one this module's
    own docstring disclaims -- "that check would pass for a fork that silently
    diverges from upstream". Reproduced against a real fork carrying an unpushed
    commit that touches renderdoc/driver/, a surface the declaration lists as
    excluded: the working tree showed only the declared patch, the driver commit
    was invisible, and the verifier returned PASS.
    """
    prov = exc.get("provenance") or {}
    artifact = prov.get("patch_artifact")
    want_sha = prov.get("patch_sha256")
    base = prov.get("base_commit")

    if artifact:
        path = artifact if os.path.isabs(artifact) else os.path.join(repo_root, artifact)
        if not os.path.isfile(path):
            raise Violation(
                "F3",
                f"declared patch artefact {artifact!r} does not exist, so the "
                f"patch this exception names cannot be identified",
            )
        import hashlib
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        if want_sha and digest != want_sha:
            raise Violation(
                "F3",
                f"patch artefact {artifact} hashes to {digest}, declaration "
                f"says {want_sha}",
            )

    if base:
        head = _git(fork, "rev-parse", "HEAD").strip()
        if head != base:
            raise Violation(
                "F3",
                f"fork HEAD is {head[:12]} but the declaration pins "
                f"{base[:12]}; a commit past the base is not covered by any "
                f"declaration, because a committed change is invisible to the "
                f"working-tree comparison",
            )


def _verify_provenance(exc, fork, repo_root):
    """F3: dispatch on the identity facts the declaration actually carries.

    Two kinds of provenance exist and they are not interchangeable. A capture
    exception is bound to a capture corpus: the metadata must exist, must name
    the same mechanism, and must record the patch as applied. A driver
    lifecycle fix has no capture corpus at all; its provenance is a pinned
    patch artefact, its digest and a pinned base.

    Forcing the second kind through the first is what previously made a
    driver-only exception unexpressible: it could only be declared by
    fabricating capture-corpus metadata, which merges two identities, or by
    weakening F3 for everything, which weakens the capture exception too.
    Neither is necessary, so neither is done.

    The dispatch is deliberately not an either/or. Declaring both runs both.
    Declaring neither is F3, because a declaration that omits its identity
    fields is not thereby exempt from proving them. Declaring the patch triple
    partially is F3 for the same reason: two of three fields are an identity
    nobody can verify.
    """
    prov = exc.get("provenance") or {}
    globs = prov.get("metadata_globs") or []
    patch_fields = ("patch_artifact", "patch_sha256", "base_commit")
    declared = [f for f in patch_fields if prov.get(f)]

    if declared and len(declared) != len(patch_fields):
        raise Violation(
            "F3",
            f"exception {exc.get('exception_id')!r} declares "
            f"{declared} but not {sorted(set(patch_fields) - set(declared))}; "
            "a partial patch identity cannot be verified, so it is not treated "
            "as one",
        )
    if not globs and not declared:
        raise Violation(
            "F3",
            f"exception {exc.get('exception_id')!r} declares no provenance: "
            "neither capture metadata globs nor a patch identity, so nothing "
            "binds it to reality",
        )

    # Patch identity first, then capture evidence. An exception can be wrong
    # both ways, and only one reason is reported. Fork identity is the more
    # urgent fact -- it says which fork this is -- and reporting the weaker
    # evidence gap first would bury the base divergence underneath it.
    if declared:
        _verify_patch_identity(exc, fork, repo_root)
    if globs:
        _verify_capture_metadata(exc, repo_root)


def _verify_capture_metadata(exc, repo_root):
    """F3: the metadata must record the patch, and agree with reality."""
    prov = exc.get("provenance") or {}
    globs = prov.get("metadata_globs") or []
    root = os.path.normpath(os.path.join(repo_root, prov.get("root", ".")))

    import glob as _glob

    files = []
    for pattern in globs:
        files.extend(sorted(_glob.glob(os.path.join(root, pattern))))
    if not files:
        raise Violation(
            "F3",
            f"no capture metadata matched {globs} under {root}, so provenance cannot "
            "be bound",
            kind=ABSENCE_EXTERNAL,
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
    _verify_named_evidence(exc, root)
    return seen


def _verify_named_evidence(exc, root):
    """F3: every path the declaration names as evidence must actually exist.

    These two lines used to be here, doing nothing:

        prov.get("mechanism_path", "capture_mechanism.patch")
        prov.get("recorded_path", "capture_mechanism.patch_recorded")

    Bare expressions. The keys were read and the values discarded, so a
    declaration could name evidence that does not exist and still pass. On the
    real declaration that is not hypothetical: both files are absent from
    rdebug-validation, and the exception verified anyway.

    The contract states the rule this was supposed to implement --
    "patch_recorded agrees with patch presence"
    (docs/A1-FORK-INTEGRITY-CONTRACT.md line 74). Agreement needs both sides.
    Only the recorded side was ever read.

    Presence is what is checked here, not content. Nothing in the repository
    fixes a format for either artefact, and inventing one would be a guess
    wearing a check's clothing.
    """
    prov = exc.get("provenance") or {}
    for key in ("mechanism_path", "recorded_path"):
        rel = prov.get(key)
        if not rel:
            continue
        path = rel if os.path.isabs(rel) else os.path.join(root, rel)
        if not os.path.isfile(path):
            raise Violation(
                "F3",
                f"declaration names {key}={rel!r} as provenance evidence, but "
                f"{rel!r} does not exist under {root}; a declaration that "
                f"names evidence it cannot produce is not verified evidence",
                kind=ABSENCE_EXTERNAL,
            )


def _outcome_for(v, declaration):
    """INFRASTRUCTURE_FAILURE or REGRESSION, and why.

    release_gate maps any non-zero gate exit to REGRESSION. That is right for a
    gate that ran and found the work wrong, and wrong here: the commonest
    reason this audit fails on a clean machine is that the external capture
    evidence it binds to is not present. CAPTURE-CORPUS-CONTRACT section 5
    forbids translating an absence into REGRESSION, and DESIGN_SPEC 4.2.2 lists
    "capture does not exist -> REGRESSION" as an explicitly forbidden mapping.
    So the audit states its own four-state verdict rather than letting the exit
    code speak for it.

    The discriminator is absent-external versus present-and-disagreeing:

      the declared provenance root does not exist      -> INFRASTRUCTURE_FAILURE
      evidence is there and disagrees with us          -> REGRESSION
      an in-repo artefact has the wrong digest         -> REGRESSION
      the fork is not at the base it declares          -> REGRESSION
    """
    if getattr(v, "kind", VIOLATION) == ABSENCE_EXTERNAL:
        return ("INFRASTRUCTURE_FAILURE",
                "a declared external artefact is absent on this machine; "
                "nothing was concluded about the fork")
    return "REGRESSION", "provenance is present and disagrees with the declaration"


def _write_verdict(path, outcome, why, code=None, abort=None):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "schema": "rdebug-fork-verdict/1",
            "outcome": outcome,
            "detail": why,
            "cases": {},
            "evidence": ({"violation_code": code} if code else {})
                       | ({"abort": abort} if abort else {}),
        }, fh, indent=1)


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fork", default=os.path.normpath(
        os.path.join(repo_root, "..", "renderdoc")))
    ap.add_argument("--declaration", default=os.path.join(repo_root, "fork-exception.json"))
    ap.add_argument("--verdict-json", default=None,
                    help="write the four-state verdict here for the gate runner")
    args = ap.parse_args(argv)

    print("fork integrity audit (DESIGN_SPEC 2.1.1)")
    print(f"  fork        : {args.fork}")
    print(f"  declaration : {args.declaration}")
    try:
        summary = verify(args.fork, args.declaration, repo_root)
    except Violation as v:
        outcome, why = _outcome_for(v, args.declaration)
        print(f"  FAIL  {v}")
        print(f"  outcome  {outcome}: {why}")
        if args.verdict_json:
            _write_verdict(args.verdict_json, outcome, why, v.code, abort=str(v))
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
    if args.verdict_json:
        _write_verdict(args.verdict_json, "PASS",
                       "{} tracked modification(s) under {} declared "
                       "exception(s)".format(summary["tracked_modifications"],
                                             summary["exceptions"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
