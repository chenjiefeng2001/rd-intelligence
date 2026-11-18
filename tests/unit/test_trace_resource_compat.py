"""R4.2: the v2 extension must stay invisible to v1 consumers.

A snapshot fixes the exact legacy output shape, and stable-ID controls fix
the identity algorithm that R1 promised not to change. These are deliberately
brittle: a helpful-looking rename here is an API break.
"""

import unittest

from rdebug.analysis.resource_flow import trace_resource
from rdebug.evidence import make, validate

ROWS = [
    {"eventId": 10, "usage": "Clear", "usageRaw": 1},
    {"eventId": 20, "usage": "PS_Resource", "usageRaw": 2},
    {"eventId": 30, "usage": "ColorTarget", "usageRaw": 3},
]


class FakeSession:
    path = "cap.rdc"

    def usage(self, rid):
        return ROWS

    def root_actions(self):
        return []

    def last_draw_event_id(self):
        return 30


LEGACY_KEYS = ("resource", "contextEventId", "writers", "readers", "other",
               "summary", "evidence")


class TestLegacySnapshot(unittest.TestCase):
    def test_legacy_subtree_is_byte_stable(self):
        result = trace_resource(FakeSession(), "ResourceId::91")
        legacy = {key: result[key] for key in LEGACY_KEYS}
        self.assertEqual(
            legacy,
            {
                "resource": {"id": "ResourceId::91", "name": ""},
                "contextEventId": 30,
                "writers": [
                    {
                        "eventId": 10, "usage": "Clear", "kind": "write",
                        "actionName": "",
                        "evidence": [{
                            "capture": "cap.rdc", "eventId": 10,
                            "resourceId": "ResourceId::91",
                            "operation": "usage:Clear",
                            "source": "ReplayController.GetUsage",
                            "id": "15e30d3412cb",
                        }],
                    },
                    {
                        "eventId": 30, "usage": "ColorTarget", "kind": "write",
                        "actionName": "",
                        "evidence": [{
                            "capture": "cap.rdc", "eventId": 30,
                            "resourceId": "ResourceId::91",
                            "operation": "usage:ColorTarget",
                            "source": "ReplayController.GetUsage",
                            "id": "6d47a98ea34b",
                        }],
                    },
                ],
                "readers": [
                    {
                        "eventId": 20, "usage": "PS_Resource", "kind": "read",
                        "actionName": "",
                        "evidence": [{
                            "capture": "cap.rdc", "eventId": 20,
                            "resourceId": "ResourceId::91",
                            "operation": "usage:PS_Resource",
                            "source": "ReplayController.GetUsage",
                            "id": "399e63a403a9",
                        }],
                    },
                ],
                "other": [],
                "summary": {
                    "usageCount": 3, "writerCount": 2, "readerCount": 1,
                    "otherCount": 0, "firstWriterEventId": 10,
                    "lastWriterEventId": 30, "lastReaderEventId": 20,
                    "unknownCount": 0, "versionCount": 2,
                },
                "evidence": [{
                    "capture": "cap.rdc", "eventId": 30,
                    "resourceId": "ResourceId::91",
                    "operation": "trace_resource",
                    "source": "rdebug.analysis.resource_flow",
                    "id": "d752ed1ddcc6",
                    "data": {"usageCount": 3},
                }],
            },
        )

    def test_no_undeclared_legacy_field_was_added(self):
        result = trace_resource(FakeSession(), "ResourceId::91")
        self.assertEqual(result["summary"].get("firstReaderEventId", "absent"),
                         "absent")
        self.assertNotIn("contextEventId", result["summary"])
        self.assertEqual(result["other"], [])


class TestStableIdentityInvariants(unittest.TestCase):
    def test_known_ids_are_unchanged(self):
        self.assertEqual(make(event_id=11, operation="writes")["id"],
                         "283c7ed34ccd")
        self.assertEqual(make(capture="cap.rdc", event_id=10,
                              resource_id="ResourceId::91",
                              operation="usage:Clear",
                              source="ReplayController.GetUsage")["id"],
                         "15e30d3412cb")

    def test_v2_fields_do_not_alter_a_known_id(self):
        ev = make(event_id=11, operation="writes", status="inferred",
                  revision="r1", query_id="q1", observation={"v": 1})
        self.assertEqual(ev["id"], "283c7ed34ccd")
        self.assertTrue(validate(ev))  # default path stays permissive

    def test_strict_mode_is_opt_in(self):
        legacy = make(event_id=12, operation="writes")
        self.assertTrue(validate(legacy))
        with self.assertRaises(ValueError):
            validate(legacy, strict=True)


if __name__ == "__main__":
    unittest.main()
