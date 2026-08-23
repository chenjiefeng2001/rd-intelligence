from ..errors import QueryError
from ..query.events import build_action_index

MAX_DRAWS_DEFAULT = 16
MAX_INPUT_RESOURCES = 8


def _group_modifications(modifications):
    by_event = {}
    order = []
    for m in modifications:
        eid = m["eventId"]
        if eid not in by_event:
            by_event[eid] = {
                "eventId": eid,
                "primitives": [],
                "passedCount": 0,
                "failedCount": 0,
                "directWrite": False,
                "lastPostMod": None,
            }
            order.append(eid)
        group = by_event[eid]
        if m["primitiveID"] not in group["primitives"]:
            group["primitives"].append(m["primitiveID"])
        if m["passed"]:
            group["passedCount"] += 1
            group["lastPostMod"] = m["postMod"]
        else:
            group["failedCount"] += 1
        if m.get("directShaderWrite"):
            group["directWrite"] = True
    return [by_event[e] for e in sorted(order)]


def build_graph(pixel, history, pipelines, actions=None, target=None):
    nodes = []
    edges = []
    actions_index = actions or {}

    def add_node(node):
        nodes.append(node)
        return node

    pixel_id = "pixel:{},{}".format(pixel["x"], pixel["y"])
    add_node(
        {
            "id": pixel_id,
            "kind": "pixel",
            "attrs": {"x": pixel["x"], "y": pixel["y"], "mip": history.get("mip", 0),
                      "slice": history.get("slice", 0), "sample": history.get("sample", 0)},
        }
    )

    target_rid = target or history.get("resource")
    if target_rid is not None:
        add_node({"id": f"target:{target_rid}", "kind": "target",
                  "attrs": {"resource": str(target_rid)}})
        edges.append({"from": f"target:{target_rid}", "to": pixel_id,
                      "label": "contains", "evidence": {}})

    write_groups = _group_modifications(history["modifications"])
    for group in write_groups:
        eid = group["eventId"]
        draw_id = f"draw:{eid}"
        action_info = actions_index.get(eid, {})
        add_node(
            {
                "id": draw_id,
                "kind": "draw",
                "attrs": {
                    "eventId": eid,
                    "name": action_info.get("name", ""),
                    "primitives": group["primitives"],
                    "passed": group["passedCount"],
                    "failed": group["failedCount"],
                    "directWrite": group["directWrite"],
                },
            }
        )
        if target_rid is not None:
            edges.append(
                {
                    "from": draw_id,
                    "to": f"target:{target_rid}",
                    "label": "writes",
                    "evidence": {
                        "eventId": eid,
                        "primitives": group["primitives"],
                        "postMod": group["lastPostMod"],
                    },
                }
            )
        pipe = pipelines.get(eid)
        if not pipe:
            continue
        ps = pipe.get("shaders", {}).get("Pixel")
        if ps and not group["directWrite"]:
            shader_id = "shader:{}:{}".format(eid, ps["resource"])
            add_node(
                {
                    "id": shader_id,
                    "kind": "shader",
                    "attrs": {
                        "stage": "Pixel",
                        "resource": ps["resource"],
                        "entryPoint": ps.get("entryPoint", ""),
                        "debuggable": ps.get("debuggable"),
                    },
                }
            )
            edges.append({"from": draw_id, "to": shader_id, "label": "bound_ps",
                          "evidence": {"eventId": eid}})
            input_count = 0
            for d in pipe.get("descriptors", []):
                rid = d.get("resource")
                if rid is None:
                    continue
                res_id = f"resource:{rid}"
                if not any(n["id"] == res_id for n in nodes):
                    if input_count >= MAX_INPUT_RESOURCES:
                        continue
                    input_count += 1
                    add_node({"id": res_id, "kind": "resource",
                              "attrs": {"resource": str(rid)}})
                edges.append(
                    {
                        "from": shader_id,
                        "to": res_id,
                        "label": "reads",
                        "evidence": {"stage": d.get("stage"), "type": d.get("type"),
                                     "index": d.get("index")},
                    }
                )
        ib = pipe.get("indexBuffer")
        if ib and ib.get("resource"):
            ib_id = "resource:{}".format(ib["resource"])
            if not any(n["id"] == ib_id for n in nodes):
                add_node({"id": ib_id, "kind": "resource",
                          "attrs": {"resource": str(ib["resource"])}})
            edges.append({"from": draw_id, "to": ib_id, "label": "reads_indices",
                          "evidence": {"eventId": eid}})

    final_value = None
    for m in reversed(history["modifications"]):
        if m["passed"]:
            final_value = m["postMod"]
            break
    summary = {
        "modificationCount": len(history["modifications"]),
        "writeEventCount": len(write_groups),
        "finalValue": final_value,
        "contextEventId": history.get("contextEventId"),
    }
    return {"nodes": nodes, "edges": edges, "summary": summary}


def trace_pixel(
    session,
    x,
    y,
    target=None,
    context_eid=None,
    mip=0,
    slice_=0,
    sample=0,
    max_draws=MAX_DRAWS_DEFAULT,
):
    if context_eid is None:
        context_eid = session.last_event_id()
    if target is None:
        ctx_pipe = session.pipeline(context_eid)
        outs = ctx_pipe.get("outputTargets") or []
        depth = ctx_pipe.get("depthTarget")
        if outs:
            target = outs[0]["resource"]
        elif depth:
            target = depth["resource"]
        else:
            raise QueryError(
                f"no output targets bound at event {context_eid}; pass --target explicitly"
            )

    history = session.pixel_history(
        target, x, y, mip=mip, slice_=slice_, sample=sample, context_eid=context_eid
    )

    write_events = sorted({m["eventId"] for m in history["modifications"]})
    truncated = len(write_events) > max_draws
    selected = write_events[-max_draws:] if truncated else write_events

    pipelines = {eid: session.pipeline(eid) for eid in selected}

    from ..query.events import flatten_actions

    actions_index = build_action_index(flatten_actions(session.root_actions()))

    graph = build_graph(
        {"x": x, "y": y},
        history,
        pipelines,
        actions=actions_index,
        target=str(target),
    )
    graph["summary"]["truncatedDraws"] = truncated
    graph["summary"]["totalWriteEvents"] = len(write_events)
    graph["summary"]["analyzedDraws"] = len(selected)
    graph["summary"]["target"] = str(target)
    return graph
