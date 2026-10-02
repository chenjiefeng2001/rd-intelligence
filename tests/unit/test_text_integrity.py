"""Text integrity: the bytes of the record must still be the bytes.

RETENTION, per docs/CONTROL-ADMISSION-CONTRACT.md §2. The property asserted is
that content has not been corrupted, which is a retention property and not a
flow one: nothing needs to travel from a producer to a consumer for a
character to have been mangled on the way in.

Why this exists. A U+FFFD replacement character entered a document twice during
this work, both times through the same path -- a PowerShell here-string piped
into Python and written back -- and both times the damage was invisible to
everything else:

  * Markdown rendered it without complaint;
  * every control passed, because none of them looked at the characters;
  * the pipeline passed, including the gate that owns this file's neighbours.

It was found by reading a line that looked wrong in a console, not by any
check. That is the definition of an unmonitored property. A defect that occurs
twice, is caused by a known non-random path, and is caught by chance will occur
a third time.

Scope: files git tracks, plus the cross-repository STATUS.md, which is part of
the evidence chain but lives outside this repository and therefore never
appears in `git ls-files`. Excluded on purpose: build artefacts, caches, and
the generated report, none of which are records.
"""

import ast
import os
import subprocess
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
EXTERNAL_STATUS = os.path.join(os.path.dirname(REPO_ROOT), "STATUS.md")

#: Only text formats a human reads as a record. Binary is skipped rather than
#: guessed at.
TEXT_SUFFIXES = (".md", ".json", ".py", ".toml", ".yml", ".yaml",
                 ".cfg", ".ini", ".txt")

#: The character a decode failure leaves behind, and the other silent one.
REPLACEMENT = "\ufffd"
NUL = "\x00"


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT,
                         capture_output=True, text=True, encoding="utf-8")
    for rel in out.stdout.splitlines():
        if rel.lower().endswith(TEXT_SUFFIXES):
            yield rel


def _external_files():
    if os.path.exists(EXTERNAL_STATUS):
        yield os.path.relpath(EXTERNAL_STATUS, os.path.dirname(REPO_ROOT))


class TestTextIntegrity(unittest.TestCase):

    def _scan(self):
        """Yield (label, line_number, column, kind, context) for each hit."""
        for rel in _tracked_text_files():
            path = os.path.join(REPO_ROOT, rel)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for number, line in enumerate(fh, 1):
                    for column, char in enumerate(line, 1):
                        if char == REPLACEMENT:
                            yield (rel, number, column, "U+FFFD",
                                   line.strip()[:70])
                        elif char == NUL:
                            yield (rel, number, column, "NUL",
                                   line.strip()[:70])
        for rel in _external_files():
            path = os.path.join(os.path.dirname(REPO_ROOT), rel)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for number, line in enumerate(fh, 1):
                    if REPLACEMENT in line:
                        yield (rel, number, line.index(REPLACEMENT) + 1,
                               "U+FFFD", line.strip()[:70])

    def test_the_scan_covers_something(self):
        """Otherwise the check below would pass by scanning nothing."""
        self.assertGreater(len(list(_tracked_text_files())), 40,
                           "git ls-files returned almost nothing; the "
                           "integrity scan would be vacuous")
        self.assertTrue(os.path.exists(EXTERNAL_STATUS),
                        "the cross-repository status report is part of the "
                        "evidence chain and must be scanned too")

    def test_no_record_contains_a_replacement_character(self):
        hits = [h for h in self._scan() if h[3] == "U+FFFD"]
        self.assertEqual(
            hits, [],
            "records contain U+FFFD, which means text was lost in decoding "
            "and the surrounding characters are already wrong:\n" +
            "\n".join(f"  {h[0]}:{h[1]}:{h[2]}  {h[3]}  |  {h[4]}"
                         for h in hits[:10]))

    def test_no_record_contains_a_nul(self):
        hits = [h for h in self._scan() if h[3] == "NUL"]
        self.assertEqual(
            hits, [],
            "records contain a NUL byte:\n" +
            "\n".join(f"  {h[0]}:{h[1]}:{h[2]}  {h[3]}" for h in hits[:10]))

    def test_the_root_cause_is_recorded_here(self):
        """The defect was caused by a known path, so the path must be named.

        Asserted against the module docstring extracted by AST, not against
        the file's text. Searching the whole file made this control
        self-satisfying -- the probe's own literal satisfied it, so deleting the
        cause from the docstring changed nothing and the check stayed green.
        That is the sixth time in this work that a control has been satisfied
        by the thing it inspects.
        """
        with open(os.path.abspath(__file__), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        docstring = ast.get_docstring(tree) or ""
        self.assertIn(
            "here-string", docstring,
            "this control's docstring must keep naming the write path that "
            "caused the corruption. Without the cause, the control documents a "
            "symptom and the route stays undocumented.")
        self.assertIn(
            "invisible", docstring,
            "the docstring must keep recording that the damage was invisible "
            "to every other check, which is the reason this control exists")


if __name__ == "__main__":
    unittest.main()
