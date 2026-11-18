"""R4.1: one analysis function, three entry paths, one payload.

The CLI opens a CaptureSession directly; MCP and IDE go through
WorkerManager and the worker's JSON line protocol. This module pins the
property that matters to callers: none of the three paths reshapes the
analysis result, and JSON serialization preserves types and semantics.
"""

import inspect
import json
import pathlib
import unittest

from rdebug.analysis.resource_flow import trace_resource
from rdebug.jsonutil import to_json

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
ROWS = [
    {"eventId": 10, "usage": "Clear", "usageRaw": 1},
    {"eventId": 20, "usage": "PS_Resource", "usageRaw": 2},
]


class FakeSession:
    path = "cap.rdc"

    def usage(self, rid):
        return ROWS

    def root_actions(self):
        return []

    def last_draw_event_id(self):
        return 20


class TestSharedAnalysisFunction(unittest.TestCase):
    def test_every_entry_references_the_same_function(self):
        for rel in (
            "src/rdebug/cli.py",
            "src/rdebug_mcp/server.py",
            "src/rdebug_ide/app.py",
            "src/rdebug/workers.py",
        ):
            body = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("trace_resource", body, rel)

    def test_only_the_analysis_module_implements_it(self):
        # server.py legitimately defines a thin MCP tool of the same name;
        # it forwards to _run and must not contain analysis logic.
        offenders = []
        for path in (REPO / "src").rglob("*.py"):
            if path.name in ("resource_flow.py", "server.py"):
                continue
            if "def trace_resource(" in path.read_text(encoding="utf-8"):
                offenders.append(str(path))
        self.assertEqual(offenders, [])
        mcp = (REPO / "src/rdebug_mcp/server.py").read_text(encoding="utf-8")
        self.assertIn('_run(capture, "trace_resource"', mcp)

    def test_worker_argument_names_match_the_analysis_signature(self):
        params = set(inspect.signature(trace_resource).parameters)
        self.assertTrue({"session", "resource", "context_eid",
                         "include_other"} <= params)
        workers = (REPO / "src/rdebug/workers.py").read_text(encoding="utf-8")
        self.assertIn('a["resource"]', workers)
        for key in ("eid", "include_other"):
            self.assertIn(f'a.get("{key}"', workers)


class TestSerializationParity(unittest.TestCase):
    def test_json_roundtrip_is_semantically_identical(self):
        direct = trace_resource(FakeSession(), "ResourceId::91")
        through_worker = json.loads(to_json(direct))
        self.assertEqual(through_worker, direct)

    def test_types_survive_the_worker_protocol(self):
        payload = json.loads(to_json(trace_resource(FakeSession(), "ResourceId::91")))
        self.assertIsInstance(payload["contextEventId"], int)
        self.assertIsInstance(payload["summary"]["writerCount"], int)
        self.assertIsNone(payload["lifetime"]["endpoints"]["creation"]["eventId"])
        self.assertEqual(payload["analysisStatus"], "partial")
        self.assertEqual(payload["causal"]["edges"][0]["supportLevel"],
                         "inferred_from_order")
        for edge in payload["causal"]["edges"]:
            for ref in edge["evidenceRefs"]:
                self.assertIsInstance(ref["id"], str)

    def test_opt_out_flag_behaves_the_same_after_serialization(self):
        hidden = trace_resource(FakeSession(), "ResourceId::91", include_other=False)
        shown = trace_resource(FakeSession(), "ResourceId::91", include_other=True)
        self.assertEqual(json.loads(to_json(hidden)), hidden)
        self.assertEqual(json.loads(to_json(shown)), shown)


if __name__ == "__main__":
    unittest.main()
