import unittest

from rdebug.analysis.shader_trace import build_shader_trace, resolve_inst_info

RAW = {
    "stage": "Pixel",
    "entryPoint": "PSMain",
    "shaderResource": "ResourceId(7)",
    "pipelineObject": "ResourceId(3)",
    "files": [
        {"index": 0, "filename": "ps.hlsl"},
        {"index": 1, "filename": "common.hlsli"},
    ],
    "disassembly": "\n".join(
        [
            "ps_5_0",
            "dcl_globalFlags refactoringAllowed",
            "mov o0.xyzw, r0.xyzw",
            "ret",
        ]
    ),
    "steps": [
        {"stepIndex": 0, "nextInstruction": 0, "events": 0, "callstack": [], "changes": []},
        {
            "stepIndex": 1,
            "nextInstruction": 2,
            "events": 1,
            "callstack": ["PSMain"],
            "changes": [
                {
                    "before": {"name": "input.color", "type": "Float", "rows": 1, "columns": 4},
                    "after": {"name": "input.color", "type": "Float", "rows": 1, "columns": 4,
                              "value": [0.5, 0.5, 0.5, 1.0]},
                }
            ],
        },
        {"stepIndex": 2, "nextInstruction": 3, "events": 0, "callstack": ["PSMain"], "changes": []},
    ],
    "instInfo": [
        {"instruction": 0, "disassemblyLine": 1, "fileIndex": -1,
         "lineStart": 0, "lineEnd": 0, "colStart": 0, "colEnd": 0},
        {"instruction": 2, "disassemblyLine": 3, "fileIndex": 0,
         "lineStart": 42, "lineEnd": 42, "colStart": 5, "colEnd": 20},
    ],
    "inputs": [{"name": "input.color", "type": "Float", "rows": 1, "columns": 4}],
    "constantBlocks": [],
    "truncated": False,
}


class TestResolveInstInfo(unittest.TestCase):
    def test_exact_and_lower_bound(self):
        self.assertEqual(resolve_inst_info(RAW["instInfo"], 2)["instruction"], 2)
        self.assertEqual(resolve_inst_info(RAW["instInfo"], 3)["instruction"], 2)
        self.assertEqual(resolve_inst_info(RAW["instInfo"], 99)["instruction"], 2)

    def test_below_first_returns_none(self):
        rows = [r for r in RAW["instInfo"] if r["instruction"] > 0]
        self.assertIsNone(resolve_inst_info(rows, 0))


class TestBuildShaderTrace(unittest.TestCase):
    def test_shape_and_contract(self):
        trace = build_shader_trace("cap.rdc", 824, 391, 1821, 3, RAW)
        self.assertEqual(trace["eventId"], 1821)
        self.assertEqual(trace["primitive"], 3)
        self.assertEqual(trace["pixel"], {"x": 824, "y": 391})
        self.assertEqual(trace["shader"]["entryPoint"], "PSMain")
        self.assertEqual(trace["outputs"], {})
        self.assertEqual(trace["stepCount"], 3)
        self.assertFalse(trace["truncated"])
        self.assertIn("disassembly", trace)

    def test_source_resolution_per_step(self):
        trace = build_shader_trace("cap.rdc", 1, 2, 10, None, RAW)
        first = trace["steps"][0]
        self.assertNotIn("sourceFile", first)
        mid = trace["steps"][1]
        self.assertEqual(mid["source"]["line"], 42)
        self.assertEqual(mid["disassemblyText"], "mov o0.xyzw, r0.xyzw")
        self.assertEqual(mid["sourceFile"], "ps.hlsl")

    def test_no_disassembly_flag(self):
        trace = build_shader_trace("cap.rdc", 1, 2, 10, None, RAW, include_disassembly=False)
        self.assertNotIn("disassembly", trace)
        self.assertNotIn("disassemblyText", trace["steps"][1])

    def test_evidence_attached(self):
        trace = build_shader_trace("cap.rdc", 1, 2, 10, None, RAW)
        ops = [ev["operation"] for ev in trace["evidence"]]
        self.assertIn("shader_debug", ops)
        for ev in trace["evidence"]:
            self.assertIn("id", ev)


if __name__ == "__main__":
    unittest.main()
