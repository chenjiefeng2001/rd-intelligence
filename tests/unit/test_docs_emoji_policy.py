"""Enforceable documentation typography policy.

Scope is deliberately narrow. A naive "no symbols" rule would delete the
box-drawing characters that render tables and the arrows that express flow, and
retro-fitting every historical document would mean editing frozen evidence
records. So the rule bans emoji and pictographs, permits structure and semantics,
and applies to the entry-point documents rather than to the archive.
"""
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
DOCS = REPO / "docs"

# Banned: emoji, pictographs, dingbats, variation selectors, regional
# indicators, and symbols that render as a glyph rather than as punctuation.
BANNED = [
    (0x1F000, 0x1FAFF, "emoji"),
    (0x1F1E6, 0x1F1FF, "regional indicator"),
    (0x2600, 0x26FF, "miscellaneous symbol / pictograph"),
    (0x2700, 0x27BF, "dingbat"),
    (0x2B00, 0x2BFF, "misc symbol and arrow"),
    (0xFE00, 0xFE0F, "variation selector"),
    (0x25A0, 0x25FF, "geometric shape"),
    (0x2E80, 0x2EFF, "CJK radicals supplement"),
]

# Permitted, with the reason, so the boundary is reviewable rather than implied.
PERMITTED = [
    (0x2500, 0x257F, "box drawing: renders table structure"),
    (0x2190, 0x21FF, "arrows: express control flow and ordering"),
    (0x00B0, 0x00FF, "latin-1 punctuation and symbols"),
    (0x4E00, 0x9FFF, "CJK ideograph: the documents are bilingual"),
]

# Entry points a reader meets first. The archive under docs/ is out of scope
# because much of it is a frozen evidence record.
IN_SCOPE = [
    REPO / "README.md",
    DOCS / "README.md",
    DOCS / "API-REFERENCE.md",
]


def scan(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    bad = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        for ch in line:
            o = ord(ch)
            for lo, hi, label in BANNED:
                if lo <= o <= hi:
                    bad.setdefault((lineno, o, label), 0)
                    bad[(lineno, o, label)] += 1
                    break
    return bad


def name_of(ch):
    import unicodedata
    try:
        return unicodedata.name(ch)
    except ValueError:
        return "<unnamed>"


class TestNoEmojiInEntryPointDocs(unittest.TestCase):
    def test_entry_point_documents_carry_no_emoji(self):
        for path in IN_SCOPE:
            if not path.exists():
                continue
            bad = scan(path)
            with self.subTest(doc=path.name):
                self.assertEqual(
                    bad, {},
                    "%s contains emoji: %s"
                    % (path.name,
                       ", ".join("L%d U+%04X %s" % (ln, o, lb)
                                 for (ln, o, lb) in sorted(bad))))

    def test_structure_and_semantics_stay_permitted(self):
        """The rule must not be so broad that it deletes tables and flow."""
        for path in IN_SCOPE:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for lo, hi, why in PERMITTED:
                found = [c for c in text if lo <= ord(c) <= hi]
                # Permitted means permitted, not required; only assert that a
                # file which uses them is not penalised, by construction.
                for c in found:
                    o = ord(c)
                    self.assertFalse(
                        any(b_lo <= o <= b_hi for b_lo, b_hi, _ in BANNED),
                        "%s: U+%04X is both permitted and banned (%s)"
                        % (path.name, o, why))

    def test_banned_and_permitted_ranges_do_not_overlap(self):
        for lo, hi, why in PERMITTED:
            for blo, bhi, label in BANNED:
                self.assertFalse(
                    lo <= bhi and blo <= hi,
                    "range overlap: permitted U+%04X-U+%04X (%s) vs banned "
                    "%s U+%04X-U+%04X" % (lo, hi, why, label, blo, bhi))


class TestPolicyIsEnforceable(unittest.TestCase):
    """A rule that cannot fail is not a rule."""

    def test_the_detector_finds_an_emoji_when_one_is_present(self):
        probe = REPO / "README.md"
        self.assertTrue(probe.exists())
        original = probe.read_text(encoding="utf-8")
        try:
            probe.write_text("# t\n\nwin \U0001F501 restart\n",
                             encoding="utf-8", newline="")
            bad = scan(probe)
            self.assertTrue(bad, "the detector did not see an emoji it was given")
            self.assertTrue(any(lb == "emoji" for _, _, lb in bad))
        finally:
            probe.write_text(original, encoding="utf-8", newline="")

    def test_the_policy_states_its_scope_and_rationale(self):
        text = (REPO / "tests" / "unit" / "test_docs_emoji_policy.py").read_text(
            encoding="utf-8")
        self.assertIn("box drawing", text)
        self.assertIn("frozen evidence", text)
        self.assertIn("IN_SCOPE", text)


if __name__ == "__main__":
    unittest.main()