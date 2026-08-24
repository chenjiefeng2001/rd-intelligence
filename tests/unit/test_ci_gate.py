import os
import tempfile
import unittest

from rdebug import ci
from rdebug.errors import CaptureOpenError

_TMP = tempfile.mkdtemp()
_DUMMY = os.path.join(_TMP, "cap.rdc")
with open(_DUMMY, "wb") as _f:
    _f.write(b"fake capture bytes")


class FakeAction:
    def __init__(self, eid, name):
        self.eventId = eid
        self.actionId = eid
        self.customName = name
        self.flags = 0
        self.numIndices = 3
        self.numInstances = 0
        self.children = []


def _mod(eid, passed=True, r=0.5):
    return {
        "eventId": eid, "primitiveID": 0, "fragIndex": 0, "passed": passed,
        "unboundPS": False, "directShaderWrite": False,
        "preMod": {"float": [0.0] * 4, "depth": -1.0, "stencil": -1},
        "shaderOut": {"float": [r, 0.5, 0.5, 1.0], "depth": -1.0, "stencil": -1},
        "postMod": {"float": [r, 0.5, 0.5, 1.0], "depth": -1.0, "stencil": -1},
    }


class FakeSession:
    path = _DUMMY

    def __init__(self, r=0.5):
        self.r = r

    def pixel_history(self, rid, x, y, mip=0, slice_=0, sample=0,
                      comp_type=None, context_eid=None):
        r = self.r if x >= 300 else 0.1
        passed = x >= 300
        return {
            "resource": "ResourceId::35", "contextEventId": 8, "x": x, "y": y,
            "mip": 0, "slice": 0, "sample": 0,
            "evidence": [{"id": f"ev_{x}_{y}", "eventId": 8,
                          "operation": "pixel_history"}],
            "modifications": [_mod(8, passed=passed, r=r)],
        }

    def pipeline(self, event_id=None):
        return {
            "outputTargets": [{"slot": 0, "resource": "ResourceId::35",
                               "firstMip": 0, "firstSlice": 0}],
            "depthTarget": None,
            "shaders": {"Pixel": {"resource": "ResourceId::49",
                                  "entryPoint": "main", "debuggable": True}},
            "descriptors": [{"stage": "Pixel", "type": "ReadOnlyResource",
                             "index": 0, "resource": "ResourceId::47",
                             "sampler": None}],
            "indexBuffer": None,
        }

    def root_actions(self):
        return [FakeAction(8, "Shade")]

    def action_rows(self):
        return [{"eventId": 8, "actionId": 8, "name": "Shade", "flags": 0,
                 "depth": 0, "parentEventId": None, "numIndices": 3,
                 "numInstances": 0, "childCount": 0, "isDraw": True,
                 "isClear": False, "isDispatch": False,
                 "mayModifyPixel": True, "fragmentCandidate": True}]

    def usage(self, rid):
        return [{"eventId": 2, "usage": "CopyDst", "usageRaw": 0}]

    def debug_pixel(self, x, y, **kwargs):
        raise CaptureOpenError("no debug in fake")

    def last_draw_event_id(self):
        return 8


SPEC = {
    "pixels": [[320, 240], [10, 10]],
    "pairs": [{"a": [320, 240], "b": [10, 10], "name": "shaded_vs_bg"}],
}


class TestCIGate(unittest.TestCase):
    def test_record_check_roundtrip_passes(self):
        s = FakeSession()
        baseline = ci.record(s, SPEC)
        report = ci.check(FakeSession(), baseline)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["failures"], [])
        self.assertGreater(report["passedChecks"], 0)

    def test_value_regression_detected_with_evidence(self):
        baseline = ci.record(FakeSession(), SPEC)
        report = ci.check(FakeSession(r=0.9), baseline)
        self.assertEqual(report["status"], "regression")
        kinds = [f["kind"] for f in report["failures"]]
        self.assertIn("pixel_value", kinds)
        failure = next(f for f in report["failures"] if f["kind"] == "pixel_value")
        self.assertEqual(failure["expected"][0], 0.5)
        self.assertEqual(failure["actual"][0], 0.9)
        self.assertTrue(failure["evidenceIds"])

    def test_tolerance_absorbs_small_drift(self):
        baseline = ci.record(FakeSession(), SPEC)
        report = ci.check(FakeSession(r=0.5 + 1e-9), baseline, tolerance=1e-6)
        self.assertEqual(report["status"], "pass")

    def test_pair_regression_detected(self):
        class UniformPair(FakeSession):
            def pixel_history(self, rid, x, y, mip=0, slice_=0, sample=0,
                              comp_type=None, context_eid=None):
                result = dict(FakeSession.pixel_history(self, rid, x, y))
                result["modifications"] = [_mod(8, passed=True, r=0.5)]
                return result

        baseline = ci.record(FakeSession(), SPEC)
        report = ci.check(UniformPair(), baseline)
        self.assertEqual(report["status"], "regression")
        pair_failures = [f for f in report["failures"]
                         if f["name"] == "shaded_vs_bg"]
        self.assertTrue(pair_failures)
        self.assertTrue(all(f["evidenceIds"] for f in pair_failures))

    def test_capture_hash_gate(self):
        baseline = ci.record(FakeSession(), SPEC)
        other_path = os.path.join(_TMP, "other.rdc")
        with open(other_path, "wb") as f:
            f.write(b"different bytes")

        class OtherFile(FakeSession):
            path = other_path

        report = ci.check(OtherFile(), baseline)
        self.assertEqual(report["status"], "regression")
        self.assertFalse(report["captureHashMatch"])
        self.assertEqual(report["failures"][0]["kind"], "capture_hash")

        report2 = ci.check(OtherFile(), baseline, ignore_capture_hash=True)
        self.assertEqual(report2["status"], "pass")
        self.assertFalse(report2["captureHashMatch"])


if __name__ == "__main__":
    unittest.main()
