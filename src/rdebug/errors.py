class RDebugError(Exception):
    pass


class RenderDocModuleNotFound(RDebugError):
    pass


class CaptureOpenError(RDebugError):
    pass


class ReplayUnsupportedError(CaptureOpenError):
    pass


class QueryError(RDebugError):
    pass
