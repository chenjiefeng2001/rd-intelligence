"""Thin MCP transport over Semantic API v1.

This layer exposes exactly four tools — trace_pixel, trace_resource,
debug_pixel, diff_pixel — and adds nothing else: no orchestration, no
analysis logic, no RenderDoc API access, no extra domain models. Results
(including evidence) are passed through verbatim as JSON.

M1.3: each capture is served by a dedicated worker process, one replay
runtime per capture, instead of an in-process SessionManager. DESIGN_SPEC
§2.9 first MUST: the RenderDoc in-process replay runtime does not
safely support multiple live controllers, which produced silent value
corruption, native hangs and 0xC0000005 (W1-R1 F-1/F-2). MCP is where
that was most exposed, because `capture` is a per-call argument to all
four tools and the old manager defaulted to holding four sessions at once.

Stable Core is untouched. The tools are thin wrappers that forward their
arguments to a worker and return its JSON.
"""

import functools
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from rdebug.errors import RDebugError
from rdebug.jsonutil import to_json
from rdebug.worker_manager import RecyclePolicy, WorkerManager

mcp = FastMCP("rdebug")

# One worker process per capture, recycled on the frozen W1-R4 policy
# (q250 / 128MB private-memory delta / 1800s). The policy values are
# engineering defaults, not architectural constants (DESIGN_SPEC §2.9).
_WORKERS = WorkerManager(recycle=RecyclePolicy.production_default())


def _run(capture, tool, **args):
    """Forward a tool call to the capture's worker process.

    Arguments whose value is None are dropped so the worker's own defaults
    apply, exactly as Python's did on the in-process path. `include_disassembly
    =False` and similar falsy-but-meaningful values are preserved -- only
    None is dropped, because forwarding None would override a worker's
    default with a null it never expected (e.g. sample=None in place of 0).
    """
    return _WORKERS.query(capture, tool,
                          **{k: v for k, v in args.items() if v is not None})


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from rdebug.observability import record, record_result, timed

        try:
            with timed("query", transport="mcp", tool=fn.__name__):
                result = fn(*args, **kwargs)
            try:
                record_result("mcp", fn.__name__, json.loads(result))
            except Exception:
                pass
            return result
        except RDebugError as e:
            # WorkerError derives from RDebugError, so a dead worker, a spawn
            # failure and a bad capture all arrive here and become an
            # error payload rather than an unhandled tool error (M1.0/D3).
            record("query_error", transport="mcp", tool=fn.__name__,
                   error=str(e))
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
    return to_json(_run(
        capture, "trace_pixel", x=x, y=y, target=target, eid=eid, mip=mip,
        slice=slice, sample=sample, max_draws=max_draws,
        expand_reads=expand_reads, max_writers=max_writers))


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
    return to_json(_run(capture, "trace_resource", resource=resource, eid=eid,
                        include_other=include_other))


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
    return to_json(_run(
        capture, "debug_pixel", x=x, y=y, target=target, eid=eid,
        primitive=primitive, sample=sample, view=view, max_steps=max_steps,
        include_disassembly=include_disassembly))


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
    return to_json(_run(
        capture, "diff_pixel", a_x=a_x, a_y=a_y, b_x=b_x, b_y=b_y,
        max_draws=max_draws, include_shader_values=include_shader_values,
        expand_reads=expand_reads))


def main():
    try:
        mcp.run()
    finally:
        # Dispose every worker rather than leaving a live replay runtime per
        # capture behind in a process that is exiting anyway.
        _WORKERS.dispose_all()


if __name__ == "__main__":
    main()

