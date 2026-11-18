"""C4: subresource resolution must stay honest when detail is absent."""

import unittest

from rdebug.analysis.subresource import (
    build_coverage,
    match_subresource,
    resolve_access_subresources,
)

RID = "ResourceId::47"


def row(**overrides):
    base = {
        "resource": RID, "firstMip": 0, "numMips": 1,
        "firstSlice": 0, "numSlices": 1,
        "byteOffset": 0, "byteSize": 0, "status": "observed",
    }
    base.update(overrides)
    return base


class TestSubresourceResolution(unittest.TestCase):
    def test_matching_resource_is_attached(self):
        accesses = [{"eventId": 11, "resourceId": RID, "status": "observed"}]
        out = resolve_access_subresources(accesses, {11: [row(), row(resource="ResourceId::9")]})
        self.assertEqual(out[0]["subresourceStatus"], "observed")
        self.assertEqual(len(out[0]["subresources"]), 1)

    def test_missing_event_is_explicit_unknown(self):
        accesses = [{"eventId": 12, "resourceId": RID, "status": "observed"}]
        out = resolve_access_subresources(accesses, {})
        self.assertEqual(out[0]["subresourceStatus"], "unknown")
        self.assertIn("no descriptor access", out[0]["subresourceReason"])

    def test_coverage_distinguishes_analyzed_unobserved_and_missing(self):
        accesses = [
            {"eventId": 11, "resourceId": RID, "status": "observed"},
            {"eventId": 12, "resourceId": RID, "status": "observed"},
            {"eventId": 13, "resourceId": RID, "status": "unknown"},
        ]
        resolved = resolve_access_subresources(
            accesses, {11: [row()]})
        cov = build_coverage(accesses, resolved)
        self.assertEqual(cov["analyzedEventCount"], 1)
        self.assertEqual(cov["unobservedEventCount"], 1)
        self.assertEqual(cov["missingInputEventCount"], 1)
        self.assertEqual(cov["status"], "partial")

    def test_empty_coverage_is_unknown(self):
        cov = build_coverage([], [])
        self.assertEqual(cov["status"], "unknown")

    def test_range_match_compares_real_fields(self):
        writer = {"subresources": [row()]}
        same = {"subresources": [row()]}
        other = {"subresources": [row(firstMip=1)]}
        self.assertTrue(match_subresource(writer, same)["sameSubresource"])
        self.assertFalse(match_subresource(writer, other)["sameSubresource"])

    def test_unknown_range_never_matches_positively(self):
        result = match_subresource({}, {"subresources": [row()]})
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("sameSubresource", result)

    def test_missing_range_field_is_unknown(self):
        incomplete = row()
        incomplete.pop("numSlices")
        result = match_subresource({"subresources": [incomplete]},
                                   {"subresources": [row()]})
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "range_fields_missing")


if __name__ == "__main__":
    unittest.main()
