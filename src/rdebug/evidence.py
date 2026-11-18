import hashlib
import json

from .errors import QueryError

_FIELDS = ("capture", "eventId", "resourceId", "subresource", "location", "operation", "source")
_STATUS = ("observed", "inferred", "unknown")
_V2_FIELDS = (
    "status",
    "queryId",
    "revision",
    "qualifiedId",
    "sourceRef",
    "observation",
    "inference",
)


def make(
    capture=None,
    event_id=None,
    resource_id=None,
    subresource=None,
    location=None,
    operation=None,
    source=None,
    data=None,
    status=None,
    query_id=None,
    revision=None,
    source_ref=None,
    observation=None,
    inference=None,
):
    """Build an evidence record.

    The stable ``id`` is computed from the reference fields only. Everything
    added by the v2 protocol -- including ``revision`` and ``data`` -- is
    written *after* that computation, so an existing record's identity never
    changes when a caller starts supplying the new optional arguments.
    """
    ev = {}
    if capture is not None:
        ev["capture"] = str(capture)
    if event_id is not None:
        ev["eventId"] = int(event_id)
    if resource_id is not None:
        ev["resourceId"] = str(resource_id)
    if subresource is not None:
        ev["subresource"] = subresource
    if location is not None:
        ev["location"] = location
    if operation is not None:
        ev["operation"] = str(operation)
    if source is not None:
        ev["source"] = str(source)
    ev["id"] = _stable_id(ev)

    if status is not None:
        if status not in _STATUS:
            raise ValueError("invalid evidence status: " + str(status))
        ev["status"] = status
    if query_id is not None:
        ev["queryId"] = str(query_id)
    if revision is not None:
        ev["revision"] = str(revision)
        ev["qualifiedId"] = _qualified_id(ev["id"], ev["revision"])
    if source_ref is not None:
        ev["sourceRef"] = source_ref
    if observation is not None:
        ev["observation"] = observation
    if inference is not None:
        ev["inference"] = inference
    if data is not None:
        ev["data"] = data
    return ev


def _stable_id(ev):
    canonical = json.dumps(ev, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def _qualified_id(evidence_id, revision):
    canonical = f"{evidence_id}|{revision}"
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def record(observation=None, inference=None, **kwargs):
    """Build a v2 evidence record with an honest status.

    A record with no observation is ``unknown``; an observation with no
    inference is ``observed``; an observation plus an inference is
    ``inferred``. An inference without an observation is *not* upgraded to an
    observed fact -- that is the exact shape of the F12 class of defect.
    """
    if observation is None:
        status = "unknown"
    elif inference is None:
        status = "observed"
    else:
        status = "inferred"
    kwargs.setdefault("status", status)
    return make(observation=observation, inference=inference, **kwargs)


def validate(ev, strict=False):
    if not isinstance(ev, dict):
        raise TypeError("evidence must be a dict")
    if "id" not in ev:
        raise ValueError("evidence missing stable id")
    if not any(field in ev for field in _FIELDS):
        raise ValueError("evidence must reference at least one of: " + ", ".join(_FIELDS))
    if strict:
        status = ev.get("status")
        if status not in _STATUS:
            raise ValueError("strict evidence requires status in " + ", ".join(_STATUS))
        if "revision" not in ev or "qualifiedId" not in ev:
            raise ValueError("strict evidence requires revision and qualifiedId")
        expected = _qualified_id(ev["id"], ev["revision"])
        if ev["qualifiedId"] != expected:
            raise ValueError("evidence qualifiedId does not match id and revision")
        if status in ("observed", "inferred") and "observation" not in ev:
            raise ValueError(status + " evidence requires an observation")
        if status == "unknown" and ev.get("observation") is not None:
            raise ValueError("unknown evidence must not carry an observation")
    return True


def ref(ev, qualified=False):
    """Project an evidence reference.

    The default shape is intentionally unchanged: callers that only need the
    stable id must see exactly ``{"id": ...}``.
    """
    projection = {"id": ev["id"]}
    if qualified:
        if "revision" not in ev or "qualifiedId" not in ev:
            raise QueryError("evidence has no revision; cannot form a qualified reference")
        projection["revision"] = ev["revision"]
        projection["qualifiedId"] = ev["qualifiedId"]
    return projection


def require_observed(evidences):
    """Reject a result that would treat unknown evidence as an observation.

    Callers that are about to draw a content conclusion call this first. It is
    a guard, not a converter: an unknown item stays unknown and aborts the
    conclusion, rather than being silently dropped or read as empty.
    """
    for ev in evidences or ():
        status = ev.get("status", "observed")
        if status == "unknown":
            raise QueryError(
                "cannot conclude from unknown evidence: " + str(ev.get("id")),
                kind="unknown_evidence",
            )
    return True
