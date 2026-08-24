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

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT / "tests")
    env.setdefault("RDEBUG_RENDERDOC_PATH",
                   r"D:\renderdoc_no_mcp\renderdoc\x64\Release\pymodules")
    env["RDEBUG_TELEMETRY"] = str(harness.REPORTS_DIR / "telemetry.jsonl")

    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests" / "workload"), top_level_dir=str(ROOT))
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)

    harness.REPORT["corpus"] = [
        {"path": c["path"], "draws": c["draws"], "tier": c["tier"]}
        for c in harness.CORPUS
    ]
    correctness_ok = all(r["pass"] for r in harness.REPORT["correctness"].values())
    reliability_ok = all(
        v == 0 for k, v in harness.REPORT["reliability"].items()
        if k != "failedRecoveries"
    )
    non_debug_p95 = [
        st["p95"] for tool, st in harness.latency_summary().items()
        if tool != "debug_pixel" and st["p95"] is not None
    ]
    perf_ok = all(p < 100 for p in non_debug_p95) if non_debug_p95 else True
    gate = (correctness_ok and reliability_ok and perf_ok
            and not result.failures and not result.errors)

    payload = harness.write_report(gate)
    harness.print_summary(payload)
    print("\nreport:", harness.REPORTS_DIR / "workload-report.json")
    sys.exit(0 if gate else 1)


if __name__ == "__main__":
    main()
