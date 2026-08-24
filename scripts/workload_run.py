"""One-shot workload runner: corpus -> unittest workloads -> report + gate."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.workload import harness  # noqa: E402


def main():
    if not harness.CORPUS:
        print("corpus empty; generating ...", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "workload_corpus.py")],
                       check=True)
        harness.CORPUS = harness.discover_corpus()
        for c in harness.CORPUS:
            harness.REPORT["corpus"].append(
                {"path": c["path"], "draws": c["draws"], "tier": c["tier"]})

    # Tests execute in-process and isolated scenarios inherit os.environ, so
    # the environment must be applied here -- an unused env dict produced a
    # vacuous PASS once every workload class skipped (0 queries, gate PASS).
    os.environ.setdefault(
        "RDEBUG_RENDERDOC_PATH",
        r"D:\renderdoc_no_mcp\renderdoc\x64\Release\pymodules")
    os.environ["PYTHONPATH"] = (
        str(ROOT / "src") + os.pathsep + str(ROOT / "tests")
        + os.pathsep + os.environ.get("PYTHONPATH", ""))
    os.environ["RDEBUG_TELEMETRY"] = str(harness.REPORTS_DIR / "telemetry.jsonl")

    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests" / "workload"), top_level_dir=str(ROOT))
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)

    harness.REPORT["corpus"] = [
        {"path": c["path"], "draws": c["draws"], "tier": c["tier"]}
        for c in harness.CORPUS
    ]
    ran_queries = sum(harness.REPORT["queries"].values())
    ran_correctness = len(harness.REPORT["correctness"])

    correctness_ok = all(r["pass"] for r in harness.REPORT["correctness"].values())
    reliability_ok = all(
        v == 0 for k, v in harness.REPORT["reliability"].items()
        if k != "failedRecoveries"
    )
    # Perf gate guards the cheap-query population only (a warm-regression
    # sentinel: baseline p95 ≈ 9ms resource / ≈ 100–180ms background pixel).
    # Deep covered-pixel replay cost is seconds by nature and dominated by
    # pixel modification count -- mixing it into one blanket threshold made
    # the gate structurally unpassable (ff18fee run already exceeded it at
    # 156.8ms). Deep-trace latency stays in the report as observation only.
    # Decision recorded in docs/validation/phase5d-workload.md (2026-08-25).
    summary = harness.latency_summary()

    def p95(tool):
        return (summary.get(tool) or {}).get("p95")

    resource_p95, bg_p95 = p95("trace_resource"), p95("trace_pixel_bg")
    perf_ok = (resource_p95 is not None and resource_p95 < 100
               and bg_p95 is not None and bg_p95 < 250)
    # Vacuous-run guard: a suite where nothing executed must never pass.
    non_vacuous = ran_queries > 0 and ran_correctness > 0 and result.testsRun > 0
    gate = (non_vacuous and correctness_ok and reliability_ok and perf_ok
            and not result.failures and not result.errors)

    payload = harness.write_report(gate)
    harness.print_summary(payload)
    print("\nreport:", harness.REPORTS_DIR / "workload-report.json")
    sys.exit(0 if gate else 1)


if __name__ == "__main__":
    main()
