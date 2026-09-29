"""Replay worker process: one process owns exactly one capture.

The RenderDoc in-process replay runtime does not safely support multiple
live replay controllers in one process (see rdebug-validation/
docs/W1-R1-FINDINGS.md, findings F-1/F-2/F-3). This module moves the
ownership boundary to the process level:

    one worker process = one replay runtime = one active capture

Protocol (stdin/stdout, one JSON object per line):
    -> {"id": 1, "op": "call",  "tool": "trace_pixel", "args": {...}}
    <- {"id": 1, "ok": true,  "result": "<json string>"}
    -> {"id": 2, "op": "ping"}                <- {"id": 2, "ok": true}
    -> {"id": 3, "op": "exit"}                (worker replies then exits)
EOF on stdin also terminates the worker.

Memory instrumentation (opt-in, for F-3a heap attribution): start the
worker with RDEBUG_WORKER_TRACEMALLOC=1 to enable tracemalloc; op "mem"
then reports Python-traced allocations, optional snapshot diffs against
the previous mem call, and tracked-object census. Everything else stays
identical with tracing disabled or the op unused.

stdout carries ONLY protocol lines. The dispatch surface mirrors the four
Semantic API v1 tools exactly as the MCP transport exposes them; results
are serialized with rdebug.jsonutil.to_json so NaN/Inf semantics are
identical across transports."""

import argparse
import json
import os
import sys
import uuid


def _dispatch():
    """Route a call to something that needs the capture's session.

    The first four entries mirror the Semantic API v1 tools exactly and are
    what the MCP transport exposes. `ci_check` is a fifth entry because
    rdebug.ci is Stable Core and the IDE consumes it directly (it did so
    before M1.4, in-process); it needs a session, so it has to run where
    the capture lives.

    Putting it here rather than behind a separate op is a correction: the
    first version made it an op, which forced the IDE through
    WorkerManager.query() and failed with "unknown tool". Keeping it as an
    op would have meant adding a second call path to WorkerManager purely
    to preserve a boundary that is enforced where it actually matters --
    the MCP tool surface, which is what an LLM sees. That surface is still
    exactly four tools, checked by
    tests_transport/test_transport.py::TransportInvariants.
    """
    from rdebug.analysis.pixel_diff import diff_pixel
    from rdebug.analysis.pixel_trace import trace_pixel
    from rdebug.analysis.resource_flow import trace_resource
    from rdebug.analysis.shader_trace import debug_pixel
    from rdebug.ci import check as ci_check

    def _tp(session, **a):
        return trace_pixel(
            session, a["x"], a["y"], target=a.get("target"),
            context_eid=a.get("eid"), mip=a.get("mip", 0),
            slice_=a.get("slice", 0), sample=a.get("sample", 0),
            max_draws=a.get("max_draws", 16),
            expand_reads=a.get("expand_reads", True),
            max_writers_per_resource=a.get("max_writers", 8))

    def _tr(session, **a):
        return trace_resource(session, a["resource"],
                              context_eid=a.get("eid"),
                              include_other=a.get("include_other", False))

    def _dp(session, **a):
        return debug_pixel(session, a["x"], a["y"], target=a.get("target"),
                           context_eid=a.get("eid"),
                           primitive=a.get("primitive"),
                           sample=a.get("sample"), view=a.get("view"),
                           max_steps=a.get("max_steps", 4096),
                           include_disassembly=a.get("include_disassembly",
                                                     True))

    def _df(session, **a):
        return diff_pixel(session, (a["a_x"], a["a_y"]),
                          (a["b_x"], a["b_y"]),
                          max_draws=a.get("max_draws", 16),
                          include_shader_values=a.get(
                              "include_shader_values", False),
                          expand_reads=a.get("expand_reads", True)).to_dict()

    def _ci_check(session, **a):
        # **a because the transport forwards transport-level keys such as
        # `capture` alongside the call arguments; the other four entries
        # read the keys they need out of the same dict.
        return ci_check(session, a.get("baseline") or {})

    return {"trace_pixel": _tp, "trace_resource": _tr,
            "debug_pixel": _dp, "diff_pixel": _df,
            "ci_check": _ci_check}


_prev_snapshot = None

# Per-process token identifying THIS worker process. Generated once at
# startup and constant for the process's life, so it is stable within a
# capture's lifetime and changes on respawn -- which is exactly the
# lifetime the D1 ruling asks for. It is a process token, not a RenderDoc
# object identity, and is not comparable to any other worker's.
_WORKER_INSTANCE_ID = uuid.uuid4().hex[:12]


def _identity(session, bound):
    """READ-ONLY observation payload for the migration acceptance checks.

    Deliberately reports what is verifiable and says "unobservable" where
    it is not. In particular the controller's RenderDoc-level identity is
    NOT reported: the API has none, and a Python id() would look like an
    identity claim while proving only that two Python objects differ.
    """
    runtime = session.replay_identity()
    controller = session.controller_identity()
    # Distinguishes controllers opened in THIS process. Named
    # opaque_local_token precisely so it cannot be mistaken for a
    # RenderDoc-level identity, and it is not comparable across processes.
    controller["opaque_local_token"] = f"{_WORKER_INSTANCE_ID}:{id(session)}"
    return {
        "worker_pid": os.getpid(),
        "worker_instance_id": _WORKER_INSTANCE_ID,
        "capture": bound,
        "capture_session_index": 0,
        "runtime": runtime,
        "controller": controller,
        "contract_status": "diagnostic_only__not_part_of_the_contract",
    }


def _mem_stats(args):
    """Python-layer memory view for the F-3a heap differential.

    args: gc (force collection first), snapshot (take tracemalloc snapshot
    and diff against the previous one), top (rows in top_growth)."""
    import gc

    stats = {}
    if args.get("gc"):
        gc.collect()
    counts = {}
    for obj in gc.get_objects():
        name = type(obj).__name__
        counts[name] = counts.get(name, 0) + 1
    stats["objects_total"] = sum(counts.values())
    stats["objects_top"] = sorted(counts.items(),
                                  key=lambda kv: -kv[1])[:12]
    stats["gc_counts"] = list(gc.get_count())

    try:
        import tracemalloc
    except ImportError:
        return stats
    if not tracemalloc.is_tracing():
        stats["tracemalloc"] = None
        return stats

    current, peak = tracemalloc.get_traced_memory()
    stats["tracemalloc"] = {"current": current, "peak": peak}

    global _prev_snapshot
    if args.get("snapshot"):
        snap = tracemalloc.take_snapshot()
        top_rows = []
        if _prev_snapshot is not None:
            limit = int(args.get("top", 8))
            for st in snap.compare_to(_prev_snapshot, "lineno")[:limit]:
                frame = st.traceback[-1]
                top_rows.append({
                    "site": f"{frame.filename}:{frame.lineno}",
                    "size_diff": st.size_diff,
                    "count_diff": st.count_diff,
                    "size_now": st.size,
                })
        _prev_snapshot = snap
        stats["top_growth"] = top_rows
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rdebug-worker")
    ap.add_argument("--capture", required=True)
    args = ap.parse_args(argv)

    if os.environ.get("RDEBUG_WORKER_TRACEMALLOC") == "1":
        import tracemalloc
        tracemalloc.start(10)

    from rdebug.adapter.core import CaptureSession
    from rdebug.errors import RDebugError
    from rdebug.jsonutil import to_json

    tools = _dispatch()
    out = sys.stdout

    def send(obj):
        out.write(json.dumps(obj, default=str) + "\n")
        out.flush()

    session = CaptureSession(args.capture)
    bound = os.path.abspath(session.path)
    send({"id": 0, "ok": True, "result": to_json(
        {"ready": True, "capture": bound})})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            send({"id": None, "ok": False, "error": f"bad request: {e}"})
            continue
        rid = req.get("id")
        op = req.get("op", "call")

        if op == "exit":
            send({"id": rid, "ok": True, "result": "\"bye\""})
            break
        if op == "ping":
            send({"id": rid, "ok": True, "result": "\"pong\""})
            continue
        if op == "mem":
            send({"id": rid, "ok": True,
                  "result": json.dumps(_mem_stats(req.get("args") or {}))})
            continue
        if op == "identity":
            # READ-ONLY. Answers "who actually served this request?" for the
            # migration acceptance checks. It observes; it never gates, never
            # affects health or recycle, and the transport does not depend
            # on it. See workers.py module docstring and DESIGN_SPEC §2.9.
            try:
                send({"id": rid, "ok": True,
                      "result": json.dumps(_identity(session, bound))})
            except Exception as e:
                send({"id": rid, "ok": False,
                      "error": f"{type(e).__name__}: {e}"})
            continue
        if op == "inventory":
            # Structural/legal-arg-space metadata only (W2 blinding):
            # texture dims/ids and event count. No semantic values.
            try:
                texs = session.textures()
                inv = {
                    "textures": [
                        {"id": t["id"], "width": t["width"],
                         "height": t["height"], "type": t["type"]}
                        for t in texs],
                    "last_event_id": session.last_event_id(),
                }
                send({"id": rid, "ok": True,
                      "result": json.dumps(inv)})
            except Exception as e:
                send({"id": rid, "ok": False,
                      "error": f"{type(e).__name__}: {e}"})
            continue
        if op != "call":
            send({"id": rid, "ok": False,
                  "error": f"unknown op {op!r}"})
            continue

        tool = req.get("tool")
        fn = tools.get(tool)
        if fn is None:
            send({"id": rid, "ok": False,
                  "error": f"unknown tool {tool!r}"})
            continue
        call_args = dict(req.get("args") or {})
        wanted = os.path.abspath(str(call_args.get("capture", ""))) \
            if call_args.get("capture") else bound
        if wanted != bound:
            send({"id": rid, "ok": False,
                  "error": f"worker bound to {bound}, requested {wanted}"})
            continue

        try:
            payload = fn(session, **call_args)
            send({"id": rid, "ok": True, "result": to_json(payload)})
        except RDebugError as e:
            send({"id": rid, "ok": True,
                  "result": json.dumps({"error": str(e), "tool": tool})})
        except Exception as e:
            send({"id": rid, "ok": False,
                  "error": f"{type(e).__name__}: {e}"})

    try:
        session.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
