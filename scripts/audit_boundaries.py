"""Mechanical boundary audit for DESIGN_SPEC.md.

Runs the machine-checkable rules and prints a PASS/FAIL table.
Non-zero exit code = violation."""

import os
import re
import sys

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
                out[rel] = open(full, encoding="utf-8").read()
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

    # 2.9 MUST NOT: transports must not construct the legacy in-process
    # multi-session SessionManager in NEW code. MCP/IDE still do. DESIGN_SPEC
    # explicitly labels them a transitional form, so this is a recorded
    # deviation rather than a failure -- but it is the single largest open
    # item in §2.9: F-1/F-2 (silent value corruption, native hang, 0xC0000005
    # from multiple live controllers) originate on exactly this path.
    legacy = []
    for path, text in transports.items():
        if re.search(r"SessionManager\s*\(", text):
            legacy.append(path)
    if legacy:
        deviation("2.9 transports still on legacy SessionManager",
                  ", ".join(legacy) + " (W1-R1 F-1/F-2 live here; "
                  "migrate to WorkerManager)")

    # 2.9 MUST NOT: the bounded-retry recovery must be driven by a
    # structured signal, not by substring-matching the error text. A query
    # error whose message contains "dead" would otherwise trigger a full
    # process recycle.
    if wm_text:
        check("2.9 recovery uses structured transient flag",
              "e.transient" in wm_text
              and "exited unexpectedly\", " not in wm_text)


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

    # Rule 2.2: Stable Core must not import transports
    violations = []
    for path, text in core.items():
        for token in ("import mcp", "from mcp", "rdebug_mcp", "rdebug_ide"):
            if token in text:
                violations.append(f"{path}: {token}")
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
