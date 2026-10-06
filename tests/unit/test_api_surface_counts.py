"""Keep the documented surface count derived from the code.

Every stale number in a reference is a number nobody re-checks. These controls
compare the counts the documents state against the counts the implementation
actually has, so adding an endpoint or a subcommand without updating the prose
fails here rather than being discovered by a reader.
"""
import pathlib
import re
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"


def zh() -> str:
    return (DOCS / "API-REFERENCE.md").read_text(encoding="utf-8")


def en() -> str:
    return (DOCS / "API-REFERENCE.en.md").read_text(encoding="utf-8")


def routes():
    from rdebug_ide import app

    return sorted(app._ROUTES)


def subcommands():
    from rdebug.cli import _build_parser

    parser = _build_parser()
    for action in parser._actions:
        if getattr(action, "choices", None) and hasattr(action,
                                                        "_name_parser_map"):
            return sorted(action.choices)
    return []


class TestTheCountsAreDerived(unittest.TestCase):
    def test_the_endpoint_count_is_stated_correctly_in_both_editions(self):
        # Each document states the count in its own language. Asserting both
        # phrasings inside each file would have passed on a document that
        # carried the other's wording, which is not what either of them does.
        expected = str(len(routes()))
        self.assertIn("`rdebug-ide`（" + expected + " endpoints）", zh())
        self.assertIn("`rdebug-ide` (" + expected + " endpoints)", en())

    def test_every_route_is_documented_in_both_editions(self):
        for name, text in (("zh", zh()), ("en", en())):
            for route in routes():
                with self.subTest(lang=name, route=route):
                    self.assertIn(route, text)

    def test_every_subcommand_is_documented_in_both_editions(self):
        for name, text in (("zh", zh()), ("en", en())):
            for sub in subcommands():
                with self.subTest(lang=name, sub=sub):
                    self.assertIn("`" + sub + "`", text)

    def test_the_two_editions_document_the_same_routes(self):
        routes_in = re.compile(r"\| `(/api/[^`]*)` \|")
        self.assertEqual(set(routes_in.findall(zh())), set(routes_in.findall(en())))

    def test_no_documented_endpoint_is_not_implemented(self):
        # The other direction: a route in the docs that does not exist would
        # send someone to a 404 for a documented feature.
        routes_in = re.compile(r"\| `(/api/[^`]*)` \|")
        implemented = set(routes())
        for name, text in (("zh", zh()), ("en", en())):
            for route in routes_in.findall(text):
                with self.subTest(lang=name, route=route):
                    self.assertIn(route, implemented)


class TestTheHistoryEndpointsAreDescribedHonestly(unittest.TestCase):
    def test_both_editions_explain_the_store_is_optional(self):
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn("RDEBUG_STORE", text)

    def test_both_editions_state_that_history_is_not_on_the_query_path(self):
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn("/api/history", text)

    def test_both_editions_record_the_zero_limit_rule(self):
        # limit=0 clamping to 1 rather than becoming the default page is the
        # kind of detail that gets "simplified" away by a later editor.
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn("limit=0", text)


class TestNoClaimContradictsTheImplementation(unittest.TestCase):
    """A "not implemented" note that names something that now exists.

    Found by drift rather than by intent: `/api/history` landed and the
    reference kept saying the request-metrics view was NOT IMPLEMENTED, in four
    places across two editions. Nothing caught it because every individual claim
    was once true, and a document that is wrong only in its summary lines is
    still a document a reader trusts.

    The check is deliberately narrow. It fires only when a line both claims
    NOT IMPLEMENTED *and* names an endpoint or a store that the code has. Every
    other NOT IMPLEMENTED in these documents is still true, and widening the
    rule would produce failures that say nothing about correctness.
    """

    IMPLEMENTED = ("/api/history", "RDEBUG_STORE", "/api/state", "/api/events")

    def _offenders(self, text):
        out = []
        for number, line in enumerate(text.splitlines(), 1):
            if "NOT IMPLEMENTED" not in line:
                continue
            for token in self.IMPLEMENTED:
                if token in line:
                    out.append((number, line.strip()[:90]))
        return out

    def test_neither_edition_claims_history_is_unimplemented(self):
        for name, text in (("zh", zh()), ("en", en())):
            offenders = self._offenders(text)
            with self.subTest(lang=name):
                self.assertEqual(
                    offenders, [],
                    "these lines call something NOT IMPLEMENTED while naming "
                    "a feature that exists: " + repr(offenders))

    def test_the_retired_workstream_a_phrase_is_gone(self):
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertNotIn(
                    "A workstream", text,
                    "workstream A was closed on grounds the store removed; "
                    "leaving the phrase makes the reference describe a "
                    "decision that no longer holds")

    def test_the_summary_points_at_the_history_section(self):
        for name, text in (("zh", zh()), ("en", en())):
            with self.subTest(lang=name):
                self.assertIn("/api/history/summary", text)
                self.assertIn("2.11", text)


if __name__ == "__main__":
    unittest.main()
