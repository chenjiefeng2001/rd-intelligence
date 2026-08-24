from ..errors import QueryError


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
