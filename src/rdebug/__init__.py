__version__ = "0.1.0"

_SEMANTIC_API_V1 = {
    "trace_pixel": ("rdebug.analysis.pixel_trace", "trace_pixel"),
    "trace_resource": ("rdebug.analysis.resource_flow", "trace_resource"),
    "debug_pixel": ("rdebug.analysis.shader_trace", "debug_pixel"),
    "diff_pixel": ("rdebug.analysis.pixel_diff", "diff_pixel"),
}


def __getattr__(name):
    if name in _SEMANTIC_API_V1:
        import importlib

        module_name, attr = _SEMANTIC_API_V1[name]
        return getattr(importlib.import_module(module_name), attr)
    raise AttributeError(name)


def __dir__():
    return sorted(list(globals()) + list(_SEMANTIC_API_V1))
