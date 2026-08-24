import hashlib

from .analysis.common import actions_index_for, choose_output_target
from .analysis.pixel_diff import diff_pixel
from .model import PixelHistoryResult

_BASELINE_VERSION = 1


def capture_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _final_value(history):
    chosen = None
    for m in history.modifications:
        if m["passed"]:
            chosen = m
    if chosen is None:
        return None
    return {
        "float": [float(v) for v in chosen["postMod"].get("float", [])],
        "depth": float(chosen["postMod"].get("depth", -1.0)),
    }


def _fragment_event_id(session, history):
    actions_index = actions_index_for(session)
    candidates = [
        m
        for m in history.modifications
        if m["passed"]
        and not m.get("unboundPS")
        and not m.get("directShaderWrite")
        and actions_index.get(m["eventId"], {}).get("fragmentCandidate", True)
    ]
    return candidates[-1]["eventId"] if candidates else None


def _pixel_fingerprint(session, target, x, y):
    context_eid = session.last_draw_event_id()
    history = PixelHistoryResult.parse(
        session.pixel_history(target, x, y, context_eid=context_eid)
    )
    evidence = [ev["id"] for ev in history.payload.get("evidence", [])]
    return {
        "finalValue": _final_value(history),
        "fragmentEventId": _fragment_event_id(session, history),
        "evidenceIds": evidence,
    }


def _pair_fingerprint(session, a, b):
    result = diff_pixel(session, a, b).to_dict()
    first = result.get("firstDivergence")
    evidence_ids = [ev["id"] for ev in result.get("evidence", [])]
    if first:
        evidence_ids += [
            e["id"]
            for e in first.get("good", {}).get("evidence", [])
            + first.get("bad", {}).get("evidence", [])
        ]
    return {
        "comparison": result["comparison"],
        "firstDivergence": first.get("layer") if first else None,
        "layerStatuses": {ly["layer"]: ly["status"] for ly in result["layers"]},
        "evidenceIds": evidence_ids,
    }


def record(session, spec):
    target = spec.get("target")
    if target is None:
        target = choose_output_target(session, session.last_draw_event_id())

    baseline = {
        "version": _BASELINE_VERSION,
        "captureSha256": capture_hash(session.path),
        "target": str(target),
        "pixels": {},
        "pairs": {},
    }
    for x, y in spec.get("pixels", []):
        baseline["pixels"][f"px_{x}_{y}"] = _pixel_fingerprint(session, target, x, y)
    for pair in spec.get("pairs", []):
        a, b = [int(pair["a"][0]), int(pair["a"][1])], [
            int(pair["b"][0]),
            int(pair["b"][1]),
        ]
        name = pair.get("name") or f"pair_{a[0]}_{a[1]}_vs_{b[0]}_{b[1]}"
        entry = {"a": a, "b": b}
        entry.update(_pair_fingerprint(session, a, b))
        baseline["pairs"][name] = entry
    return baseline


def _floats_match(a, b, tolerance):
    if a is None or b is None or len(a) != len(b):
        return a == b
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def check(session, baseline, tolerance=1e-6, ignore_capture_hash=False):
    failures = []
    passed = 0

    target = baseline.get("target")
    if target is None:
        target = choose_output_target(session, session.last_draw_event_id())

    hash_ok = capture_hash(session.path) == baseline.get("captureSha256")
    if not hash_ok and not ignore_capture_hash:
        failures.append(
            {
                "kind": "capture_hash",
                "name": "capture",
                "path": "captureSha256",
                "expected": baseline.get("captureSha256"),
                "actual": capture_hash(session.path),
                "evidenceIds": [],
            }
        )

    for name, expected in baseline.get("pixels", {}).items():
        x, y = (int(v) for v in name[len("px_"):].split("_"))
        actual = _pixel_fingerprint(session, target, x, y)
        ev = actual["evidenceIds"] or expected.get("evidenceIds", [])

        fv_exp = (expected.get("finalValue") or {}).get("float")
        fv_act = (actual.get("finalValue") or {}).get("float")
        if _floats_match(fv_exp, fv_act, tolerance):
            passed += 1
        else:
            failures.append(
                {
                    "kind": "pixel_value",
                    "name": name,
                    "path": f"pixel({x},{y}).finalValue.float",
                    "expected": fv_exp,
                    "actual": fv_act,
                    "evidenceIds": ev,
                }
            )

        fe_exp, fe_act = expected.get("fragmentEventId"), actual.get("fragmentEventId")
        if fe_exp == fe_act:
            passed += 1
        else:
            failures.append(
                {
                    "kind": "fragment_event",
                    "name": name,
                    "path": f"pixel({x},{y}).fragmentEventId",
                    "expected": fe_exp,
                    "actual": fe_act,
                    "evidenceIds": ev,
                }
            )

    for name, expected in baseline.get("pairs", {}).items():
        a, b = tuple(expected["a"]), tuple(expected["b"])
        actual = _pair_fingerprint(session, a, b)
        diffs = []
        for key in ("comparison", "firstDivergence"):
            if expected.get(key) != actual.get(key):
                diffs.append(
                    {
                        "kind": f"pair_{key}",
                        "name": name,
                        "path": f"{name}.{key}",
                        "expected": expected.get(key),
                        "actual": actual.get(key),
                        "evidenceIds": actual["evidenceIds"],
                    }
                )
        for layer, status in expected.get("layerStatuses", {}).items():
            actual_status = actual["layerStatuses"].get(layer)
            if actual_status != status:
                diffs.append(
                    {
                        "kind": "pair_layer_status",
                        "name": name,
                        "path": f"{name}.layerStatuses.{layer}",
                        "expected": status,
                        "actual": actual_status,
                        "evidenceIds": actual["evidenceIds"],
                    }
                )
        if diffs:
            failures.extend(diffs)
        else:
            passed += 1

    return {
        "status": "pass" if not failures else "regression",
        "captureHashMatch": hash_ok,
        "passedChecks": passed,
        "failures": failures,
    }
