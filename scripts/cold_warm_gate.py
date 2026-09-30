"""Gate 3: cold-equals-warm semantic equivalence (DESIGN_SPEC 4.3).

The check exists because the spec requires it and no such check existed. It
compares the complete semantic payload of every mandatory case, across four
collection points that form a real worker boundary:

    A_cold   first query in a freshly spawned worker
    A_warm   the same queries after warm-up, in the same worker
    B_cold   the same queries in a NEW worker, after an explicit recycle
    B_warm   the same queries after warm-up in that new worker

Worker identity is recorded as execution evidence, in a field beside the
payloads and never inside them. The recycle is real: the worker process is
disposed and a different process serves the next query, which is asserted by
comparing pids rather than assumed.

Comparison is over the whole payload. There is no field allowlist, no
volatile-field exclusion, and no subset comparison. If a value differs the
verdict is REGRESSION and the differing paths are reported, so the cause can
be found rather than tolerated. Adding an exclusion list is exactly what this
check exists to make unnecessary.

The one canonicalisation applied is that dict keys are sorted before
comparison. That is not a filter: every value is still compared. It exists
because dict construction order is not a semantic fact, and comparing it
would manufacture REGRESSIONs on unrelated refactors, which is precisely the
pressure that produces exclusion lists later.

Four outcomes, per the Q3 ruling:

    equal                      PASS
    any difference             REGRESSION
    both sides unavailable     UNKNOWN, and the failure type and message are
                               compared, because a stably unavailable case
                               must not mask a real difference
    environment unusable       INFRASTRUCTURE_FAILURE

A mandatory case that cannot be executed is never dropped. It is reported as
unavailable with the reason, and it keeps the verdict off PASS.
"""

import argparse
import json
import os
import sys

from rdebug.errors import RDebugError
from rdebug.worker_manager import WorkerManager

PASS = "PASS"
REGRESSION = "REGRESSION"
UNKNOWN = "UNKNOWN"
INFRA = "INFRASTRUCTURE_FAILURE"

EXIT_CODES = {PASS: 0, REGRESSION: 2, INFRA: 3, UNKNOWN: 4}

WARMUP_QUERIES = 12
MAX_REPORTED_DIFFS = 8


class GateAbort(Exception):
    """Environment or dependency unusable; not a content conclusion."""

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


def canonical(payload):
    """Full payload, keys sorted, nothing removed."""
    return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)


def diff_paths(left, right, prefix="", out=None):
    """Every path whose value differs. No limit on traversal, only on reporting."""
    if out is None:
        out = []
    if isinstance(left, dict) and isinstance(right, dict):
        for k in sorted(set(left) | set(right)):
            diff_paths(left.get(k, "<absent>"), right.get(k, "<absent>"),
                       f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            out.append((prefix, f"len {len(left)}", f"len {len(right)}"))
        else:
            for i, (a, b) in enumerate(zip(left, right)):
                diff_paths(a, b, f"{prefix}[{i}]", out)
    elif left != right:
        out.append((prefix, left, right))
    return out


def build_cases(inventory):
    """Mandatory dimensions, derived from the capture rather than hardcoded.

    The centre of the largest texture is used because that is inside the
    rasterised area of a triangle fixture; the corner pixels are covered only
    by the clear, which is a different code path and proved misleading during
    the reachability investigation.
    """
    textures = sorted(inventory.get("textures") or [],
                      key=lambda t: -(t.get("width", 0) * t.get("height", 0)))
    if not textures:
        raise GateAbort("capture exposes no textures; cannot derive a target")
    biggest = textures[0]
    target = biggest["id"]
    cx, cy = biggest["width"] // 2, biggest["height"] // 2
    eid = inventory.get("last_event_id")
    if eid is None:
        raise GateAbort("capture reports no last_event_id")

    return [
        {"id": "trace_pixel", "mandatory": True,
         "tool": "trace_pixel",
         "args": {"x": cx, "y": cy, "target": target, "eid": eid}},
        {"id": "trace_resource", "mandatory": True,
         "tool": "trace_resource",
         "args": {"resource": target, "eid": eid}},
        {"id": "diff_pixel", "mandatory": True,
         "tool": "diff_pixel",
         "args": {"a_x": cx, "a_y": cy, "b_x": 10, "b_y": 10}},
        # High risk by construction: this path goes through the shader
        # debugger. If it differs, the verdict is REGRESSION and the cause is
        # investigated. If it cannot run, the case is reported unavailable and
        # the verdict is UNKNOWN or INFRASTRUCTURE_FAILURE. It is never
        # dropped to make the gate green.
        {"id": "diff_pixel_shader_values", "mandatory": True,
         "tool": "diff_pixel",
         "args": {"a_x": cx, "a_y": cy, "b_x": 10, "b_y": 10,
                  "include_shader_values": True}},
        {"id": "debug_pixel", "mandatory": True,
         "tool": "debug_pixel",
         "args": {"x": cx, "y": cy, "target": target, "eid": eid,
                  "include_disassembly": True}},
    ]


def run_case(mgr, capture, case):
    """One case, one worker request. Failures become recorded unavailability."""
    try:
        return {"status": "ok", "payload": mgr.query(capture, case["tool"],
                                                     **case["args"])}
    except RDebugError as e:
        return {"status": "unavailable",
                "error_type": type(e).__name__, "error": str(e)}
    except Exception as e:  # noqa: BLE001 - recorded, not swallowed
        return {"status": "unavailable",
                "error_type": type(e).__name__, "error": str(e)}


def collect(mgr, capture, cases, label):
    """Run every case in the current worker, then record which worker it was."""
    pid_before = mgr.pid(capture)
    results = {}
    for case in cases:
        results[case["id"]] = run_case(mgr, capture, case)
    return {
        "label": label,
        "pid": mgr.pid(capture),
        "pid_before": pid_before,
        "cases": results,
    }


def warm(mgr, capture, inventory, eid, n=WARMUP_QUERIES):
    """Unrelated work, so the compared queries are not compared with themselves."""
    textures = inventory.get("textures") or []
    if not textures:
        return 0
    target = textures[0]["id"]
    for i in range(n):
        try:
            mgr.query(capture, "trace_pixel", x=10 + i, y=10,
                      target=target, eid=eid)
        except Exception:  # noqa: BLE001 - warm-up failure is not a verdict
            pass
        try:
            mgr.query(capture, "trace_resource", resource=target, eid=eid)
        except Exception:  # noqa: BLE001
            pass
    return n


def compare_case(case_id, reference, others):
    """Compare one case across the other collection points."""
    ref = reference["cases"][case_id]
    verdict = PASS
    detail = []
    for other_label, other in others:
        o = other["cases"][case_id]
        if ref["status"] == "unavailable" or o["status"] == "unavailable":
            if ref["status"] == "unavailable" and o["status"] == "unavailable":
                same = (ref.get("error_type") == o.get("error_type")
                        and ref.get("error") == o.get("error"))
                verdict = UNKNOWN if same else REGRESSION
                if not same:
                    detail.append({
                        "pair": other_label, "verdict": REGRESSION,
                        "reason": "unavailable on both sides but differently",
                        "reference_error": ref.get("error_type"),
                        "other_error": o.get("error_type"),
                    })
                else:
                    detail.append({
                        "pair": other_label, "verdict": UNKNOWN,
                        "reason": "unavailable on both sides identically",
                        "error_type": ref.get("error_type"),
                    })
            else:
                verdict = REGRESSION
                detail.append({
                    "pair": other_label, "verdict": REGRESSION,
                    "reason": "available on one side only",
                    "reference_status": ref["status"],
                    "other_status": o["status"],
                })
            continue
        diffs = diff_paths(ref["payload"], o["payload"])
        if diffs:
            verdict = REGRESSION
            detail.append({
                "pair": other_label, "verdict": REGRESSION,
                "reason": f"{len(diffs)} differing path(s)",
                "differing_paths": [
                    {"path": p, "reference": a, "other": b}
                    for p, a, b in diffs[:MAX_REPORTED_DIFFS]
                ],
                "differing_path_count": len(diffs),
            })
    return verdict, detail


def run(capture, warmup=WARMUP_QUERIES, mgr=None):
    owned = mgr is None
    mgr = mgr or WorkerManager()
    evidence = {"capture": capture, "warmup_queries": warmup}
    try:
        # inventory() does not spawn a worker, and a worker has to exist
        # before the capture can be inspected. ping() is a readiness request,
        # not a semantic query, so the worker is still cold with respect to
        # this capture's semantics when A_cold runs.
        try:
            mgr.ping(capture)
        except Exception as e:  # noqa: BLE001
            raise GateAbort(f"worker did not start: {type(e).__name__}: {e}")
        try:
            inventory = mgr.inventory(capture)
        except Exception as e:  # noqa: BLE001
            raise GateAbort(f"inventory failed: {type(e).__name__}: {e}")
        cases = build_cases(inventory)
        eid = inventory["last_event_id"]
        evidence["cases"] = [c["id"] for c in cases]

        a_cold = collect(mgr, capture, cases, "A_cold")
        warm(mgr, capture, inventory, eid, warmup)
        a_warm = collect(mgr, capture, cases, "A_warm")

        # Real recycle: dispose the worker process, so the next request is
        # served by a different one. Asserted by pid, not assumed.
        mgr.dispose(capture)
        b_cold = collect(mgr, capture, cases, "B_cold")
        warm(mgr, capture, inventory, eid, warmup)
        b_warm = collect(mgr, capture, cases, "B_warm")

        same_worker = a_cold["pid"] == a_warm["pid"] == a_cold["pid_before"]
        recycled = bool(a_cold["pid"]) and bool(b_cold["pid"]) \
            and a_cold["pid"] != b_cold["pid"]
        evidence["workers"] = {
            "A_cold": a_cold["pid"], "A_warm": a_warm["pid"],
            "B_cold": b_cold["pid"], "B_warm": b_warm["pid"],
        }
        evidence["same_worker_within_A"] = same_worker
        evidence["recycle_produced_new_worker"] = recycled
        evidence["pairs"] = [
            {"pair": "A_cold vs A_warm", "same_worker": True,
             "crossed_recycle": False, "crossed_worker": False},
            {"pair": "A_cold vs B_cold", "same_worker": False,
             "crossed_recycle": True, "crossed_worker": True},
            {"pair": "A_cold vs B_warm", "same_worker": False,
             "crossed_recycle": True, "crossed_worker": True},
        ]

        if not same_worker or not recycled:
            # The boundary this gate exists to test was not established. That
            # is an execution failure, not a content verdict.
            raise GateAbort(
                f"worker boundary not established: "
                f"same_worker_within_A={same_worker} "
                f"recycle_produced_new_worker={recycled} "
                f"(pids {list(evidence['workers'].values())})"
            )

        per_case, overall = {}, PASS
        others_by_label = {"A_warm": a_warm, "B_cold": b_cold,
                           "B_warm": b_warm}
        for case in cases:
            cid = case["id"]
            verdict, detail = compare_case(
                cid, a_cold,
                [("A_warm", a_warm), ("B_cold", b_cold), ("B_warm", b_warm)],
            )
            # Execution accounting, so a report can answer which cases
            # actually ran and which were unavailable, rather than only
            # saying that everything executable passed.
            attempted = 1 + len(others_by_label)
            available = 1 + sum(
                1 for o in others_by_label.values()
                if o["cases"][cid]["status"] == "ok"
            )
            per_case[cid] = {"verdict": verdict, "mandatory": True,
                             "attempted": attempted,
                             "available_at": available,
                             "comparisons": detail}
            if verdict == REGRESSION:
                overall = REGRESSION
            elif verdict == UNKNOWN and overall != REGRESSION:
                overall = UNKNOWN
        return {"outcome": overall, "cases": per_case, "evidence": evidence}
    finally:
        if owned:
            mgr.dispose_all()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gate 3 cold==warm equivalence")
    ap.add_argument("capture")
    ap.add_argument("--json", metavar="PATH", default=None,
                    help="where to write the verdict the release gate reads")
    ap.add_argument("--warmup", type=int, default=WARMUP_QUERIES)
    args = ap.parse_args(argv)

    capture = os.path.abspath(args.capture)
    try:
        verdict = run(capture, warmup=args.warmup)
    except GateAbort as e:
        verdict = {"outcome": INFRA, "cases": {},
                   "evidence": {"capture": capture, "abort": e.detail}}
        print(f"gate3 {INFRA}: {e.detail}")
    else:
        print("gate3 {}".format(verdict["outcome"]))
        for cid, c in sorted(verdict["cases"].items()):
            print(f"  {cid:<28} {c['verdict']:<12} "
                  f"available_at {c.get('available_at', 0)}/"
                  f"{c.get('attempted', 0)}")
            for d in c["comparisons"]:
                print(f"      {d['pair']:<18} {d['verdict']:<12} {d['reason']}")
        ev = verdict["evidence"]
        print("  workers: {}".format(ev.get("workers")))
        print(f"  same_worker_within_A={ev.get('same_worker_within_A')} "
              f"recycle_produced_new_worker={ev.get('recycle_produced_new_worker')}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(verdict, fh, indent=1, default=str)
    return EXIT_CODES[verdict["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
