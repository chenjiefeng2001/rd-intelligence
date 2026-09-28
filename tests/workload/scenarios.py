"""Reliability scenarios executed in isolated subprocesses.

Each scenario is a self-contained sequence that must end by printing
SCENARIO_OK. A native crash (access violation) kills only the subprocess;
the parent records it as a reliability data point."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tests"))


from rdebug.adapter.core import CaptureSession  # noqa: E402
from rdebug.analysis.pixel_trace import trace_pixel  # noqa: E402
from rdebug.analysis.resource_flow import trace_resource  # noqa: E402
from rdebug.analysis.shader_trace import debug_pixel  # noqa: E402
from rdebug.errors import QueryError  # noqa: E402
from rdebug.session_cache import SessionManager  # noqa: E402


def _caps():
    base = os.path.join(os.path.dirname(__file__), "corpus")
    return [str(p) for p in sorted(Path(base).glob("*.rdc"))[:4]]


def _manager(max_sessions=6):
    return SessionManager(
        factory_provider=lambda: CaptureSession, max_sessions=max_sessions)


def scenario_error_injection():
    import tempfile

    cap = _caps()[0]
    tmp = tempfile.mkdtemp()
    corrupted = os.path.join(tmp, "corrupted.rdc")
    with open(corrupted, "wb") as f:
        f.write(os.urandom(4096))
    missing = os.path.join(tmp, "missing.rdc")

    for bad in (corrupted, missing):
        # The AssertionError must be raised OUTSIDE the try, or the very
        # guard it implements gets swallowed by its own handler and the
        # scenario reports SCENARIO_OK for a capture that opened fine.
        opened = None
        try:
            opened = CaptureSession(bad)
        except QueryError:
            continue
        except Exception:
            # A native-level failure is an acceptable rejection too.
            continue
        if opened is not None:
            opened.close()
            raise AssertionError("corrupted/missing capture opened")
    os.remove(corrupted)

    with SessionManager(factory_provider=lambda: CaptureSession,
                        max_sessions=2).use(cap) as s:
        try:
            trace_resource(s, "ResourceId::999999")
            raise AssertionError("invalid resource accepted")
        except QueryError:
            pass
        spec_target = s.pipeline(s.last_draw_event_id())["outputTargets"][0]["resource"]
        flow = trace_resource(s, spec_target)
        assert flow["resource"]["id"] == spec_target
        try:
            debug_pixel(s, 10, 10, max_steps=64)
            raise AssertionError("background debug unexpectedly succeeded")
        except QueryError:
            pass
    print("SCENARIO_OK")


def scenario_isolation():
    caps = _caps()
    mgr = _manager(6)
    for idx in [0, 1, 2, 3, 0]:
        cap = caps[idx]
        expected = os.path.abspath(cap)

        def walk(node, expected=expected):
            if isinstance(node, dict):
                if "capture" in node and "id" in node:
                    assert os.path.abspath(node["capture"]) == expected, \
                        "cross-capture contamination"
                for v in node.values():
                    walk(v, expected)
            elif isinstance(node, list):
                for v in node:
                    walk(v, expected)

        with mgr.use(cap) as s:
            graph = trace_pixel(s, 10, 10, max_draws=4)
            flow = trace_resource(
                s, s.pipeline(s.last_draw_event_id())["outputTargets"][0]["resource"])
        walk(graph)
        walk(flow)
    mgr.dispose_all()
    print("SCENARIO_OK")


def scenario_lru_cycles():
    caps = _caps()
    mgr = _manager(2)
    for _cycle in range(12):
        for cap in caps:
            with mgr.use(cap) as s:
                trace_pixel(s, 10, 10, max_draws=4)
    mgr.dispose_all()
    print("SCENARIO_OK")


def scenario_mcp_contract():
    from rdebug_mcp import server

    cap = _caps()[0]
    prev = server._session_factory
    server._session_factory = lambda c: CaptureSession(c)
    server._MANAGER.dispose_all()
    try:
        valid = {"capture": cap, "x": 320, "y": 240, "max_draws": 4}
        invalid = {"capture": cap, "resource": "bogus"}
        for i in range(200):
            if i % 2 == 0:
                payload = json.loads(server.trace_pixel(**valid))
                assert "summary" in payload
            else:
                payload = json.loads(server.trace_resource(**invalid))
                assert "error" in payload
    finally:
        server._session_factory = prev
        server._MANAGER.dispose_all()
    print("SCENARIO_OK")


SCENARIOS = {
    "error_injection": scenario_error_injection,
    "isolation": scenario_isolation,
    "lru_cycles": scenario_lru_cycles,
    "mcp_contract": scenario_mcp_contract,
}


if __name__ == "__main__":
    name = sys.argv[1]
    SCENARIOS[name]()
