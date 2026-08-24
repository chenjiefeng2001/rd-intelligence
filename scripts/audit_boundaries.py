"""Mechanical boundary audit for DESIGN_SPEC.md.

Runs the machine-checkable rules and prints a PASS/FAIL table.
Non-zero exit code = violation."""

import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


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

    width = max(len(name) for name, _ok, _d in CHECKS) + 3
    failed = 0
    for name, ok, detail in CHECKS:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"{mark}  {name.ljust(width)}{detail}")
    print()
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} boundary checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
