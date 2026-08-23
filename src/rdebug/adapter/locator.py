import os
import sys
from pathlib import Path

from ..errors import RenderDocModuleNotFound

ENV_VAR = "RDEBUG_RENDERDOC_PATH"

_DEFAULT_DIRS = (
    r"C:\Program Files\RenderDoc",
    r"C:\Program Files (x86)\RenderDoc",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\RenderDoc"),
)


def candidate_dirs(explicit=None):
    dirs = []
    if explicit:
        dirs.append(Path(explicit))
    env = os.environ.get(ENV_VAR)
    if env:
        dirs.append(Path(env))
    dirs.extend(Path(p) for p in _DEFAULT_DIRS)
    return dirs


def find_module_dir(explicit=None):
    for d in candidate_dirs(explicit):
        try:
            if not d.is_dir():
                continue
            if (d / "renderdoc.pyd").exists() or (d / "renderdoc.so").exists():
                return d
        except OSError:
            continue
    return None


def import_renderdoc(explicit=None):
    d = find_module_dir(explicit)
    if d is None:
        searched = ", ".join(str(x) for x in candidate_dirs(explicit))
        raise RenderDocModuleNotFound(
            f"renderdoc python module not found. Searched: {searched}. "
            f"Set {ENV_VAR} to a directory containing renderdoc.pyd / renderdoc.so. "
            "The module is not shipped by default; build it from RenderDoc source, see "
            "docs/python_api/python_module.rst in the RenderDoc repository."
        )
    text = str(d)
    if text not in sys.path:
        sys.path.insert(0, text)
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(text)
        except OSError:
            pass
    try:
        import renderdoc
    except ImportError as e:
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise RenderDocModuleNotFound(
            f"found renderdoc module at '{text}' but importing it failed: {e}. "
            "The module binary is built for one specific CPython minor version and cannot "
            f"load under Python {ver}; rebuild RenderDoc's python module against this "
            "interpreter as described in docs/python_api/python_module.rst (custom-py-ver)."
        )
    return renderdoc
