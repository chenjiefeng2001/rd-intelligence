import hashlib
import json

_FIELDS = ("capture", "eventId", "resourceId", "subresource", "location", "operation", "source")


def make(
    capture=None,
    event_id=None,
    resource_id=None,
    subresource=None,
    location=None,
    operation=None,
    source=None,
    data=None,
):
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
    if data is not None:
        ev["data"] = data
    return ev


def _stable_id(ev):
    canonical = json.dumps(ev, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def validate(ev):
    if not isinstance(ev, dict):
        raise TypeError("evidence must be a dict")
    if "id" not in ev:
        raise ValueError("evidence missing stable id")
    if not any(field in ev for field in _FIELDS):
        raise ValueError("evidence must reference at least one of: " + ", ".join(_FIELDS))
    return True


def ref(ev):
    return {"id": ev["id"]}
