import unittest

from rdebug.evidence import make, record, ref, require_observed, validate


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


class TestEvidenceModelV2(unittest.TestCase):
    """Additive protocol: old records keep their exact shape and identity."""

    def test_v2_metadata_does_not_change_the_stable_id(self):
        legacy = make(event_id=11, operation="writes")
        v2 = make(event_id=11, operation="writes", status="observed",
                  query_id="q-1", revision="r1", source_ref={"kind": "replay"})
        self.assertEqual(v2["id"], legacy["id"])
        for key in ("status", "queryId", "revision", "qualifiedId", "sourceRef"):
            self.assertIn(key, v2)

    def test_qualified_id_changes_with_revision_but_id_does_not(self):
        a = make(event_id=12, revision="r1")
        b = make(event_id=12, revision="r2")
        self.assertEqual(a["id"], b["id"])
        self.assertNotEqual(a["qualifiedId"], b["qualifiedId"])

    def test_default_ref_shape_is_byte_identical_to_v1(self):
        v2 = make(event_id=13, revision="r1", status="observed")
        self.assertEqual(ref(v2), {"id": v2["id"]})
        self.assertEqual(
            ref(v2, qualified=True),
            {"id": v2["id"], "revision": "r1", "qualifiedId": v2["qualifiedId"]},
        )

    def test_strict_validate_requires_a_grounded_record(self):
        validate(make(event_id=14))
        with self.assertRaises(ValueError):
            validate(make(event_id=14, status="observed"), strict=True)
        grounded = record(observation={"value": 1}, event_id=14, revision="r1")
        self.assertTrue(validate(grounded, strict=True))

    def test_record_derives_an_honest_status(self):
        self.assertEqual(
            record(event_id=15)["status"], "unknown")
        self.assertEqual(
            record(observation={"v": 1}, event_id=15)["status"], "observed")
        self.assertEqual(
            record(observation={"v": 1}, inference={"cause": "x"},
                   event_id=15)["status"], "inferred")

    def test_inference_without_observation_is_not_upgraded(self):
        ev = record(inference={"cause": "guess"}, event_id=16)
        self.assertEqual(ev["status"], "unknown")
        self.assertNotIn("observation", ev)

    def test_unknown_evidence_is_rejected_by_the_guard(self):
        from rdebug.errors import QueryError

        with self.assertRaises(QueryError):
            require_observed([record(event_id=17)])
        self.assertTrue(require_observed([make(event_id=18)]))
        self.assertTrue(require_observed([]))


if __name__ == "__main__":
    unittest.main()
