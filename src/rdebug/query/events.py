def flatten_actions(root_actions, draw_flag=None):
    rows = []
    stack = [(action, 0, None) for action in reversed(list(root_actions))]
    while stack:
        action, depth, parent_eid = stack.pop()
        flags = int(action.flags)
        row = {
            "eventId": int(action.eventId),
            "actionId": int(getattr(action, "actionId", 0)),
            "name": str(action.customName or ""),
            "flags": flags,
            "depth": depth,
            "parentEventId": parent_eid,
            "numIndices": int(getattr(action, "numIndices", 0)),
            "numInstances": int(getattr(action, "numInstances", 0)),
            "childCount": len(list(getattr(action, "children", []) or [])),
        }
        if draw_flag is not None:
            row["isDraw"] = bool(flags & int(draw_flag))
        children = list(getattr(action, "children", []) or [])
        for child in reversed(children):
            stack.append((child, depth + 1, int(action.eventId)))
        rows.append(row)
    return rows


def filter_rows(
    rows,
    min_eid=None,
    max_eid=None,
    name=None,
    only_draws=False,
    limit=None,
):
    out = []
    needle = name.lower() if name else None
    for row in rows:
        if min_eid is not None and row["eventId"] < int(min_eid):
            continue
        if max_eid is not None and row["eventId"] > int(max_eid):
            continue
        if only_draws and not row.get("isDraw", False):
            continue
        if needle is not None and needle not in row["name"].lower():
            continue
        out.append(row)
        if limit is not None and len(out) >= int(limit):
            break
    return out


def build_action_index(rows):
    index = {}
    semantics_keys = (
        "isDraw",
        "isClear",
        "isDispatch",
        "mayModifyPixel",
        "fragmentCandidate",
    )
    for row in rows:
        entry = {"name": row["name"], "flags": row["flags"]}
        for key in semantics_keys:
            if key in row:
                entry[key] = row[key]
        index[row["eventId"]] = entry
    return index


def event_semantics(flags, *, draw_flag, clear_flags, dispatch_flags):
    """Semantic predicate over ActionFlags. A clear event may modify the pixel
    (authoritative PixelHistory fact) but can never be a fragment candidate:
    no pixel shader invocation happens for it."""
    f = int(flags)
    is_draw = bool(f & int(draw_flag))
    is_clear = any(f & int(c) for c in clear_flags)
    is_dispatch = any(f & int(d) for d in dispatch_flags)
    return {
        "isDraw": is_draw,
        "isClear": is_clear,
        "isDispatch": is_dispatch,
        "mayModifyPixel": is_draw or is_clear,
        "fragmentCandidate": is_draw and not is_clear and not is_dispatch,
    }
