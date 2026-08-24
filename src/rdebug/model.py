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
