from ..errors import QueryError
from ..evidence import make as make_evidence
from .common import choose_output_target


def resolve_inst_info(inst_info_rows, instruction):
    best = None
    for row in inst_info_rows:
        if row["instruction"] <= instruction:
            best = row
        else:
            break
    return best


def build_shader_trace(
    capture,
    x,
    y,
    event_id,
    primitive,
    raw,
    include_disassembly=True,
    evidence=None,
):
    disasm_lines = raw["disassembly"].splitlines()
    files = raw["files"]
    steps_out = []
    for s in raw["steps"]:
        ni = s["nextInstruction"]
        entry = {
            "stepIndex": s["stepIndex"],
            "nextInstruction": ni,
            "events": s["events"],
            "callstack": s["callstack"],
            "changes": s["changes"],
        }
        src = resolve_inst_info(raw["instInfo"], ni)
        if src is not None:
            entry["source"] = {
                "fileIndex": src["fileIndex"],
                "line": src["lineStart"],
                "disassemblyLine": src["disassemblyLine"],
            }
            line_no = src["disassemblyLine"]
            if include_disassembly and 1 <= line_no <= len(disasm_lines):
                entry["disassemblyText"] = disasm_lines[line_no - 1]
            if 0 <= src["fileIndex"] < len(files):
                entry["sourceFile"] = files[src["fileIndex"]]["filename"]
        steps_out.append(entry)

    trace_evidence = list(evidence or [])
    trace_evidence.append(
        make_evidence(
            capture=capture,
            event_id=event_id,
            location={"x": x, "y": y},
            operation="shader_debug",
            source="ReplayController.DebugPixel",
            data={"primitive": primitive},
        )
    )

    payload = {
        "eventId": event_id,
        "pixel": {"x": x, "y": y},
        "primitive": primitive,
        "shader": {
            "stage": raw["stage"],
            "entryPoint": raw["entryPoint"],
            "resource": raw["shaderResource"],
            "pipelineObject": raw["pipelineObject"],
            "debuggable": True,
        },
        "inputs": raw["inputs"],
        "outputs": {},
        "steps": steps_out,
        "stepCount": len(steps_out),
        "truncated": raw["truncated"],
        "files": files,
        "evidence": trace_evidence,
    }
    if include_disassembly:
        payload["disassembly"] = raw["disassembly"]
    return payload


def debug_pixel(
    session,
    x,
    y,
    target=None,
    context_eid=None,
    primitive=None,
    sample=None,
    view=None,
    max_steps=4096,
    include_disassembly=True,
):
    if context_eid is None:
        context_eid = session.last_event_id()
    if target is None:
        target = choose_output_target(session, context_eid)
    target = str(target)

    query_evidence = make_evidence(
        capture=session.path,
        event_id=int(context_eid),
        resource_id=target,
        subresource={"sample": 0 if sample is None else int(sample)},
        location={"x": int(x), "y": int(y)},
        operation="pixel_history",
        source="rdebug.analysis.shader_trace",
    )

    chosen_event = context_eid
    chosen_primitive = primitive
    if primitive is None:
        history = session.pixel_history(target, x, y, context_eid=context_eid)
        candidates = [
            m
            for m in history["modifications"]
            if m["passed"] and not m.get("unboundPS") and not m.get("directShaderWrite")
        ]
        if candidates:
            chosen = candidates[-1]
            chosen_event = chosen["eventId"]
            chosen_primitive = chosen["primitiveID"]
        elif any(m.get("unboundPS") for m in history["modifications"]):
            raise QueryError(
                "pixel only has writes without a bound pixel shader; nothing to debug"
            )
        else:
            raise QueryError(
                "no passed fragment wrote to this pixel; pass --primitive explicitly"
            )

    raw = session.debug_pixel(
        x=x,
        y=y,
        primitive=chosen_primitive,
        sample=sample,
        view=view,
        eid=chosen_event,
        max_steps=max_steps,
    )
    return build_shader_trace(
        capture=session.path,
        x=x,
        y=y,
        event_id=chosen_event,
        primitive=chosen_primitive,
        raw=raw,
        include_disassembly=include_disassembly,
        evidence=[query_evidence],
    )
