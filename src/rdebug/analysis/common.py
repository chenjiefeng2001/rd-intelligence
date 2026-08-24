from ..errors import QueryError
from ..query.events import build_action_index, flatten_actions


def choose_output_target(session, context_eid):
    pipe = session.pipeline(context_eid)
    outs = pipe.get("outputTargets") or []
    depth = pipe.get("depthTarget")
    if outs:
        return outs[0]["resource"]
    if depth:
        return depth["resource"]
    raise QueryError(
        f"no output targets bound at event {context_eid}; pass --target explicitly"
    )


def actions_index_for(session):
    rows_fn = getattr(session, "action_rows", None)
    if rows_fn is not None:
        return build_action_index(rows_fn())
    return build_action_index(flatten_actions(session.root_actions()))
