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
    for row in rows:
        index[row["eventId"]] = {"name": row["name"], "flags": row["flags"]}
    return index
