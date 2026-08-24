import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rdebug.adapter.core import CaptureSession
from rdebug.analysis.pixel_diff import diff_pixel
from rdebug.analysis.pixel_trace import trace_pixel
from rdebug.analysis.resource_flow import trace_resource
from rdebug.analysis.shader_trace import debug_pixel
from rdebug_mcp.server import SessionManager

CAPTURE = sys.argv[1]
OUT = sys.argv[2]

X, Y = 320, 240


def trajectory(session):
    return {
        "trace_pixel": trace_pixel(session, X, Y, max_draws=4),
        "trace_resource": trace_resource(session, "ResourceId::47"),
        "diff_pixel": diff_pixel(session, (X, Y), (10, 10)).to_dict(),
        "debug_pixel": debug_pixel(session, X, Y, max_steps=512,
                                   include_disassembly=False),
    }


def timed_cold():
    times = {}
    outputs = {}

    def step(name, fn):
        t0 = time.perf_counter()
        with CaptureSession(CAPTURE) as s:
            outputs[name] = fn(s)
        times[name] = round((time.perf_counter() - t0) * 1000.0, 1)

    step("trace_pixel", lambda s: trace_pixel(s, X, Y, max_draws=4))
    step("trace_resource", lambda s: trace_resource(s, "ResourceId::47"))
    step("diff_pixel", lambda s: diff_pixel(s, (X, Y), (10, 10)).to_dict())
    step("debug_pixel", lambda s: debug_pixel(s, X, Y, max_steps=512,
                                              include_disassembly=False))
    times["total"] = round(sum(times.values()), 1)
    return times, outputs


def timed_warm2(mgr):
    times = {}
    outputs = {}

    def step(name, fn):
        t0 = time.perf_counter()
        with mgr.use(CAPTURE) as s:
            outputs[name] = fn(s)
        times[name] = round((time.perf_counter() - t0) * 1000.0, 1)

    step("trace_pixel", lambda s: trace_pixel(s, X, Y, max_draws=4))
    step("trace_resource", lambda s: trace_resource(s, "ResourceId::47"))
    step("diff_pixel", lambda s: diff_pixel(s, (X, Y), (10, 10)).to_dict())
    step("debug_pixel", lambda s: debug_pixel(s, X, Y, max_steps=512,
                                              include_disassembly=False))
    times["total"] = round(sum(times.values()), 1)
    return times, outputs


def timed_warm():
    times = {}
    outputs = {}
    mgr = SessionManager(factory_provider=lambda: lambda c: CaptureSession(c))

    def step(name, fn):
        t0 = time.perf_counter()
        with mgr.use(CAPTURE) as s:
            outputs[name] = fn(s)
        times[name] = round((time.perf_counter() - t0) * 1000.0, 1)

    step("trace_pixel", lambda s: trace_pixel(s, X, Y, max_draws=4))
    step("trace_resource", lambda s: trace_resource(s, "ResourceId::47"))
    step("diff_pixel", lambda s: diff_pixel(s, (X, Y), (10, 10)).to_dict())
    step("debug_pixel", lambda s: debug_pixel(s, X, Y, max_steps=512,
                                              include_disassembly=False))
    times["total"] = round(sum(times.values()), 1)
    return times, outputs, mgr


cold_times, cold_out = timed_cold()
warm_times, warm_out, mgr = timed_warm()
warm2_times, warm2_out = timed_warm2(mgr)

equivalence = {}
for name in cold_out:
    equivalence[name] = (json.dumps(cold_out[name], sort_keys=True)
                         == json.dumps(warm_out[name], sort_keys=True))

report = {
    "capture": os.path.abspath(CAPTURE),
    "cold": cold_times,
    "warm": warm_times,
    "warm2": warm2_times,
    "warmSessionStats": mgr.stats(),
    "semanticEquivalence": equivalence,
    "allEquivalent": all(equivalence.values()),
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
json.dump(report, sys.stdout, indent=2)
sys.stdout.write("\n")
