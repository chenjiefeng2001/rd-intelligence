import argparse
import json
import sys

from . import __version__
from .errors import RDebugError
from .jsonutil import to_json


def _emit(value, indent):
    sys.stdout.write(to_json(value, indent=indent))
    sys.stdout.write("\n")


def _fail(message, code=2):
    sys.stderr.write(json.dumps({"error": str(message)}))
    sys.stderr.write("\n")
    return code


def _open_session(args):
    from .adapter.core import CaptureSession

    rd_path = getattr(args, "rd_path", None)
    session = CaptureSession(args.capture, rd_path=rd_path)
    return session


def _add_common(p):
    p.add_argument("capture", help="path to the .rdc capture file")
    p.add_argument(
        "--rd-path",
        default=None,
        help="directory containing renderdoc.pyd / renderdoc.so "
        "(or set RDEBUG_RENDERDOC_PATH)",
    )


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="rdebug",
        description="RenderDoc debug intelligence layer: evidence-first JSON queries "
        "over RenderDoc captures (Layer 1 adapter + Layer 2 query/analysis).",
    )
    parser.add_argument("--version", action="version", version="rdebug " + __version__)
    sub = parser.add_subparsers(dest="command")

    info = sub.add_parser("info", help="capture metadata summary")
    _add_common(info)

    events = sub.add_parser("events", help="list actions/events")
    _add_common(events)
    events.add_argument("--min-eid", type=int, default=None)
    events.add_argument("--max-eid", type=int, default=None)
    events.add_argument("--name", default=None, help="case-insensitive name substring")
    events.add_argument("--limit", type=int, default=None)

    draws = sub.add_parser("draws", help="list drawcalls only")
    draws.add_argument("--min-eid", type=int, default=None)
    draws.add_argument("--max-eid", type=int, default=None)
    draws.add_argument("--name", default=None, help="case-insensitive name substring")
    draws.add_argument("--limit", type=int, default=None)

    resources = sub.add_parser("resources", help="list resources")
    _add_common(resources)
    resources.add_argument("--name", default=None)
    resources.add_argument("--limit", type=int, default=None)

    textures = sub.add_parser("textures", help="list textures")
    _add_common(textures)
    textures.add_argument("--limit", type=int, default=None)

    buffers = sub.add_parser("buffers", help="list buffers")
    _add_common(buffers)
    buffers.add_argument("--limit", type=int, default=None)

    pipeline = sub.add_parser("pipeline", help="pipeline state snapshot at an event")
    _add_common(pipeline)
    pipeline.add_argument("--eid", type=int, required=True)

    usage = sub.add_parser("usage", help="resource usage timeline")
    _add_common(usage)
    usage.add_argument("--resource", required=True)

    history = sub.add_parser("pixel-history", help="pixel history on a target resource")
    _add_common(history)
    history.add_argument("--target", required=True, help="resource id of the texture")
    history.add_argument("--x", type=int, required=True)
    history.add_argument("--y", type=int, required=True)
    history.add_argument("--mip", type=int, default=0)
    history.add_argument("--slice", type=int, default=0)
    history.add_argument("--sample", type=int, default=0)
    history.add_argument("--eid", type=int, default=None,
                         help="context event id (default: last event in frame)")

    trace = sub.add_parser("trace-pixel", help="lazy dependency graph for one pixel")
    _add_common(trace)
    trace.add_argument("--x", type=int, required=True)
    trace.add_argument("--y", type=int, required=True)
    trace.add_argument("--target", default=None, help="resource id (default: first color output)")
    trace.add_argument("--eid", type=int, default=None)
    trace.add_argument("--mip", type=int, default=0)
    trace.add_argument("--slice", type=int, default=0)
    trace.add_argument("--sample", type=int, default=0)
    trace.add_argument("--max-draws", type=int, default=16)

    dbg = sub.add_parser(
        "debug-pixel",
        help="run the RenderDoc shader debugger on one pixel fragment and emit a structured trace",
    )
    _add_common(dbg)
    dbg.add_argument("--x", type=int, required=True)
    dbg.add_argument("--y", type=int, required=True)
    dbg.add_argument("--target", default=None, help="resource id (default: first color output)")
    dbg.add_argument("--eid", type=int, default=None,
                     help="context event id (default: last event in frame)")
    dbg.add_argument("--primitive", type=int, default=None,
                     help="primitive id to debug (default: auto-pick from pixel history)")
    dbg.add_argument("--sample", type=int, default=None)
    dbg.add_argument("--view", type=int, default=None)
    dbg.add_argument("--max-steps", type=int, default=4096)
    dbg.add_argument("--no-disassembly", action="store_true")

    indent = parser.add_argument("-i", "--indent", type=int, default=2)
    indent.help = "JSON indentation"
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    global_indent = 2
    cleaned = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in ("-i", "--indent"):
            global_indent = int(argv[i + 1])
            i += 2
            continue
        if token.startswith("--indent="):
            global_indent = int(token.split("=", 1)[1])
            i += 1
            continue
        cleaned.append(token)
        i += 1
    argv = cleaned

    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return _dispatch(args, global_indent)
    except RDebugError as e:
        return _fail(e)
    except KeyboardInterrupt:
        return _fail("interrupted", code=130)


def _dispatch(args, indent):
    cmd = args.command
    if cmd == "info":
        with _open_session(args) as s:
            rows = s.action_rows(limit=None)
            payload = {
                "file": s.path,
                "driver": s.driver,
                **s.api_info(),
                "eventCount": len(rows),
                "lastEventId": max((r["eventId"] for r in rows), default=0),
                "textureCount": len(s.textures()),
                "bufferCount": len(s.buffers()),
            }
        _emit(payload, indent)
        return 0
    if cmd == "events":
        with _open_session(args) as s:
            rows = s.action_rows(
                min_eid=args.min_eid,
                max_eid=args.max_eid,
                name=args.name,
                limit=args.limit,
            )
        _emit({"events": rows, "count": len(rows)}, indent)
        return 0
    if cmd == "draws":
        with _open_session(args) as s:
            rows = s.draw_rows(
                min_eid=args.min_eid,
                max_eid=args.max_eid,
                name=args.name,
                limit=args.limit,
            )
        _emit({"draws": rows, "count": len(rows)}, indent)
        return 0
    if cmd == "resources":
        with _open_session(args) as s:
            rows = s.resources(name=args.name, limit=args.limit)
        _emit({"resources": rows, "count": len(rows)}, indent)
        return 0
    if cmd == "textures":
        with _open_session(args) as s:
            rows = s.textures(limit=args.limit)
        _emit({"textures": rows, "count": len(rows)}, indent)
        return 0
    if cmd == "buffers":
        with _open_session(args) as s:
            rows = s.buffers(limit=args.limit)
        _emit({"buffers": rows, "count": len(rows)}, indent)
        return 0
    if cmd == "pipeline":
        with _open_session(args) as s:
            payload = s.pipeline(args.eid)
        _emit(payload, indent)
        return 0
    if cmd == "usage":
        with _open_session(args) as s:
            rows = s.usage(args.resource)
        _emit({"resource": args.resource, "usages": rows}, indent)
        return 0
    if cmd == "pixel-history":
        with _open_session(args) as s:
            payload = s.pixel_history(
                args.target,
                args.x,
                args.y,
                mip=args.mip,
                slice_=args.slice,
                sample=args.sample,
                context_eid=args.eid,
            )
        _emit(payload, indent)
        return 0
    if cmd == "trace-pixel":
        from .analysis.pixel_trace import trace_pixel

        with _open_session(args) as s:
            payload = trace_pixel(
                s,
                args.x,
                args.y,
                target=args.target,
                context_eid=args.eid,
                mip=args.mip,
                slice_=args.slice,
                sample=args.sample,
                max_draws=args.max_draws,
            )
        _emit(payload, indent)
        return 0
    if cmd == "debug-pixel":
        from .analysis.shader_trace import debug_pixel

        with _open_session(args) as s:
            payload = debug_pixel(
                s,
                args.x,
                args.y,
                target=args.target,
                context_eid=args.eid,
                primitive=args.primitive,
                sample=args.sample,
                view=args.view,
                max_steps=args.max_steps,
                include_disassembly=not args.no_disassembly,
            )
        _emit(payload, indent)
        return 0
    return _fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    sys.exit(main())
