"""Thin MCP transport over Semantic API v1.

This layer exposes exactly four tools 鈥?trace_pixel, trace_resource,
debug_pixel, diff_pixel 鈥?and adds nothing else: no orchestration, no
analysis logic, no RenderDoc API access, no extra domain models. Results
(including evidence) are passed through verbatim as JSON.
"""

import functools
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from rdebug.errors import RDebugError
from rdebug.jsonutil import to_json
from rdebug.session_cache import SessionManager

mcp = FastMCP("rdebug")

_session_factory = None


def _default_session_factory(capture):
    from rdebug.adapter.core import CaptureSession

    return CaptureSession(capture)


def _current_factory():
    return _session_factory or _default_session_factory


_MANAGER = SessionManager(factory_provider=_current_factory)


def _open(capture):
    return _MANAGER.use(capture)


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RDebugError as e:
            return json.dumps({"error": str(e), "tool": fn.__name__})

    return wrapper


@mcp.tool()
@_safe
def trace_pixel(
    capture: str,
    x: int,
    y: int,
    target: Optional[str] = None,
    eid: Optional[int] = None,
    mip: int = 0,
    slice: int = 0,
    sample: int = 0,
    max_draws: int = 16,
    expand_reads: bool = True,
    max_writers: int = 8,
) -> str:
    """Local causal flow graph for one pixel: Pixel -> Draw -> Shader ->
    read Resources -> Writers. Every edge carries evidence referencing the
    underlying capture facts (eventId / resourceId / operation)."""
    from rdebug.analysis.pixel_trace import trace_pixel

    with _open(capture) as session:
        payload = trace_pixel(
            session,
            x,
            y,
            target=target,
            context_eid=eid,
            mip=mip,
            slice_=slice,
            sample=sample,
            max_draws=max_draws,
            expand_reads=expand_reads,
            max_writers_per_resource=max_writers,
        )
    return to_json(payload)


@mcp.tool()
@_safe
def trace_resource(
    capture: str,
    resource: str,
    eid: Optional[int] = None,
    include_other: bool = False,
) -> str:
    """Writers and readers of one resource (usage timeline classified into
    write/read/other). Every entry carries evidence."""
    from rdebug.analysis.resource_flow import trace_resource

    with _open(capture) as session:
        payload = trace_resource(
            session, resource, context_eid=eid, include_other=include_other
        )
    return to_json(payload)


@mcp.tool()
@_safe
def debug_pixel(
    capture: str,
    x: int,
    y: int,
    target: Optional[str] = None,
    eid: Optional[int] = None,
    primitive: Optional[int] = None,
    sample: Optional[int] = None,
    view: Optional[int] = None,
    max_steps: int = 4096,
    include_disassembly: bool = True,
) -> str:
    """Structured shader debug trace for one pixel fragment: inputs, per-step
    variable changes, source/disassembly mapping. Evidence included."""
    from rdebug.analysis.shader_trace import debug_pixel

    with _open(capture) as session:
        payload = debug_pixel(
            session,
            x,
            y,
            target=target,
            context_eid=eid,
            primitive=primitive,
            sample=sample,
            view=view,
            max_steps=max_steps,
            include_disassembly=include_disassembly,
        )
    return to_json(payload)


@mcp.tool()
@_safe
def diff_pixel(
    capture: str,
    a_x: int,
    a_y: int,
    b_x: int,
    b_y: int,
    max_draws: int = 16,
    include_shader_values: bool = False,
    expand_reads: bool = True,
) -> str:
    """Compare two pixels' local causal flows and report the first provable
    divergence. States are strictly same/different/unknown; every layer entry
    carries evidence for both sides."""
    from rdebug.analysis.pixel_diff import diff_pixel

    with _open(capture) as session:
        payload = diff_pixel(
            session,
            (a_x, a_y),
            (b_x, b_y),
            max_draws=max_draws,
            include_shader_values=include_shader_values,
            expand_reads=expand_reads,
        ).to_dict()
    return to_json(payload)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
