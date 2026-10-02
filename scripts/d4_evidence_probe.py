"""D4 evidence probe: is "live but semantically invalid" reachable?

D4's question is narrow and post-migration. Before M1, a workerless
transport could put two ReplayControllers in one process, and that WAS the
live-but-unhealthy condition (W1-R1 F-1/F-2). The isolation boundary now
makes that unreachable, so D4 asks what remains:

    can a single worker's own replay runtime enter a state that
    proc.poll() cannot detect, where a later valid query returns a wrong
    answer rather than an error?

This probe issues only queries the API considers valid. It injects no
corruption and does not attempt to manufacture a failure, because fault
injection can show whether a detection path exists but cannot show that
the condition is worth covering in production.

It also separates the four things this condition must NOT be confused
with, and reports each explicitly:

  process death            the worker pid is gone
  domain query error       an RDebugError with a domain message
  bad parameter            rejected by the transport's bad_request branch
  unsupported operation    e.g. "shader is not debuggable" on this capture
  LIVE + RESPONSIVE + WRONG   the only thing that would count as unhealthy
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))


def _capture_dir():
    return os.environ.get("RDEBUG_ISOLATION_CAPTURE_DIR",
                          os.path.join("tests", "workload", "corpus"))


def _pick_capture():
    d = _capture_dir()
    for f in sorted(os.listdir(d)):
        if f.endswith(".rdc"):
            return os.path.abspath(os.path.join(d, f))
    raise SystemExit(f"no .rdc in {d}")


def _fingerprint(payload):
    return json.dumps(payload, sort_keys=True, default=str)


def probe_session(capture, interleaves, pixels):
    """Session-level: does a valid query sequence change another query?"""
    from rdebug.adapter import core
    from rdebug.adapter.core import CaptureSession
    from rdebug.errors import RDebugError

    result = {"layer": "session", "capture": os.path.basename(capture)}
    sess = CaptureSession(capture)
    try:
        target = sess.pipeline(sess.last_draw_event_id())["outputTargets"][0]["resource"]
        result["initialise_epoch"] = core._REPLAY_LIFECYCLE.get(
            "initialise_epoch", 0)

        # Baseline fingerprints, each taken as the FIRST query on a fresh
        # session would produce it, so a later change is attributable to
        # what ran in between.
        firsts = {}
        for name, (x, y) in pixels.items():
            firsts[name] = _fingerprint(sess.pixel_history(target, x, y).payload)
        result["pixels_differ_from_each_other"] = (
            firsts["a"] != firsts["b"])

        # Interleave a and b, then re-take a. If state leaks, a changes.
        drift = 0
        for _ in range(interleaves):
            sess.pixel_history(target, *pixels["b"])
            if _fingerprint(sess.pixel_history(target, *pixels["a"]).payload
                            ) != firsts["a"]:
                drift += 1
        result["interleaves"] = interleaves
        result["a_drift_count"] = drift
        result["a_stable"] = drift == 0

        # Cursor: it persists inside a session by design, so record whether
        # it moves and whether anything observable follows from it.
        before = sess.current_event_id
        sess.set_event(sess.last_draw_event_id())
        result["cursor_moves_to_last_draw"] = (sess.current_event_id
                                               == sess.last_draw_event_id())
        result["cursor_moved"] = sess.current_event_id != before
        result["still_responsive_after_run"] = _fingerprint(
            sess.pixel_history(target, *pixels["a"]).payload) == firsts["a"]

        # The four categories, explicitly separated.
        categories = {}
        try:
            sess.pixel_history(target, 4, 4, context_eid=999999)
            categories["domain_query_error"] = "no error raised"
        except RDebugError as e:
            categories["domain_query_error"] = f"RDebugError: {e}"
        except Exception as e:  # noqa: BLE001 - the probe classifies failures into categories, so the exception type is data rather than control flow
            categories["domain_query_error"] = f"{type(e).__name__}: {e}"
        categories["unsupported_operation"] = _try_debug(sess, pixels["a"])
        categories["bad_parameter"] = "handled at the transport boundary, not here"
        categories["process_death"] = "n/a: this probe holds no subprocess"
        result["non_unhealthy_categories"] = categories
    finally:
        sess.close()
    return result


def _try_debug(sess, xy):
    try:
        sess.debug_pixel(xy[0], xy[1], max_steps=16)
        return "succeeded (this capture is debuggable)"
    except Exception as e:  # noqa: BLE001 - debugeability is an observation being recorded, so every failure mode is in scope
        return f"{type(e).__name__}: {e}"


def probe_worker(capture, interleaves, pixels):
    """Worker-level: what the transport would actually see."""
    from rdebug.worker_manager import WorkerManager

    result = {"layer": "worker", "capture": os.path.basename(capture)}
    mgr = WorkerManager()
    try:
        mgr.ping(capture)
        pid = mgr.pid(capture)

        def q(name):
            x, y = pixels[name]
            return _fingerprint(mgr.query(capture, "trace_pixel", x=x, y=y,
                                          max_draws=4))
        base = {n: q(n) for n in ("a", "b")}
        result["pixels_differ_from_each_other"] = base["a"] != base["b"]
        drift = 0
        errors = 0
        for _ in range(interleaves):
            q("b")
            if q("a") != base["a"]:
                drift += 1
        result["interleaves"] = interleaves
        result["a_drift_count"] = drift
        result["a_stable"] = drift == 0
        result["errors_seen"] = errors
        result["worker_alive_after"] = mgr.alive(capture)
        result["worker_pid_stable"] = (mgr.pid(capture) == pid)
        info = mgr.identity(capture)
        result["runtime"] = {
            "initialise_epoch": info["runtime"]["initialise_epoch"],
            "live_sessions": info["runtime"]["live_sessions"],
            "identity": info["runtime"]["identity"],
        }
    finally:
        mgr.dispose_all()
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="d4_evidence_probe")
    ap.add_argument("--capture", default="")
    ap.add_argument("--interleaves", type=int, default=50)
    ap.add_argument("--layer", choices=("session", "worker", "both"),
                    default="both")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    capture = os.path.abspath(args.capture or _pick_capture())
    pixels = {"a": (4, 4), "b": (8, 8)}
    out = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "capture": capture, "interleaves": args.interleaves}

    if args.layer in ("session", "both"):
        out["session"] = probe_session(capture, args.interleaves, pixels)
    if args.layer in ("worker", "both"):
        out["worker"] = probe_worker(capture, args.interleaves, pixels)

    text = json.dumps(out, indent=2, default=str)
    print(text)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
