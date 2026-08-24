import unittest

from rdebug.evidence import make, ref, validate


class TestEvidenceContract(unittest.TestCase):
    def test_make_with_all_fields(self):
        ev = make(
            capture="cap.rdc",
            event_id=1234,
            resource_id="ResourceId(91)",
            subresource={"mip": 0},
            location={"x": 824, "y": 391},
            operation="writes",
            source="ReplayController.PixelHistory",
        )
        validate(ev)
        self.assertEqual(ev["eventId"], 1234)
        self.assertEqual(ev["operation"], "writes")
        self.assertTrue(ev["id"])

    def test_stable_and_distinct_ids(self):
        a = make(event_id=1, operation="writes")
        b = make(event_id=1, operation="writes")
        c = make(event_id=2, operation="writes")
        self.assertEqual(a["id"], b["id"])
        self.assertNotEqual(a["id"], c["id"])

    def test_none_fields_omitted(self):
        ev = make(event_id=5)
        self.assertNotIn("capture", ev)
        self.assertNotIn("resourceId", ev)
        validate(ev)

    def test_data_payload_kept_out_of_identity(self):
        a = make(event_id=7, data={"primitives": [1]})
        b = make(event_id=7, data={"primitives": [1, 2]})
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(b["data"]["primitives"], [1, 2])

    def test_validate_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate(make())
        with self.assertRaises(TypeError):
            validate(["not", "a", "dict"])

    def test_ref(self):
        ev = make(event_id=9)
        self.assertEqual(ref(ev), {"id": ev["id"]})


if __name__ == "__main__":
    unittest.main()
