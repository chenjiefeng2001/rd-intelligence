"""Capture path and query-limit policy.

WHY THIS EXISTS
===============
`capture` is a caller-supplied string. It reaches `subprocess.Popen` as a worker
argument and the worker opens it. Before this module the only transformation was
`os.path.abspath`, which makes the path absolute but does not constrain *where*
it may point. Any entity able to reach a query surface -- an AI agent driving the
MCP tools, a prompt-injected instruction, a local process -- could therefore
name an arbitrary path and have the worker open it.

The policy is deny-by-default with an explicit opt-in:

  * ``RDEBUG_CAPTURE_ROOT`` -- ``os.pathsep``-separated list of directories that
    are allowed. When set, it replaces the default entirely.
  * when unset, the single allowed root is the repository's canonical corpus
    directory, which is what the declared fixtures live in.

An operator who legitimately needs a different tree sets the variable. Nobody
has to widen the policy to use the tool on the corpus.

This is deliberately NOT a sandbox: it constrains the *path*, not the process.
It closes arbitrary-file-read through a query surface; it is not a substitute for
running the surface on a host you do not trust.

QUERY LIMITS
============
``max_draws`` and friends arrived from the caller unclamped. A causal graph over
a wide pixel can expand combinatorially, and the worker recycle policy
(250 quanta / 128 MB / 1800 s) is a *backstop*, not a *prevention*. The values
here are ceilings, not defaults: a caller asking for fewer still gets fewer.
"""
import os

from .errors import RDebugError

# Server-side ceilings. A caller asking for more is clamped down to these.
MAX_DRAWS = 256
MAX_WRITERS = 64
MAX_READS = 256

ENV_ROOTS = "RDEBUG_CAPTURE_ROOT"


class CapturePathError(RDebugError):
    """The requested capture is outside every allowed root, or is not a file."""


def _repo_root():
    # src/rdebug/capture_policy.py -> src/rdebug -> src -> repo root
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.dirname(here)
    return os.path.dirname(src)


def default_root():
    return os.path.join(_repo_root(), "tests", "workload", "corpus")


def allowed_roots():
    """Directories a capture may live in.

    The environment variable replaces the default rather than adding to it, so
    pointing at a different tree cannot silently leave the corpus open too.
    """
    raw = os.environ.get(ENV_ROOTS, "").strip()
    if not raw:
        return [default_root()]
    roots = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(os.path.abspath(part))
    return roots or [default_root()]


def _within(candidate, root):
    if candidate == root:
        return True
    return candidate.startswith(root.rstrip(os.sep) + os.sep)


def resolve_capture(capture):
    """Return the absolute capture path, or raise `CapturePathError`.

    The check is `abspath` + commonpath rather than string prefixing so that a
    sibling directory whose name merely starts with the root's name (for example
    ``corpus-evil`` next to ``corpus``) is rejected.
    """
    if capture is None or not str(capture).strip():
        raise CapturePathError("capture path is empty")
    path = os.path.abspath(str(capture))
    roots = allowed_roots()
    for root in roots:
        try:
            if os.path.commonpath([path, root]) == root and _within(path, root):
                break
        except ValueError:
            # Different drives on Windows: no shared path, so not a match.
            continue
    else:
        raise CapturePathError(
            "capture path is outside the allowed capture root(s); "
            f"set {ENV_ROOTS} to widen the policy"
        )
    if not os.path.exists(path):
        raise CapturePathError("capture file does not exist")
    if not os.path.isfile(path):
        raise CapturePathError("capture path is not a file")
    return path


def clamp_limits(max_draws=None, max_writers=None, expand_reads=None):
    """Clamp caller-supplied query limits to the server-side ceilings."""
    out = {}
    if max_draws is not None:
        out["max_draws"] = max(1, min(int(max_draws), MAX_DRAWS))
    if max_writers is not None:
        out["max_writers"] = max(1, min(int(max_writers), MAX_WRITERS))
    if expand_reads is not None:
        out["expand_reads"] = bool(expand_reads)
    return out


def redact(text, capture=None):
    """Replace absolute filesystem paths so a query error cannot map the host.

    Only paths that actually appear are rewritten, and the caller-supplied
    capture is redacted first so a `<capture>` token is not shadowed by its own
    expanded form.
    """
    out = str(text)
    if capture:
        for candidate in (os.path.abspath(str(capture)), str(capture)):
            if candidate:
                out = out.replace(candidate, "<capture>")
    roots = allowed_roots()
    for root in roots:
        if not root:
            continue
        # A message may contain only a prefix of the root (a truncated path, or
        # a directory above it), so every ancestor prefix is rewritten too --
        # longest first, otherwise a short prefix would leave the tail of a
        # longer one behind.
        tail = root
        while tail:
            if tail in out:
                out = out.replace(tail, "<capture-root>")
            parent = os.path.dirname(tail)
            if parent == tail:
                break
            tail = parent
    return out
