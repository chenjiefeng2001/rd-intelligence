"""Mechanical boundary audit for DESIGN_SPEC.md.

Runs the machine-checkable rules and prints a PASS/FAIL table.
Non-zero exit code = violation."""

import ast
import io
import os
import re
import sys
import tokenize

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
CHECKS = []
DEVIATIONS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


def deviation(name, detail):
    """A gap DESIGN_SPEC explicitly permits, recorded so it stays visible.

    Not a violation, so it must not fail the audit -- but it also must not
    be able to disappear. A deviation means "the spec allows this today and
    it still has to be closed".
    """
    DEVIATIONS.append((name, detail))


def read(path):
    full = os.path.join(ROOT, path)
    with open(full, encoding="utf-8") as f:
        return f.read()


def walk(package):
    base = os.path.join(ROOT, package)
    out = {}
    for dirpath, _dirs, files in os.walk(base):
        for fn in files:
            if fn.endswith(".py"):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT).replace("\\", "/")
                # utf-8-sig: rdebug_mcp/server.py carries a BOM. Python's
                # import machinery tolerates it, but ast.parse() does not,
                # so anything that parses these sources needs this.
                out[rel] = open(full, encoding="utf-8-sig").read()
    return out


def audit_29(core, transports):
    """DESIGN_SPEC §2.9 Runtime Isolation rules.

    §2.9 was the newest normative section and the only one with no
    mechanical check, so a violation could not be caught by the audit. These
    checks are deliberately static (naming and layering), not behavioural:
    behavioural coverage lives in tests/unit/test_worker_manager.py.
    """

    # 2.9 MUST: memory thresholds and their reported fields use
    # private-memory naming. An RSS-named field is either an ambiguous name
    # or -- worse -- a gate fed by working set, which OS trimming makes
    # unreliable (observed baseline drift up to -35MB).
    wm_path = "rdebug/worker_manager.py"
    wm_text = core.get(wm_path, "")
    if wm_text:
        reported = set(re.findall(r'"(\w*(?:rss|memory)\w*)"\s*:', wm_text))
        ambiguous = sorted(
            f for f in reported
            if "rss" in f.lower() and "working_set" not in f.lower())
        check("2.9 no RSS-named reported field in worker_manager",
              not ambiguous, ", ".join(ambiguous))

        # The policy must expose a private-memory-delta threshold.
        check("2.9 private-memory-delta threshold exists",
              "max_private_memory_delta_mb" in wm_text)

        # 2.9 MUST: a missing private-memory metric must not fall back to
        # RSS as a gate. The RSS fallback is allowed for the *current*
        # reading; the baseline must stay None so the delta trigger is
        # inert rather than silently switching metrics.
        check("2.9 baseline never falls back to RSS",
              not re.search(
                  r"mem_baseline\s*=\s*self\.rss_bytes\(\)", wm_text))

        # 2.9 MUST: the baseline must be captured on the spawn path, not
        # after a return. Regression: it once sat after `return msg` in
        # _death_message(), so it stayed None and the delta trigger could
        # never fire.
        check("2.9 baseline captured on spawn",
              "_capture_baseline()" in wm_text)

    # 2.9 MUST: one worker process owns one runtime. The worker module must
    # refuse a capture that is not the one it was started with, and must
    # never be imported by Stable Core. worker_manager.py is exempt: it is
    # the launcher and legitimately names the worker as a subprocess module
    # (-m rdebug.workers) without importing it.
    workers_path = "rdebug/workers.py"
    workers_text = core.get(workers_path, "")
    if workers_text:
        check("2.9 worker rejects foreign captures",
              "requested" in workers_text and "worker bound to" in workers_text)
    violations = []
    for path, text in core.items():
        if path in (workers_path, wm_path):
            continue
        if re.search(r"rdebug\.workers|from rdebug import workers", text):
            violations.append(path)
    check("2.9 worker protocol not imported into Stable Core", not violations,
          ", ".join(violations))

    # 2.9 MUST NOT: the bounded-retry recovery must be driven by a
    # structured signal, not by substring-matching the error text. A query
    # error whose message contains "dead" would otherwise trigger a full
    # process recycle.
    if wm_text:
        check("2.9 recovery uses structured transient flag",
              "e.transient" in wm_text
              and "exited unexpectedly\", " not in wm_text)

    # 2.9 MUST NOT: transports must not construct the legacy in-process
    # multi-session SessionManager. MCP/IDE still do. §2.9 labels them a
    # transitional form, so this is a recorded deviation rather than a
    # failure -- but it is the single largest open item in §2.9: F-1/F-2
    # (silent value corruption, native hang, 0xC0000005 from multiple live
    # controllers) originate on exactly this path.
    #
    # GATE A. AST-based, so citing the file in a comment or docstring does
    # not fire. Flips from deviation to a hard check at M1.3, when MCP is
    # wired to WorkerManager.
    gate_a_hits = []
    for path, text in sorted(transports.items()):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else getattr(fn, "attr", None))
                if name == "SessionManager":
                    gate_a_hits.append(f"{path}:{node.lineno} constructs "
                                       f"SessionManager")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                names = [a.name for a in node.names]
                if "session_cache" in mod or "SessionManager" in names:
                    gate_a_hits.append(f"{path}:{node.lineno} imports "
                                       f"{mod or names}")
    if gate_a_hits:
        deviation("2.9 GATE A: transports still construct SessionManager",
                  "; ".join(gate_a_hits) + " -- becomes a hard check at M1.3")

    # 2.9 MUST: a process must not hold a second live ReplayController.
    # core.py holds _REPLAY_LIFECYCLE as a process global, so N sessions
    # share one replay runtime with N controllers coexisting.
    #
    # GATE B is a PROXY, and is labelled as one: it can only check that the
    # enforcement exists, not that the invariant holds. The invariant itself
    # is a runtime property and is proven directly by
    # tests/integration/test_runtime_isolation.py, whose
    # test_transport_path_keeps_one_controller is a tracked expectedFailure
    # until the migration lands. Flips to a hard check at M1.3.
    core_py = core.get("rdebug/adapter/core.py", "")
    if core_py and not _has_second_controller_guard(core_py):
        deviation("2.9 GATE B: no guard against a second live controller",
                  "rdebug/adapter/core.py CaptureSession.__init__ has no "
                  "branch that raises when a replay runtime is already live "
                  "in this process -- becomes a hard check at M1.3. PROXY: "
                  "the runtime invariant is proven by "
                  "tests/integration/test_runtime_isolation.py")

    audit_failure_shapes(core, transports)


def _has_second_controller_guard(capture_session_src):
    """True when __init__ refuses to open a second controller.

    The invariant is "no second live ReplayController in a process", not
    "the session counter must disappear" -- a counter plus a refusal is
    correct, and a first version of this check that demanded the counter be
    removed was rejected by its own negative control.
    """
    try:
        tree = ast.parse(capture_session_src)
    except SyntaxError:
        return False
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
    if fn is None:
        return False
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "_REPLAY_LIFECYCLE" not in test or "sessions" not in test:
            continue
        if any(isinstance(b, ast.Raise) for b in node.body):
            return True
    return False


# Files where a swallowed exception is acceptable. Each needs a reason.
_SWALLOW_ALLOWLIST = {
    # §2.8: telemetry MUST be best-effort and MUST NOT change query behaviour.
    "rdebug/observability.py": "2.8 telemetry is best-effort by mandate",
}


def audit_failure_shapes(core, transports):
    """§2.5: a failure to look must not be reported as an observation.

    The three-state contract only holds if "I could not look" is
    distinguishable from "I looked and found nothing". The recurring
    violation is an `except` that substitutes a benign-looking value (an
    empty list, an empty string) for a failed lookup; that value then
    compares equal to another empty value and the caller reports `same`.

    Swallowing into None is fine -- None is what `unknown` is built from --
    and so is a handler that only guards cleanup. What is not fine is
    inventing an empty observation out of a failure.

    AST-based: a regex version of this check passed while the very bug it
    was written for was still present, so the pattern is matched
    structurally instead. A handler may opt out with a comment carrying
    one of _EMPTY_IS_HONEST markers on the same or the preceding line.
    """
    semantic = {
        path: text for path, text in core.items()
        if path.startswith(("rdebug/analysis", "rdebug/adapter",
                            "rdebug/query", "rdebug/model.py",
                            "rdebug/evidence.py", "rdebug/ci.py"))
    }
    violations = []
    for path, text in sorted(semantic.items()):
        if path in _SWALLOW_ALLOWLIST:
            continue
        comments = _comment_lines(text)
        tree = ast.parse(text)
        for handler in (n for n in ast.walk(tree)
                        if isinstance(n, ast.ExceptHandler)):
            for node in ast.walk(handler):
                if not isinstance(node, ast.Assign):
                    continue
                if not any(isinstance(t, ast.Name) for t in node.targets):
                    continue
                if not _is_empty_observation(node.value):
                    continue
                window = comments.get(node.lineno, "") + " " + \
                    comments.get(node.lineno - 1, "")
                if not re.search(_EMPTY_IS_HONEST, window, re.I):
                    violations.append(
                        f"{path}:{node.lineno} -> {ast.unparse(node.value)}")
    check("2.5 failed lookups are not reported as empty observations",
          not violations, "; ".join(violations))

    # 2.6: transports must turn runtime errors into a JSON body. An
    # exception escaping the request handler drops the connection, which a
    # client cannot distinguish from a crash. The precise failure mode is a
    # dispatcher that only catches the domain error while its request
    # parsers index into the query dict directly: a missing parameter then
    # raises KeyError and escapes.
    #
    # Scoped to the dispatch function's own handlers. A file-level scan for
    # "somewhere there is an except KeyError" is defeated by an unrelated
    # handler elsewhere in the module -- which is exactly what happened
    # when this was first written, so it passed while the bug was present.
    bad = []
    for path, text in sorted(transports.items()):
        tree = ast.parse(text)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            if not re.match(r"(route|dispatch|handle|_safe|wrapper)$",
                            fn.name):
                continue
            handlers = [h.type for st in ast.walk(fn)
                        if isinstance(st, ast.Try) for h in st.handlers]
            names = set()
            for h in handlers:
                if h is None:
                    names.add("BARE")
                elif isinstance(h, ast.Tuple):
                    names.update(e.id for e in h.elts
                                 if isinstance(e, ast.Name))
                elif isinstance(h, ast.Name):
                    names.add(h.id)
            if not names:
                continue
            if names & {"Exception", "BARE"}:
                continue  # catch-all converts anything
            if not names & {"KeyError", "IndexError", "ValueError"}:
                bad.append(f"{path}:{fn.name} ({', '.join(sorted(names))})")
    check("2.6 transports convert query errors to a response body",
          not bad, "; ".join(bad))


_EMPTY_IS_HONEST = (r"not the same|distinguish|unknown|could not|failed|"
                    r"absent|does not mean|≠|error|empty is|honest|no such")


def _is_empty_observation(node):
    """True for a literal that reads as a successful empty observation."""
    if isinstance(node, (ast.List, ast.Dict, ast.Set, ast.Tuple)):
        return not (node.elts if hasattr(node, "elts") else node.keys)
    if isinstance(node, ast.Constant):
        return node.value in ("", 0) and not isinstance(node.value, bool)
    return False


def _comment_lines(text):
    out = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string
    except Exception:
        pass
    return out


def _imported_modules(text):
    """Absolute module names actually imported by `text`.

    Comments, docstrings and string literals are excluded because the
    module name is a value to the import machinery, not to the reader --
    citing a file in prose is not a dependency on it.
    """
    mods = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return mods
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import; resolved within the package
                continue
            if node.module:
                mods.add(node.module)
                for alias in node.names:
                    mods.add(f"{node.module}.{alias.name}")
    return mods


def main():
    core = {p: t for p, t in walk("rdebug").items()}
    mcp = walk("rdebug_mcp")
    ide = walk("rdebug_ide")
    transports = {**mcp, **ide}

    forbidden_api = ["ReplayController", "PixelHistory(", "GetUsage",
                     "DebugPixel", "InitialiseReplay", "import renderdoc"]

    # Rule 2.2: renderdoc import only inside adapter/
    violations = []
    for path, text in core.items():
        if "import renderdoc" in text and not path.startswith("rdebug/adapter/"):
            violations.append(path)
    check("2.2 renderdoc import isolated to adapter/", not violations,
          ", ".join(violations))

    # Rule 2.2: Stable Core must not import transports.
    #
    # AST-based. The previous version was a substring scan for "rdebug_mcp"
    # / "rdebug_ide", which cannot tell an import from a docstring that
    # *cites* the file it found a bug in -- so documenting the
    # WorkerError-inheritance fix in worker_manager.py's own docstring turned
    # this check red. A check that punishes writing down what you learned is
    # a check that will be worked around.
    violations = []
    for path, text in core.items():
        for mod in _imported_modules(text):
            head = mod.split(".")[0]
            if head in ("mcp", "rdebug_mcp", "rdebug_ide"):
                violations.append(f"{path}: {mod}")
    check("2.2 Stable Core has no transport dependency", not violations,
          "; ".join(violations))

    # Rule 2.2: no LLM/HTTP SDKs anywhere in src
    violations = []
    for path, text in {**core, **transports}.items():
        for token in ("openai", "anthropic", "httpx", "import requests"):
            if token in text.lower() and token != "import requests":
                violations.append(f"{path}: {token}")
            elif token == "import requests" and token in text:
                violations.append(f"{path}: {token}")
    check("2.2 no LLM/HTTP SDK dependency", not violations,
          "; ".join(violations))

    # Rule 2.2: semantic layers must not import observability
    violations = []
    for path, text in core.items():
        if any(path.startswith(p) for p in
               ("rdebug/analysis", "rdebug/adapter", "rdebug/query")):
            if "observability" in text:
                violations.append(path)
        if os.path.basename(path) in ("model.py", "evidence.py", "ci.py"):
            if "observability" in text:
                violations.append(path)
    check("2.8 observability not imported by semantic layers", not violations,
          ", ".join(violations))

    # Rule 2.6: transports free of RenderDoc API identifiers
    violations = []
    for path, text in transports.items():
        for token in forbidden_api:
            if token in text:
                violations.append(f"{path}: {token}")
    check("2.6 transports free of RenderDoc API", not violations,
          "; ".join(violations))

    # Rule 2.6: transports import only semantic four from rdebug.analysis
    allowed = re.compile(
        r"from rdebug\.analysis\.(pixel_trace|resource_flow|shader_trace|pixel_diff)"
        r" import (trace_pixel|trace_resource|debug_pixel|diff_pixel)"
    )
    violations = []
    for path, text in transports.items():
        for line in text.splitlines():
            if "from rdebug.analysis" in line:
                if not allowed.match(line.strip()):
                    violations.append(f"{path}: {line.strip()}")
    check("2.6 transports import only Semantic API v1", not violations,
          "; ".join(violations))

    # Rule 2.6: transports must not import adapter directly
    # (session lifecycle goes through rdebug.session_cache / lazy default factory)
    violations = []
    for path, text in transports.items():
        if "rdebug.adapter" in text and "CaptureSession" not in text:
            violations.append(path)
    check("2.6 transports do not deep-import adapter", not violations,
          "; ".join(violations))

    # Rule 2.8: telemetry default off
    os.environ.pop("RDEBUG_TELEMETRY", None)
    sys.path.insert(0, ROOT)
    from rdebug import observability

    check("2.8 telemetry default off", observability.record("audit") is False)

    audit_29(core, transports)

    width = max(len(name) for name, _ok, _d in CHECKS) + 3
    failed = 0
    for name, ok, detail in CHECKS:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"{mark}  {name.ljust(width)}{detail}")
    if DEVIATIONS:
        print()
        for name, detail in DEVIATIONS:
            print(f"DEVIATION  {name}\n            {detail}")
    print()
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} boundary checks passed"
          + (f"; {len(DEVIATIONS)} recorded deviation(s)" if DEVIATIONS
             else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
