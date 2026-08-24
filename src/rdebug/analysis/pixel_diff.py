from ..errors import QueryError
from ..evidence import make as make_evidence
from ..model import DiffResult, PixelHistoryResult
from .pixel_trace import trace_pixel
from .shader_trace import debug_pixel

_LAYER_ORDER = (
    "pixel_value",
    "fragment",
    "shader",
    "input_bindings",
    "shader_input_values",
    "resource_provenance",
)


def compare_scalar(a, b):
    if a is None or b is None:
        return "unknown"
    return "same" if a == b else "different"


def _final_value(history):
    chosen = None
    for m in history.modifications:
        if m["passed"]:
            chosen = m
    if chosen is None:
        return None
    post = chosen["postMod"]
    return {"float": post.get("float"), "depth": post.get("depth"),
            "eventId": chosen["eventId"], "primitiveID": chosen["primitiveID"]}


def compare_final_values(fa, fb, mods_a, mods_b):
    if mods_a == 0 or mods_b == 0:
        return "different" if mods_a != mods_b else "unknown"
    if fa is None or fb is None:
        return "unknown"
    va = {k: fa[k] for k in ("float", "depth")}
    vb = {k: fb[k] for k in ("float", "depth")}
    return "same" if va == vb else "different"


def compare_fragments(fa, fb):
    if fa is None and fb is None:
        return "unknown"
    if fa is None or fb is None:
        return "different"
    return "same" if fa == fb else "different"


def _fragment(history):
    candidates = [
        m
        for m in history.modifications
        if m["passed"] and not m.get("unboundPS") and not m.get("directShaderWrite")
    ]
    if not candidates:
        return None
    m = candidates[-1]
    return {"eventId": m["eventId"], "primitiveID": m["primitiveID"]}


def _extract_flow(graph, history):
    history = PixelHistoryResult.parse(history)
    shader = None
    input_bindings = []
    writes_evidence = {}
    reads_evidence = {}
    for e in graph["edges"]:
        if e["label"] == "writes":
            writes_evidence[str(e["evidence"][0].get("eventId"))] = e["evidence"]
        elif e["label"] == "reads":
            rid = str(e["to"]).split(":", 1)[1]
            if rid not in input_bindings:
                input_bindings.append(rid)
            reads_evidence[rid] = e["evidence"]
        elif e["label"] == "bound_ps" and shader is None:
            shader = {
                "resource": e["to"].split(":", 2)[2],
                "evidence": e["evidence"],
            }
    provenance = {}
    for rid, flow in (graph.get("resourceFlows") or {}).items():
        provenance[rid] = {
            "writers": [w["eventId"] for w in flow["writers"]],
            "readers": [r["eventId"] for r in flow["readers"]],
            "evidence": {
                "writers": {w["eventId"]: w["evidence"] for w in flow["writers"]},
                "readers": {r["eventId"]: r["evidence"] for r in flow["readers"]},
            },
        }
    return {
        "finalValue": _final_value(history),
        "modifications": len(history.modifications),
        "fragment": _fragment(history),
        "historyEvidence": history.payload.get("evidence", []),
        "writesEvidence": writes_evidence,
        "shader": shader,
        "inputBindings": sorted(input_bindings),
        "readsEvidence": reads_evidence,
        "provenance": provenance,
    }


def _layer_entry(name, status, good=None, bad=None, path=None, evidence=None, note=None):
    entry = {"layer": name, "status": status}
    if path is not None:
        entry["path"] = path
    entry["good"] = {"value": good, "evidence": evidence or []}
    entry["bad"] = {"value": bad, "evidence": evidence or []}
    if note:
        entry["note"] = note
    return entry


def diff_pixel_flows(flow_a, flow_b, capture, shader_values_a=None, shader_values_b=None):
    layers = []

    fa, fb = flow_a["finalValue"], flow_b["finalValue"]
    va = {k: fa[k] for k in ("float", "depth")} if fa else None
    vb = {k: fb[k] for k in ("float", "depth")} if fb else None
    ev = []
    if fa:
        ev += flow_a["historyEvidence"] + flow_a["writesEvidence"].get(
            str(fa["eventId"]), []
        )
    if fb:
        ev += flow_b["historyEvidence"] + flow_b["writesEvidence"].get(
            str(fb["eventId"]), []
        )
    layers.append(
        _layer_entry(
            "pixel_value",
            compare_final_values(fa, fb, flow_a["modifications"],
                                 flow_b["modifications"]),
            va, vb, "final postMod", ev,
        )
    )

    frag_a, frag_b = flow_a["fragment"], flow_b["fragment"]
    ev = []
    if frag_a:
        ev += flow_a["writesEvidence"].get(str(frag_a["eventId"]), [])
    if frag_b:
        ev += flow_b["writesEvidence"].get(str(frag_b["eventId"]), [])
    layers.append(
        _layer_entry(
            "fragment",
            compare_fragments(frag_a, frag_b),
            frag_a,
            frag_b,
            "last passed fragment (eventId, primitiveID)",
            ev,
        )
    )

    sh_a, sh_b = flow_a["shader"], flow_b["shader"]
    sa = sh_a["resource"] if sh_a else None
    sb = sh_b["resource"] if sh_b else None
    ev = (sh_a or {}).get("evidence", []) + (sh_b or {}).get("evidence", [])
    layers.append(
        _layer_entry("shader", compare_scalar(sa, sb), sa, sb,
                     "bound pixel shader (code identity)", ev)
    )

    bind_a, bind_b = flow_a["inputBindings"], flow_b["inputBindings"]
    ev = flow_a["historyEvidence"] + flow_b["historyEvidence"]
    layers.append(
        _layer_entry(
            "input_bindings",
            compare_scalar(bind_a, bind_b),
            bind_a,
            bind_b,
            "sorted direct read resources",
            ev,
        )
    )

    if shader_values_a is None and shader_values_b is None:
        layers.append(
            _layer_entry(
                "shader_input_values",
                "unknown",
                note="not requested; pass include_shader_values=True to compare "
                "interpolated PS inputs via the shader debugger",
            )
        )
    else:
        layers.append(
            _layer_entry(
                "shader_input_values",
                compare_scalar(shader_values_a, shader_values_b),
                shader_values_a,
                shader_values_b,
                "interpolated PS inputs",
                flow_a["historyEvidence"] + flow_b["historyEvidence"],
            )
        )

    rids = sorted(set(flow_a["provenance"]) | set(flow_b["provenance"]))
    prov_status = "same"
    prov_good, prov_bad, prov_ev = {}, {}, []
    for rid in rids:
        pa = flow_a["provenance"].get(rid)
        pb = flow_b["provenance"].get(rid)
        wa = pa["writers"] if pa else None
        wb = pb["writers"] if pb else None
        st = compare_scalar(wa, wb)
        if st == "different":
            prov_status = "different"
            prov_good[rid] = wa
            prov_bad[rid] = wb
            if pa:
                for eid in wa or []:
                    prov_ev += pa["evidence"]["writers"].get(eid, [])
            if pb:
                for eid in wb or []:
                    prov_ev += pb["evidence"]["writers"].get(eid, [])
        elif st == "unknown":
            if prov_status != "different":
                prov_status = "unknown"
            prov_good[rid] = wa
            prov_bad[rid] = wb
    layers.append(
        _layer_entry(
            "resource_provenance", prov_status, prov_good, prov_bad,
            "writer event ids per read resource", prov_ev,
        )
    )

    differing = [entry for entry in layers if entry["status"] == "different"]

    first = None
    if differing:
        deepest = max(_LAYER_ORDER.index(e["layer"]) for e in differing)
        first = next(e for e in differing if _LAYER_ORDER.index(e["layer"]) == deepest)

    comparison = "different" if differing else (
        "same" if next(e for e in layers if e["layer"] == "pixel_value")["status"]
        == "same" else "unknown"
    )

    payload = {
        "comparison": comparison,
        "equal": comparison == "same",
        "firstDivergence": first,
        "layers": layers,
        "a": {"finalValue": fa, "fragment": frag_a},
        "b": {"finalValue": fb, "fragment": frag_b},
        "evidence": [make_evidence(capture=capture, operation="diff_pixel",
                                   source="rdebug.analysis.pixel_diff")],
    }
    return DiffResult(payload)


def diff_pixel(
    session,
    point_a,
    point_b,
    history_a=None,
    history_b=None,
    max_draws=16,
    include_shader_values=False,
    expand_reads=True,
):
    from .common import choose_output_target

    ax, ay = point_a
    bx, by = point_b

    context_eid = session.last_draw_event_id()
    default_target = choose_output_target(session, context_eid)

    hist_a = PixelHistoryResult.parse(history_a) if history_a is not None else \
        session.pixel_history(default_target, ax, ay, context_eid=context_eid)
    hist_b = PixelHistoryResult.parse(history_b) if history_b is not None else \
        session.pixel_history(default_target, bx, by, context_eid=context_eid)

    graph_a = trace_pixel(session, ax, ay, history=hist_a, max_draws=max_draws,
                          expand_reads=expand_reads)
    graph_b = trace_pixel(session, bx, by, history=hist_b, max_draws=max_draws,
                          expand_reads=expand_reads)

    values_a = values_b = None
    if include_shader_values:
        values_a = _interpolated_inputs(session, ax, ay, hist_a)
        values_b = _interpolated_inputs(session, bx, by, hist_b)

    flow_a = _extract_flow(graph_a, hist_a)
    flow_b = _extract_flow(graph_b, hist_b)
    result = diff_pixel_flows(flow_a, flow_b, session.path, values_a, values_b)
    result.payload["a"]["graphSummary"] = graph_a["summary"]
    result.payload["b"]["graphSummary"] = graph_b["summary"]
    return result


def _interpolated_inputs(session, x, y, history):
    try:
        trace = debug_pixel(session, x, y, history=history, include_disassembly=False)
        return [
            {"name": i.get("name"), "value": i.get("value")}
            for i in trace.get("inputs", [])
        ]
    except QueryError:
        return None


def _interpolated_inputs(session, x, y, history):
    try:
        trace = debug_pixel(session, x, y, history=history, include_disassembly=False)
        return [
            {"name": i.get("name"), "value": i.get("value")}
            for i in trace.get("inputs", [])
        ]
    except QueryError:
        return None
