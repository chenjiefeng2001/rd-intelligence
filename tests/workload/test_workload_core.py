"""Workload A/B/I/J: determinism, cold-warm equivalence, evidence integrity,
three-state stability."""

import json
import time
import unittest

from rdebug.analysis.pixel_diff import diff_pixel
from rdebug.analysis.pixel_trace import trace_pixel
from rdebug.analysis.resource_flow import trace_resource

from . import harness
from .harness import (
    WorkloadTest,
    canonical,
    record_query,
    verify_evidence,
)


@harness.require_corpus()
class TestDeterminism(WorkloadTest):
    def test_repeated_queries_identical(self):
        caps = [harness.pick(tier_filter="S"), harness.pick(tier_filter="M")]
        caps = [c for c in caps if c]
        for cap in caps:
            with self.subTest(capture=cap["path"]):
                with self.manager.use(cap["path"]) as s:
                    plan = harness.full_plan(s, cap,
                                             with_debug=cap["draws"] <= 512)
                    first = {}
                    for name, fn in plan:
                        t0 = time.perf_counter()
                        out = fn()
                        record_query(name, (time.perf_counter() - t0) * 1000,
                                     out if isinstance(out, dict) else None,
                                     cap["path"])
                        first[name] = canonical(out)
                    for i in range(harness.ENV_DETERMINISM_N - 1):
                        for name, fn in plan:
                            out = fn()
                            record_query(name, 0.0)
                            self.assertEqual(first[name], canonical(out),
                                             f"run {i+2} diverged on {name}")
                harness.record_correctness(
                    f"determinism[{cap['tier']}:{cap['draws']} draws]",
                    True, f"{harness.ENV_DETERMINISM_N} identical runs")


@harness.require_corpus()
class TestColdWarmEquivalence(WorkloadTest):
    def test_cold_equals_warm(self):
        cap = (harness.pick(prefer_max_draws=512, tier_filter="S")
               or harness.pick())
        from rdebug.adapter.core import CaptureSession

        with CaptureSession(cap["path"]) as s:
            plan = harness.full_plan(s, cap)
            cold = {name: canonical(fn()) for name, fn in plan}

        times = []
        with self.manager.use(cap["path"]) as s:
            plan = harness.full_plan(s, cap)
            for i in range(harness.ENV_WARM_RUNS):
                for name, fn in plan:
                    t0 = time.perf_counter()
                    out = fn()
                    dt = (time.perf_counter() - t0) * 1000.0
                    times.append(dt)
                    record_query(name, dt,
                                 out if isinstance(out, dict) else None,
                                 cap["path"])
                    if i == 0:
                        self.assertEqual(cold[name], canonical(out),
                                         f"warm run diverged on {name}")
        warm_p95 = harness.percentile(times, 95)
        harness.record_correctness(
            f"cold_warm_equivalence[{cap['tier']}]", True,
            f"{harness.ENV_WARM_RUNS} warm runs, p95={warm_p95}ms")


def _first_evidence_node(node):
    if isinstance(node, dict):
        if "id" in node and "operation" in node:
            return node
        for v in node.values():
            found = _first_evidence_node(v)
            if found is not None:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _first_evidence_node(v)
            if found is not None:
                return found
    return None


@harness.require_corpus()
class TestEvidenceIntegrity(WorkloadTest):
    def test_all_evidence_verifiable(self):
        cap = harness.pick(prefer_max_draws=256)
        violations = []
        with self.manager.use(cap["path"]) as s:
            spec = harness.spec_for(s, cap["draws"])
            payloads = [
                trace_pixel(s, *spec["covered"], max_draws=8),
                trace_resource(s, spec["texture"]),
                diff_pixel(s, spec["covered"], spec["background"]).to_dict(),
            ]
        for p in payloads:
            record_query("evidence_sweep", 0.0, p, cap["path"])
            violations += verify_evidence(p, cap["path"])

        tampered = json.loads(json.dumps(payloads[0]))
        node = _first_evidence_node(tampered)
        node["id"] = "0" * 12
        violations += verify_evidence(tampered, cap["path"])
        self.assertTrue(any(v["issue"] == "id_mismatch" for v in violations),
                        "tampered evidence id must be detected")

        real_violations = [v for v in violations if v["issue"] != "id_mismatch"]
        self.assertEqual(real_violations, [])
        harness.record_correctness("evidence_integrity", True,
                                   f"{len(payloads)} payloads verified")


@harness.require_corpus()
class TestThreeState(WorkloadTest):
    def test_states_never_flip(self):
        cap = (harness.pick(prefer_max_draws=512, tier_filter="S")
               or harness.pick())
        cases = []
        with self.manager.use(cap["path"]) as s:
            spec = harness.spec_for(s, cap["draws"])
            for _i in range(20):
                cases.append(("SAME", diff_pixel(
                    s, spec["covered"], spec["covered"]).to_dict()))
                cases.append(("DIFFERENT", diff_pixel(
                    s, spec["covered"], spec["background"]).to_dict()))
        for expected, payload in cases:
            self.assertIn(payload["comparison"],
                          ("same", "different", "unknown"))
            if expected == "SAME":
                self.assertEqual(payload["comparison"], "same")
            if expected == "DIFFERENT":
                self.assertEqual(payload["comparison"], "different")
            for ly in payload["layers"]:
                self.assertIn(ly["status"], ("same", "different", "unknown"))
        harness.record_correctness("three_state", True,
                                   f"{len(cases)} cases stable")


if __name__ == "__main__":
    unittest.main()
