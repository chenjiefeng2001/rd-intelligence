"""End-to-end control for the CI pipeline adapter.

It lives in tests/pipeline, which no gate discovers, and it is opt-in. Both
restrictions were forced by a crash rather than chosen for tidiness.

The test was first placed in tests/integration, because that is where the
gates run. From there it re-entered the pipeline, which runs the integration
suite, which re-entered the test. A skip guard helped only while the gate
marker was set; a plain unittest discovery had no marker and the integration
process died with 0xC0000005, the access violation DESIGN_SPEC 2.9 already
records for this class of problem. A test that re-enters the pipeline from
inside a suite the pipeline executes is therefore unsound here, because that
suite's purpose is to hold live replay runtimes.

It is opt-in via RDEBUG_RUN_PIPELINE_E2E for the same reason: a discovery
run should not silently pull the whole gate orchestration into whatever suite
someone pointed it at.

The expected result is the honest resting state: NEEDS_REVIEW at exit 4,
because section 4 gate 4 has no executable check. A control demanding exit 0
would be demanding the pipeline make a false claim.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from rdebug.adapter.locator import find_module_dir

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


@unittest.skipUnless(find_module_dir() is not None,
                     "renderdoc module not importable")
@unittest.skipUnless(
    os.environ.get("RDEBUG_RUN_PIPELINE_E2E") == "1",
    "opt in with RDEBUG_RUN_PIPELINE_E2E=1; running the whole gate pipeline "
    "from inside a discovered suite re-enters that suite")
@unittest.skipUnless(
    not os.environ.get("RDEBUG_GATE_RUN"),
    "running from inside the gate this test exercises; standing down to avoid "
    "re-entering the pipeline that runs this suite")
class TestPipelineEndToEnd(unittest.TestCase):
    def _run(self):
        env = dict(os.environ)
        corpus = os.path.join(REPO_ROOT, "tests", "workload", "corpus")
        env.setdefault("RDEBUG_ISOLATION_CAPTURE_DIR", corpus)
        env.setdefault("RDEBUG_INTEGRATION_CAPTURE",
                       os.path.join(corpus, "w00016_frame11.rdc"))
        report = os.path.join(tempfile.mkdtemp(prefix="cireal_"), "r.json")
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "ci_pipeline.py"),
             "--json", report, "--timeout", "3000"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=3600,
        )
        return proc, report

    def test_exit_code_is_four_and_report_is_complete(self):
        proc, report_path = self._run()
        with open(report_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(
            proc.returncode, 4,
            f"the honest resting state is NEEDS_REVIEW because gate 4 has no "
            f"executable check; got {proc.returncode}",
        )
        self.assertEqual(data["overall"]["status"], "NEEDS_REVIEW")
        self.assertEqual(data["overall"]["conclusion"], "neutral")
        self.assertFalse(data["release_blocking_enabled"])
        names = {g["gate"] for g in data["gates"]}
        for expected in ("unit", "transport", "integration",
                         "boundary_audit", "cold_warm_equivalence",
                         "fork_integrity", "benchmark_archive"):
            self.assertIn(expected, names)
        for row in data["gates"]:
            for field in ("gate", "state", "outcome", "required_execution",
                          "attempted", "executed", "command", "detail"):
                self.assertIn(field, row, row.get("gate"))


if __name__ == "__main__":
    unittest.main()
