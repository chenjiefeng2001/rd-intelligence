"""Workload C/G: real debugging-session trajectories and random stress mix.
Latency percentiles are collected into the shared REPORT."""

import random
import time
import unittest

from rdebug.analysis.pixel_diff import diff_pixel
from rdebug.analysis.pixel_trace import trace_pixel
from rdebug.analysis.resource_flow import trace_resource
from rdebug.analysis.shader_trace import debug_pixel
from rdebug.errors import RDebugError

from . import harness
from .harness import WorkloadTest, record_query


@harness.require_corpus()
class TestDebuggingSessions(WorkloadTest):
    def test_full_trajectories(self):
        cap = harness.pick(prefer_max_draws=512, tier_filter="S") or harness.pick()
        rng = random.Random(4242)
        grid = [(320, 240), (300, 220), (200, 150), (340, 260), (10, 10),
                (20, 12), (15, 30)]
        with self.manager.use(cap["path"]) as s:
            spec = harness.spec_for(s, cap["draws"])
            for i in range(min(harness.ENV_SESSIONS, 40)):
                t0 = time.perf_counter()
                pixel = rng.choice(grid)
                queries = 0
                unknown = []
                graph = trace_pixel(s, *pixel, max_draws=4)
                queries += 1
                reads = [e["to"].split(":", 1)[1]
                         for e in graph["edges"] if e["label"] == "reads"]
                for rid in reads[:2]:
                    trace_resource(s, rid)
                    queries += 1
                reference = spec["background"]
                d = diff_pixel(s, pixel, reference).to_dict()
                queries += 1
                unknown = [ly["layer"] for ly in d["layers"]
                           if ly["status"] == "unknown"]
                if "shader_input_values" in unknown:
                    try:
                        debug_pixel(s, *pixel, max_steps=256,
                                    include_disassembly=False)
                        queries += 1
                    except RDebugError:
                        queries += 1
                for ly in d["layers"]:
                    if ly["status"] == "unknown":
                        harness.REPORT["unknownLayers"][ly["layer"]] += 1
                harness.REPORT["sessions"].append({
                    "session": i, "pixel": list(pixel), "queries": queries,
                    "latencyMs": round((time.perf_counter() - t0) * 1000.0, 1),
                    "firstDivergence": (d.get("firstDivergence") or {}).get("layer"),
                    "unknownLayers": unknown,
                })
        harness.record_correctness("debugging_sessions", True,
                                   f"{min(harness.ENV_SESSIONS, 40)} trajectories")


@harness.require_corpus()
class TestStress(WorkloadTest):
    def test_random_mix(self):
        cap = harness.pick(prefer_max_draws=64, tier_filter="S")
        rng = random.Random(9090)
        total = min(harness.ENV_STRESS_QUERIES, 4000)
        with self.manager.use(cap["path"]) as s:
            spec = harness.spec_for(s, cap["draws"])
            covered = spec["covered"]
            background = spec["background"]
            for _i in range(total):
                roll = rng.random()
                t0 = time.perf_counter()
                try:
                    if roll < 0.40:
                        pixel = covered if rng.random() < 0.5 else background
                        out = trace_pixel(s, *pixel, max_draws=4)
                        record_query("trace_pixel",
                                     (time.perf_counter() - t0) * 1000, out,
                                     cap["path"])
                    elif roll < 0.65:
                        out = trace_resource(s, spec["texture"])
                        record_query("trace_resource",
                                     (time.perf_counter() - t0) * 1000, out,
                                     cap["path"])
                    elif roll < 0.90:
                        out = diff_pixel(s, covered, background).to_dict()
                        record_query("diff_pixel",
                                     (time.perf_counter() - t0) * 1000, out,
                                     cap["path"])
                    else:
                        try:
                            out = debug_pixel(s, *covered, max_steps=128,
                                              include_disassembly=False)
                        except RDebugError:
                            out = {"error": "structured"}
                        record_query("debug_pixel",
                                     (time.perf_counter() - t0) * 1000,
                                     out if isinstance(out, dict) else None,
                                     cap["path"])
                except Exception as e:
                    harness.record_failure("unhandledExceptions", repr(e))
                    raise
        harness.record_correctness("stress", True, f"{total} queries")


if __name__ == "__main__":
    unittest.main()
