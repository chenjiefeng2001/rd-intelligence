import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rdebug.adapter.core import CaptureSession
from rdebug.analysis.pixel_diff import diff_pixel

CAPTURE = sys.argv[1]
ANSWERS = os.path.join(os.path.dirname(__file__), "..", "docs", "validation",
                       "phase4c-answers.json")

CASES = {
    "case_same": {"a": (10, 10), "b": (20, 10)},
    "case_fragment": {"a": (320, 240), "b": (10, 10)},
    "case_deep_input": {"a": (330, 240), "b": (320, 240),
                        "kwargs": {"include_shader_values": True}},
    "case_structural_unknown": {"a": (330, 240), "b": (320, 240)},
}


def collect_evidence(node, ids, pairs):
    if isinstance(node, dict):
        if "id" in node and "operation" in node:
            ids.add(node["id"])
            ev_id = node.get("eventId")
            rid = node.get("resourceId")
            if ev_id is not None:
                pairs.add((int(ev_id), rid))
        for v in node.values():
            collect_evidence(v, ids, pairs)
    elif isinstance(node, list):
        for v in node:
            collect_evidence(v, ids, pairs)


def evaluate_case(name, gt_payload, answer):
    checks = {}

    ev_ids, ev_pairs = set(), set()
    collect_evidence(gt_payload, ev_ids, ev_pairs)

    gt_first = (gt_payload.get("firstDivergence") or {}).get("layer")
    checks["cause"] = (answer["stated_first_divergence_layer"] == gt_first)

    checks["evidence"] = set(answer["cited_evidence_ids"]) <= ev_ids

    bad_claims = []
    for claim in answer["claims"]:
        pair = (int(claim["eventId"]), claim.get("resourceId"))
        if pair not in ev_pairs:
            if pair[1] is None and any(p[0] == pair[0] for p in ev_pairs):
                continue
            bad_claims.append(claim)
    checks["facts"] = not bad_claims

    gt_statuses = {ly["layer"]: ly["status"] for ly in gt_payload["layers"]}
    checks["unknown"] = answer["stated_layer_statuses"] == gt_statuses

    unsupported = [
        c for c in answer["claims"]
        if "导致" in c["statement"] or "因此确定" in c["statement"]
    ]

    return {
        "cause": checks["cause"],
        "evidence": checks["evidence"],
        "facts": checks["facts"],
        "unknown": checks["unknown"],
        "unsupported_inference": bad_claims + unsupported,
        "gt_first": gt_first,
        "gt_statuses": gt_statuses,
    }


def main():
    answers = json.load(open(ANSWERS, encoding="utf-8"))
    session = CaptureSession(CAPTURE)
    scores = {k: [0, 0] for k in
              ("cause", "evidence", "facts", "unknown", "unsupported_inference")}
    detail = {}
    for name, spec in CASES.items():
        gt = diff_pixel(session, spec["a"], spec["b"],
                        **spec.get("kwargs", {})).to_dict()
        result = evaluate_case(name, gt, answers[name])
        for k in scores:
            if k == "unsupported_inference":
                scores[k][0] += 1 if not result[k] else 0
            else:
                scores[k][0] += 1 if result[k] else 0
            scores[k][1] += 1
        detail[name] = result

    session.close()
    report = {
        "scores": {k: {"passed": v[0], "total": v[1]} for k, v in scores.items()},
        "cases": detail,
    }
    out = os.path.join(os.path.dirname(__file__), "..", "docs", "validation",
                       "phase4c-reasoning.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    for k, v in scores.items():
        label = "no over-inference" if k == "unsupported_inference" else k
        print(f"{label:24s} {v[0]}/{v[1]}")
    print("saved:", os.path.abspath(out))


if __name__ == "__main__":
    main()
