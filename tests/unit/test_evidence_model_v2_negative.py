"""Negative and mutation controls for the additive Evidence Model v2.

These are deliberately about the doors that stay shut: an evidence record
must not quietly change identity, a qualified reference must not survive a
revision mismatch, and a partially observed result must not be reported as
complete. Positive behavior lives in test_evidence.py.
"""

import unittest

from rdebug.errors import QueryError
from rdebug.evidence import make, record, ref, require_observed, validate


class TestIdentityIsImmutable(unittest.TestCase):
    def test_all_v2_fields_are_outside_the_identity(self):
        base = make(event_id=7, operation="writes")
        full = make(
            event_id=7,
            operation="writes",
            status="inferred",
            query_id="q1",
            revision="r1",
            source_ref={"kind": "replay"},
            observation={"v": 1},
            inference={"why": "x"},
            data={"payload": 1},
        )
        self.assertEqual(base["id"], full["id"])

    def test_data_mutation_does_not_invalidate_a_reference(self):
        ev = make(event_id=8, data={"n": 1})
        before = ref(ev)
        ev["data"]["n"] = 2
        self.assertEqual(ref(ev), before)


class TestRevisionBoundary(unittest.TestCase):
    def test_qualified_reference_requires_a_revision(self):
        ev = make(event_id=9, status="observed")
        with self.assertRaises(QueryError):
            ref(ev, qualified=True)

    def test_tampered_qualified_id_is_rejected_in_strict_validation(self):
        ev = make(event_id=10, revision="r1", status="observed",
                  observation={"v": 1})
        ev["qualifiedId"] = "0" * 16
        with self.assertRaises(ValueError):
            validate(ev, strict=True)

    def test_two_revisions_are_not_interchangeable(self):
        a = make(event_id=11, revision="r1", status="observed")
        b = make(event_id=11, revision="r2", status="observed")
        self.assertEqual(a["id"], b["id"])
        self.assertNotEqual(ref(a, qualified=True), ref(b, qualified=True))


class TestPartialObservationIsNotComplete(unittest.TestCase):
    def test_unknown_record_has_no_observation(self):
        ev = record(event_id=12, inference={"guess": 1})
        self.assertEqual(ev["status"], "unknown")
        self.assertNotIn("observation", ev)

    def test_one_unknown_item_aborts_a_conclusion(self):
        with self.assertRaises(QueryError):
            require_observed([
                record(observation={"v": 1}, event_id=13),
                record(event_id=14),
            ])

    def test_unknown_status_string_is_not_a_synonym_for_absence(self):
        ev = record(status="unknown", observation=None, event_id=15)
        self.assertEqual(ev["status"], "unknown")
        with self.assertRaises(QueryError):
            require_observed([ev])


if __name__ == "__main__":
    unittest.main()
