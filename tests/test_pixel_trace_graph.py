import unittest

from rdebug.analysis.pixel_trace import build_graph


def history(target="ResourceId(91)", mods=None):
    return {
        "resource": target,
        "contextEventId": 500,
        "x": 824,
        "y": 391,
        "mip": 0,
        "slice": 0,
        "sample": 0,
        "modifications": mods
        or [
            {
                "eventId": 100,
                "primitiveID": 0,
                "fragIndex": 0,
                "passed": False,
                "unboundPS": False,
                "directShaderWrite": False,
                "preMod": {"float": [0.0, 0.0, 0.0, 0.0], "depth": -1.0, "stencil": -1},
                "shaderOut": {"float": [0.1, 0.2, 0.3, 1.0], "depth": -1.0, "stencil": -1},
                "postMod": {"float": [0.1, 0.2, 0.3, 1.0], "depth": -1.0, "stencil": -1},
                "depthTestFailed": True,
            },
            {
                "eventId": 200,
                "primitiveID": 2,
                "fragIndex": 0,
                "passed": True,
                "unboundPS": False,
                "directShaderWrite": False,
                "preMod": {"float": [0.1, 0.2, 0.3, 1.0], "depth": -1.0, "stencil": -1},
                "shaderOut": {"float": [0.0, 0.0, 0.0, 1.0], "depth": -1.0, "stencil": -1},
                "postMod": {"float": [0.0, 0.0, 0.0, 1.0], "depth": -1.0, "stencil": -1},
            },
        ],
    }


PIPELINES = {
    100: {
        "shaders": {},
        "descriptors": [],
        "indexBuffer": None,
    },
    200: {
        "shaders": {"Pixel": {"resource": "ResourceId(7)", "entryPoint": "main"}},
        "descriptors": [
            {"stage": "Pixel", "type": "ReadOnlyResource", "index": 0,
             "resource": "ResourceId(42)", "sampler": None}
        ],
        "indexBuffer": {"resource": "ResourceId(9)"},
    },
}


class TestBuildGraph(unittest.TestCase):
    def test_nodes_and_edges(self):
        graph = build_graph(
            {"x": 824, "y": 391},
            history(),
            PIPELINES,
            actions={100: {"name": "", "flags": 0}, 200: {"name": "Shade", "flags": 0}},
            target="ResourceId(91)",
        )
        ids = {n["id"] for n in graph["nodes"]}
        self.assertIn("pixel:824,391", ids)
        self.assertIn("target:ResourceId(91)", ids)
        self.assertIn("draw:100", ids)
        self.assertIn("draw:200", ids)
        self.assertIn("shader:200:ResourceId(7)", ids)
        self.assertIn("resource:ResourceId(42)", ids)
        self.assertIn("resource:ResourceId(9)", ids)

        edge_labels = sorted(e["label"] for e in graph["edges"])
        self.assertIn("writes", edge_labels)
        self.assertIn("bound_ps", edge_labels)
        self.assertIn("reads", edge_labels)
        self.assertIn("reads_indices", edge_labels)

        writes = [e for e in graph["edges"] if e["label"] == "writes"]
        passed_write = [e for e in writes if e["evidence"]["eventId"] == 200]
        self.assertEqual(passed_write[0]["evidence"]["primitives"], [2])
        self.assertEqual(passed_write[0]["evidence"]["postMod"]["float"],
                         [0.0, 0.0, 0.0, 1.0])

        summary = graph["summary"]
        self.assertEqual(summary["modificationCount"], 2)
        self.assertEqual(summary["writeEventCount"], 2)
        self.assertEqual(summary["finalValue"]["float"], [0.0, 0.0, 0.0, 1.0])

    def test_failed_event_has_no_shader_edge_but_kept_as_node(self):
        graph = build_graph({"x": 1, "y": 2}, history(), PIPELINES)
        failed_edges = [
            e for e in graph["edges"] if e["from"] == "draw:100" and e["label"] == "bound_ps"
        ]
        self.assertEqual(failed_edges, [])
        write_edges = [e for e in graph["edges"] if e["label"] == "writes"]
        self.assertEqual(len(write_edges), 2)

    def test_direct_write_skips_pixel_shader_node(self):
        mods = history()["modifications"][:1]
        mods[0]["directShaderWrite"] = True
        pipelines = {
            100: {
                "shaders": {"Pixel": {"resource": "ResourceId(7)"}},
                "descriptors": [],
                "indexBuffer": None,
            }
        }
        hist = history(mods=mods)
        hist["contextEventId"] = 100
        graph = build_graph({"x": 824, "y": 391}, hist, pipelines)
        kinds = {n["kind"] for n in graph["nodes"]}
        self.assertNotIn("shader", kinds)


if __name__ == "__main__":
    unittest.main()
