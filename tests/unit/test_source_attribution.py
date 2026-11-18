"""D4: levels are verified precision, never guessed ambition."""

import json
import pathlib
import unittest

from rdebug.diagnostics.mapping_resolver import (
    attach_to_report,
    event_refs_from_analysis,
    resolve_attribution,
)
from rdebug.diagnostics.report_model import SECTIONS, empty_report, validate_report
from rdebug.diagnostics.source_attribution import (
    LEVELS,
    build_mapping,
    validate_mapping,
)

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
REAL = REPO / "docs/validation/positive-copy-sample-a-d3d11-2026-11-19.json"


def meta(**overrides):
    base = {
        "api_call": {"name": "CopyResource"},
        "api_evidence_refs": [{"id": "ev-api"}],
        "symbol_identity": {"verified": True, "guid_age": "matched"},
        "binary_identity": {"verified": True, "sha256": "a" * 64},
    }
    base.update(overrides)
    return base


class TestAttributionLevels(unittest.TestCase):
    def test_levels_are_ordered(self):
        self.assertEqual(LEVELS, ("S0", "S1", "S2", "S3", "S4"))

    def test_no_metadata_is_s0(self):
        m = build_mapping([{"id": "ev1"}])
        self.assertEqual(m["highestVerifiedLevel"], "S0")
        self.assertEqual(m["mappingStatus"], "not_established")
        self.assertIn("api_call_not_established", m["limitations"])
        self.assertTrue(validate_mapping(m))

    def test_api_call_with_evidence_reaches_s1(self):
        m = build_mapping([{"id": "ev1"}], api_call={"name": "CopyResource"},
                          evidence_refs=[{"id": "ev-api"}])
        self.assertEqual(m["highestVerifiedLevel"], "S1")

    def test_mismatched_symbol_blocks_s2(self):
        m = build_mapping([{"id": "ev1"}], api_call={"name": "CopyResource"},
                          evidence_refs=[{"id": "ev-api"}],
                          engine_callsite={"function": "UpdateTexture"},
                          symbol_identity={"verified": False, "guid_age": "mismatch"},
                          binary_identity={"verified": True})
        self.assertEqual(m["highestVerifiedLevel"], "S1")
        self.assertIn("application_symbols_not_available", m["limitations"])

    def test_path_mapping_alone_never_reaches_s3(self):
        m = build_mapping([{"id": "ev1"}], api_call={"name": "CopyResource"},
                          evidence_refs=[{"id": "ev-api"}],
                          engine_callsite={"function": "UpdateTexture"},
                          symbol_identity={"verified": True},
                          binary_identity={"verified": True},
                          source_location={"file": "D:\\build\\src\\renderer.cpp",
                                           "function": "Render"},
                          path_mapping={"from": "D:\\build", "to": "C:\\src"})
        self.assertEqual(m["highestVerifiedLevel"], "S2")
        self.assertIn("source_revision_not_verified", m["limitations"])

    def test_s4_requires_line_verified_and_build_match(self):
        common = dict(
            api_call={"name": "CopyResource"},
            evidence_refs=[{"id": "ev-api"}],
            engine_callsite={"function": "UpdateTexture"},
            symbol_identity={"verified": True},
            binary_identity={"verified": True},
            source_revision={"verified": True, "commit": "abc123"},
        )
        insufficient = build_mapping(
            [{"id": "ev1"}],
            source_location={"file": "renderer.cpp", "function": "Render",
                             "line": 123},
            **common)
        self.assertEqual(insufficient["highestVerifiedLevel"], "S3")
        self.assertIn("line_not_verified_against_build", insufficient["limitations"])
        full = build_mapping(
            [{"id": "ev1"}],
            source_location={"file": "renderer.cpp", "function": "Render",
                             "line": 123, "lineVerified": True,
                             "buildMatchesSourceRevision": True},
            **common)
        self.assertEqual(full["highestVerifiedLevel"], "S4")

    def test_multiple_candidates_keep_ambiguity(self):
        m = build_mapping([{"id": "ev1"}], candidates=["callsite-a", "callsite-b"])
        self.assertIn("multiple_candidate_callsites_kept_ambiguous",
                      m["limitations"])

    def test_false_level_claim_is_rejected(self):
        m = build_mapping([{"id": "ev1"}])
        m["highestVerifiedLevel"] = "S4"
        with self.assertRaises(ValueError):
            validate_mapping(m)


class TestResolverAndReportIntegration(unittest.TestCase):
    def test_real_sample_without_symbols_stays_s0(self):
        analysis = json.loads(REAL.read_text(encoding="utf-8"))
        self.assertTrue(event_refs_from_analysis(analysis))
        mapping = resolve_attribution(analysis)
        self.assertEqual(mapping["highestVerifiedLevel"], "S0")
        self.assertFalse(mapping["sourceLocation"])
        self.assertTrue(validate_mapping(mapping))

    def test_real_sample_with_api_metadata_reaches_s1(self):
        analysis = json.loads(REAL.read_text(encoding="utf-8"))
        mapping = resolve_attribution(analysis, meta())
        self.assertEqual(mapping["highestVerifiedLevel"], "S1")

    def test_report_keeps_twelve_sections_after_integration(self):
        report = empty_report()
        mapping = resolve_attribution(json.loads(REAL.read_text(encoding="utf-8")))
        attach_to_report(report, diagnoses=[{"conclusion": {"status": "not_established"}}],
                         mappings=[mapping])
        self.assertEqual(set(report["sections"]), set(SECTIONS))
        self.assertTrue(validate_report(report))
        self.assertEqual(report["sections"]["analysis_scope"]["content"]["highestLevel"],
                         "S0")


if __name__ == "__main__":
    unittest.main()
