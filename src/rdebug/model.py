from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceRef:
    id: str
    name: str = ""

    @classmethod
    def parse(cls, value):
        if isinstance(value, ResourceRef):
            return value
        if isinstance(value, dict):
            rid = value.get("id") or value.get("resource") or ""
            return cls(id=str(rid), name=str(value.get("name") or ""))
        return cls(id=str(value))

    def __str__(self):
        return self.id


_REQUIRED_HISTORY_KEYS = (
    "resource",
    "contextEventId",
    "x",
    "y",
    "modifications",
    "evidence",
)


class PixelHistoryResult:
    """First-class intermediate result shared by trace-pixel / debug-pixel /
    evidence consumers. Wraps the adapter's dict payload; Layer 2 never sees
    native RenderDoc objects."""

    def __init__(self, payload):
        self._payload = payload

    @classmethod
    def parse(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            missing = [k for k in _REQUIRED_HISTORY_KEYS if k not in value]
            if missing:
                raise TypeError(
                    "pixel history payload missing keys: {}".format(", ".join(missing))
                )
            return cls(value)
        raise TypeError("cannot parse PixelHistoryResult from " + type(value).__name__)

    @property
    def payload(self):
        return self._payload

    @property
    def resource(self):
        return self._payload["resource"]

    @property
    def context_event_id(self):
        return self._payload["contextEventId"]

    @property
    def modifications(self):
        return self._payload["modifications"]

    def to_dict(self):
        return self._payload


class DiffResult:
    """Result of comparing two local pixel flows. comparison is one of
    "same" / "different" / "unknown" — never a similarity score."""

    def __init__(self, payload):
        self._payload = payload

    @classmethod
    def parse(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            for key in ("comparison", "layers", "a", "b", "evidence"):
                if key not in value:
                    raise TypeError(f"diff payload missing key: {key}")
            if value["comparison"] not in ("same", "different", "unknown"):
                raise TypeError("invalid comparison state")
            return cls(value)
        raise TypeError("cannot parse DiffResult from " + type(value).__name__)

    @property
    def payload(self):
        return self._payload

    @property
    def comparison(self):
        return self._payload["comparison"]

    @property
    def equal(self):
        return self._payload["comparison"] == "same"

    @property
    def first_divergence(self):
        return self._payload.get("firstDivergence")

    def to_dict(self):
        return self._payload
