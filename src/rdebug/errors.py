class RDebugError(Exception):
    pass


class RenderDocModuleNotFound(RDebugError):
    pass


class CaptureOpenError(RDebugError):
    pass


class ReplayUnsupportedError(CaptureOpenError):
    pass


class QueryError(RDebugError):
    """A query that cannot be answered for a reason the caller controls.

    kind is an optional classification carried to the transports. Transports
    already distinguish parameter problems from replay/query failures; this
    reuses that distinction instead of introducing a second error hierarchy.
    """

    def __init__(self, *args, kind=None):
        super().__init__(*args)
        self.kind = kind
