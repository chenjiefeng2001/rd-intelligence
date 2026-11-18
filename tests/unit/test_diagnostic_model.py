"""D1: the diagnostic report model must be complete and namespace-safe."""

import unittest

from rdebug.diagnostics.report_model import (
    FINDING_STATUSES,
    PRIORITIES,
    REPORT_SCHEMA,
    SECTION_STATUSES,
    SECTIONS,
    SEVERITIES,
    empty_report,
    set_section,
    validate_report,
)


class TestReportSkeleton(unittest.TestCase):
    def test_all_twelve_sections_are_always_present(self):
        report = empty_report(capture="cap.rdc", capture_sha256="a" * 64,
                              analysis_revision="r1")
        self.assertEqual(len(SECTIONS), 12)
        self.assertEqual(set(report["sections"]), set(SECTIONS))
        self.assertTrue(validate_report(report))

    def test_missing_data_is_never_silently_omitted(self):
        report = empty_report()
        for section in report["sections"].values():
            self.assertEqual(section["status"], "insufficient_evidence")
            self.assertTrue(section["reason"])
            self.assertEqual(section["content"], {})

    def test_namespaces_are_distinct_from_evidence_status(self):
        # observed/inferred/unknown belong to evidence; report sections use
        # their own availability vocabulary and findings have their own.
        self.assertNotEqual(set(SECTION_STATUSES), {"observed", "inferred", "unknown"})
        self.assertNotIn("observed", FINDING_STATUSES)
        self.assertNotIn("inferred", SEVERITIES)
        self.assertNotIn("P2", SECTION_STATUSES)
        self.assertIn("P2", PRIORITIES)

    def test_set_section_and_validation(self):
        report = empty_report()
        set_section(report, "findings", "present", None, {"findingCount": 0})
        self.assertTrue(validate_report(report))
        self.assertEqual(report["sections"]["findings"]["content"]["findingCount"], 0)

    def test_invalid_status_and_fabricated_presence_are_rejected(self):
        report = empty_report()
        with self.assertRaises(ValueError):
            set_section(report, "findings", "observed", None, {})
        with self.assertRaises(ValueError):
            set_section(report, "findings", "present", None)
        with self.assertRaises(ValueError):
            set_section(report, "unknown_section", "present", None, {})
        report["sections"].pop("limitations")
        with self.assertRaises(ValueError):
            validate_report(report)
        report["schema"] = "other/1"
        with self.assertRaises(ValueError):
            validate_report(report)

    def test_schema_is_independent_of_ci_report(self):
        self.assertEqual(REPORT_SCHEMA, "rdebug-diagnostic-report/1")
        self.assertNotIn("ci", REPORT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
