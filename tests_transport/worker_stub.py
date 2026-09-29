"""Shared worker-boundary test doubles for the transport suite.

Since M1.3 the MCP transport does not call the semantic functions itself:
it forwards arguments to a worker process via WorkerManager. Tests that
want a payload without a real RenderDoc need a stand-in for that boundary.

The doubles here are built on rdebug.workers._dispatch(), the REAL
argument mapping the worker uses, so using them also covers the mapping
between the MCP tool signatures and the worker -- which would otherwise
break silently if a parameter were renamed on either side (M0 scope
§5.6-2).
"""
import json


class RecordingWorkers:
    """WorkerManager stand-in that runs the real dispatch in-process.

    Records what the worker would have seen, and mirrors the two behaviours
    a transport actually depends on: the capture is injected into the
    forwarded args, and a domain error comes back as a payload rather than
    an exception (workers.py:214-216).
    """

    def __init__(self, session):
        self.session = session
        self.calls = []
        # One entry per capture served, mirroring WorkerManager's registry:
        # reuse is keyed by capture, not by (capture, tool).
        self.spawned = []
        self.query_log = []
        # Ownership tracking, so a lifecycle test can assert that whatever
        # configure() established is actually released by dispose().
        self.disposed = 0
        self.live = []
        self.recycle_events = []
        self.unkillable_report = []

    def _note_spawn(self, capture):
        if capture not in self.spawned:
            self.spawned.append(capture)
        if capture not in self.live:
            self.live.append(capture)

    def query(self, capture, tool, timeout=600, **args):
        from rdebug.errors import RDebugError
        from rdebug.jsonutil import to_json
        from rdebug.workers import _dispatch

        args = dict(args)
        args.setdefault("capture", capture)
        self.calls.append((capture, tool, dict(args)))
        self.query_log.append((capture, tool))
        self._note_spawn(capture)
        fn = _dispatch().get(tool)
        if fn is None:
            raise RuntimeError(f"unknown tool {tool!r}")
        try:
            return json.loads(to_json(fn(self.session, **args)))
        except RDebugError as e:
            return json.loads(json.dumps({"error": str(e), "tool": tool}))

    def ping(self, capture, timeout=60):
        self.query_log.append((capture, "ping"))
        self._note_spawn(capture)
        return True

    def captures(self):
        return list(self.live)

    def unkillable(self):
        return list(self.unkillable_report)

    def dispose_all(self):
        self.disposed += 1
        self.live = []
