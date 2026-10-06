"""Keep the Chinese and English API references in step.

Two language editions drift apart the moment nobody checks them. These controls
compare the factual skeleton of both: endpoints, parameters, status codes and
the evidence tags. Wording may differ; the claims may not.
"""
import pathlib
import re
import unittest

DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"
ZH = DOCS / "API-REFERENCE.md"
EN = DOCS / "API-REFERENCE.en.md"

STATUS = re.compile(r"\*\*(?:NOT_ESTABLISHED|NOT ESTABLISHED)\*\*")
TAGS = re.compile(r"\[(CODE|P9a|UNIT|NOT ESTABLISHED)\]")


def zh() -> str:
    return ZH.read_text(encoding="utf-8")


def en() -> str:
    return EN.read_text(encoding="utf-8")


class TestBothEditionsExist(unittest.TestCase):
    def test_both_files_exist_and_are_substantial(self):
        for p in (ZH, EN):
            with self.subTest(doc=p.name):
                self.assertTrue(p.is_file())
                self.assertGreater(len(p.read_text(encoding="utf-8")), 3000)

    def test_each_links_to_the_other(self):
        self.assertIn("API-REFERENCE.en.md", zh())
        self.assertIn("API-REFERENCE.md", en())

    def test_each_names_the_parity_audit(self):
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn("test_api_reference_parity.py", text)


class TestEndpointSetsAgree(unittest.TestCase):
    def test_same_endpoints(self):
        zh_ep = set(re.findall(r"/api/[a-z]+", zh()))
        en_ep = set(re.findall(r"/api/[a-z]+", en()))
        self.assertEqual(zh_ep, en_ep, "endpoint sets differ")

    def test_every_endpoint_appears_in_the_summary_table(self):
        for name, text in (("zh", zh()), ("en", en())):
            for ep in ("info", "trace", "diff", "resource", "explain", "ci", "stats"):
                with self.subTest(lang=name, endpoint=ep):
                    self.assertIn("/api/" + ep, text)


PARAM = re.compile(r"`(x|y|a|b|deep|eid|max_draws|id)`")


class TestParameterSetsAgree(unittest.TestCase):
    def test_the_same_parameter_symbols_appear(self):
        self.assertEqual(set(PARAM.findall(zh())), set(PARAM.findall(en())),
                         "documented parameter symbols differ")

    def test_deep_accepts_exactly_four_values(self):
        for name, text in (("zh", zh()), ("en", en())):
            for token in ("`1`", "`0`", "`true`", "`false`"):
                with self.subTest(lang=name, token=token):
                    self.assertIn(token, text)


class TestMcpAndCliAgree(unittest.TestCase):
    def test_four_tools_named_in_both(self):
        for tool in ("trace_pixel", "trace_resource", "debug_pixel", "diff_pixel"):
            with self.subTest(tool=tool):
                self.assertIn(tool, zh())
                self.assertIn(tool, en())

    def test_fifteen_cli_subcommands_named_in_both(self):
        for sub in ("trace-pixel", "diff-pixel", "debug-pixel", "trace-resource",
                    "pixel-history", "ci-record", "ci-check", "pipeline"):
            with self.subTest(sub=sub):
                self.assertIn(sub, zh())
                self.assertIn(sub, en())

    def test_both_state_the_same_number_of_subcommands(self):
        # Derived from the parser rather than written down here. A literal "15"
        # in this test and in both documents is three places to update when a
        # subcommand is added, and the day someone updates two of them the
        # documents quietly disagree with the CLI.
        from rdebug.cli import _build_parser

        parser = _build_parser()
        actions = [a for a in parser._actions
                   if getattr(a, "choices", None) and hasattr(a, "_name_parser_map")]
        names = sorted(actions[0].choices)
        self.assertGreaterEqual(len(names), 16)
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn(str(len(names)), text)
        # And every subcommand is actually documented.
        for name, text in (("zh", zh()), ("en", en())):
            for sub in names:
                with self.subTest(lang=name, subcommand=sub):
                    self.assertIn("`" + sub + "`", text)


class TestSemanticsAgree(unittest.TestCase):
    def test_both_carry_the_evidence_tags(self):
        for name, text in (("zh", zh()), ("en", en())):
            for tag in ("[CODE]", "[P9a]", "[UNIT]"):
                with self.subTest(lang=name, tag=tag):
                    self.assertIn(tag, text)

    def test_both_record_the_same_traps(self):
        traps = [
            "200",                      # status is not sufficient
            "summary",                   # contextEventId placement
            "1 byte",                   # truncation boundary
            "parse_qs",                 # empty deep
        ]
        for trap in traps:
            with self.subTest(trap=trap):
                self.assertIn(trap, zh())
                self.assertIn(trap, en())

    def test_both_declare_browser_propagation_not_established(self):
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn("NOT_ESTABLISHED", text)
                self.assertIn("NOT ESTABLISHED", text)

    def test_both_state_diff_pixel_has_no_context_eid(self):
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn("context_eid", text)
                self.assertIn("last_draw_event_id", text)

    def test_both_carry_the_sparse_event_warning(self):
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn("1..12", text)
                self.assertIn("[1, 2, 11, 12]", text)


class TestParityIsEnforceable(unittest.TestCase):
    def test_removing_an_endpoint_from_one_edition_is_caught(self):
        original = EN.read_text(encoding="utf-8")
        try:
            EN.write_text(original.replace("/api/stats", "/api/xx"),
                          encoding="utf-8", newline="")
            self.assertNotEqual(set(re.findall(r"/api/[a-z]+", zh())),
                                set(re.findall(r"/api/[a-z]+",
                                               EN.read_text(encoding="utf-8"))))
        finally:
            EN.write_text(original, encoding="utf-8", newline="")


if __name__ == "__main__":
    unittest.main()
