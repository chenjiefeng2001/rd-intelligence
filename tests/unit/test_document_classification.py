"""Document classification controls. Schema v1.1.

These check that a document declares how it is meant to be treated, not that
its contents are correct. Deciding whether a stale sentence is a defect or a
record is impossible without the declaration, so the declaration is what gets
checked.

v1.1 exists because v1 had a hole that was not a control failure but an
expression failure. A mixed document could declare *that* it contained living
material, but not *which* material, so content sat outside every anchor and
outside any default: unclassified, unchecked, and invisible. The CI contract's
preamble -- three stale current-state claims -- lived exactly there.

The fix is total coverage. A mixed document must declare

  document_living_sections  sections that must stay current, each of which
                            must resolve to a real heading
  document_living_preamble  whether content before the first heading is living
  document_default_policy   what every undeclared section is

After that, every byte of the document is either explicitly living or
explicitly defaulted historical. Nothing is in limbo.

By explicit ruling, this does NOT attempt to judge the text of undeclared
sections. "Phase 2 did not implement Gate 3" may be a true record;
"Gate 3 is not implemented" may be a false claim; no keyword test separates
them, so no such test is attempted.

Scope -- see docs/DOCUMENT-CLASSIFICATION-CONTRACT.md §6. Not done here, by
ruling: numeric synchronisation, tense checking, rewrite suggestions, any new
gate. This module lives inside the existing `unit` gate and changes no gate
count, exit mapping or readiness combination.

This module must never read repository state. That is what makes "a
point_in_time document is not compared to HEAD" structural rather than a
promise: there is no HEAD here to compare against.
"""

import ast
import os
import re
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

#: Documents marked in the first batch, plus the S1 expansion. A control
#: asserts each is still classified, so none can be quietly unmarked.
#: AUDIT-* and validation/phase* are deliberately absent: they are point-in-time
#: evidence and are not being asked to look like current contracts. Absence is
#: not an error -- an unmarked document is simply outside this schema.
SAMPLES = {
    "docs/CI-ORCHESTRATION-CONTRACT.md": ("contract", "mixed"),
    "docs/CURRENT-EVIDENCE-FREEZE.md": ("evidence_record", "point_in_time"),
    "docs/AUDIT-2026-10-02-B.md": ("audit_record", "point_in_time"),
    "docs/CAPTURE-CORPUS-CONTRACT.md": ("contract", "living"),
    "docs/DOCUMENT-CLASSIFICATION-CONTRACT.md": ("contract", "mixed"),
}

ROLES = ("contract", "evidence_record", "audit_record", "historical_note")
POLICIES = ("living", "point_in_time", "mixed")
SECTION_POLICIES = ("historical", "evidence")

#: The complete set of keys this schema defines. Anything else is a typo, and
#: a typo is worse than nothing: the author believes they declared something,
#: no control objects, and the region stays unclassified. Found by mutation --
#: misspelling document_living_sections as living_sections left every control
#: passing, because an unknown key is simply not read.
SCHEMA_KEYS = frozenset((
    "document_role",
    "freshness_policy",
    "as_of_commit",
    "document_living_preamble",
    "document_default_policy",
    "document_living_sections",
))

#: Front matter is only the region between the first two '---' at the top of
#: the file. A later '---' is a horizontal rule; treating it as a delimiter
#: swallows the rest of the document.
FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n",
                          re.DOTALL)
HEADING = re.compile(r"^(#{1,6})[ \t]+(\S.*?)[ \t]*$")
FENCE = re.compile(r"^[ \t]*(?:```|~~~)")


def _scalar(value):
    """YAML-ish scalar coercion.

    Booleans matter here: document_living_preamble is asserted with
    assertIsInstance(..., bool), so an unquoted 	rue that stayed the string
    "true" would fail its own control. Caught by running it.
    """
    value = value.strip().strip('"').strip("'")
    if value in ("true", "True"):
        return True
    if value in ("false", "False"):
        return False
    return value


def _parse_front_matter(text):
    """Minimal front matter reader. No yaml dependency, by design.

    Handles `key: scalar`, `key:` followed by `  - item` lines, and `key: >-`
    folded notes. A note's content is kept as the marker only; no control
    inspects prose.
    """
    match = FRONT_MATTER.match(text)
    if not match:
        return None, text
    fields = {}
    key = None
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t", "-")) and key is not None:
            item = line.strip()
            if item.startswith("- "):
                fields.setdefault(key, [])
                if isinstance(fields[key], list):
                    fields[key].append(item[2:].strip().strip('"'))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value in (">-", ">", "|", "|-"):
            fields[key] = ">-"
        elif value == "":
            # May be a list header or an empty scalar. Starts as a list so
            # that following "- " items append to it. Getting this wrong is
            # not cosmetic: with a scalar pre-set, setdefault returns that
            # scalar and every item is dropped without complaint.
            fields[key] = []
        else:
            fields[key] = _scalar(value)
    return fields, text[match.end():]


def _headings(body):
    """Return [(level, text, first_body_line_index)] for real headings.

    Lines inside fenced code blocks are skipped: a '#' there is a shell
    comment or a diff marker, not a heading. A parser that counted them would
    let a fenced pseudo-heading satisfy a living-section declaration.
    """
    found = []
    fence = None
    for index, line in enumerate(body.splitlines()):
        stripped = line.strip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            continue
        if FENCE.match(line):
            fence = stripped[:3]
            continue
        match = HEADING.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2), index))
    return found


def _section_body(body, heading_index):
    """Lines of the section starting at heading_index, excluding the heading.

    Runs to the next heading of the same or higher level, i.e. to where the
    section actually ends rather than to a fixed line count.
    """
    lines = body.splitlines()
    level = len(HEADING.match(lines[heading_index]).group(1))
    end = len(lines)
    for index in range(heading_index + 1, len(lines)):
        match = HEADING.match(lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return lines[heading_index + 1:end]


def _resolve(fields, body):
    """Assign a policy to every heading: living, historical or evidence.

    Living is inherited downward. A subsection is inside its parent's body, so
    inheriting is document structure, not a judgement about wording -- which
    is the kind of inference this schema refuses to make. Without inheritance
    the model got this exactly backwards: declaring '## 2.' living left
    '### 2.2 current actual result' defaulted historical, so the most
    normative content in the document fell outside living treatment.

    An explicit declaration may promote a subsection inside a historical
    parent, which is the other half of the same rule and is needed here: the
    current-state block sits under a phase-history section.

    Returns ({heading_index: policy}, {heading_index: ancestor_policy}).
    """
    declared = set(fields.get("document_living_sections") or [])
    default = fields["document_default_policy"]
    policies = {}
    inherited = {}
    stack = []
    for level, text, index in _headings(body):
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        if text in declared:
            policy = "living"
        elif parent is not None:
            policy = parent
        else:
            policy = default
        policies[index] = policy
        inherited[index] = parent
        if level > 1:
            stack.append((level, policy))
    return policies, inherited


def _documents():
    """Every markdown file in the repository that declares a classification.

    Documents without front matter are not required to declare one: only 4
    of 41 are in scope, and requiring the rest would produce 37 failures that
    say nothing about correctness.
    """
    found = {}
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            fields, body = _parse_front_matter(text)
            if fields is not None:
                found[rel] = (fields, body)
    return found


class TestDocumentClassificationSchema(unittest.TestCase):
    """Schema v1.1: role, freshness policy, and total coverage of a mixed doc."""

    @classmethod
    def setUpClass(cls):
        cls.docs = _documents()

    def _mixed(self):
        for rel, (fields, _) in sorted(self.docs.items()):
            if fields.get("freshness_policy") == "mixed":
                yield rel, fields

    # 0 -- no silent typos in the declaration itself
    def test_front_matter_declares_no_unknown_keys(self):
        for rel, (fields, _) in sorted(self.docs.items()):
            unknown = sorted(key for key in fields
                             if key not in SCHEMA_KEYS
                             and not key.endswith("_note"))
            self.assertEqual(
                unknown, [],
                f"{rel} declares unknown key(s) {unknown}. A misspelled key is "
                "read by no control, so the declaration looks present while "
                "granting nothing. Known keys are "
                f"{sorted(SCHEMA_KEYS)}; a free-text explanation belongs in a "
                "key ending in _note.")

    # 1 -- role exists and is legal
    def test_document_role_is_declared_and_valid(self):
        for rel, (fields, _) in sorted(self.docs.items()):
            self.assertIn("document_role", fields,
                          f"{rel} is classified but declares no "
                          "document_role, so a reader cannot tell whether it "
                          "is a constraint or a record")
            self.assertIn(fields["document_role"], ROLES,
                          f"{rel} declares document_role "
                          f"{fields['document_role']!r}, which is not one of "
                          f"{ROLES}")

    # 2 -- freshness policy exists and is legal
    def test_freshness_policy_is_declared_and_valid(self):
        for rel, (fields, _) in sorted(self.docs.items()):
            self.assertIn("freshness_policy", fields,
                          f"{rel} is classified but declares no "
                          "freshness_policy, so nothing says whether it must "
                          "track the current state")
            self.assertIn(fields["freshness_policy"], POLICIES,
                          f"{rel} declares freshness_policy "
                          f"{fields['freshness_policy']!r}, which is not one "
                          f"of {POLICIES}")

    # 3 -- a living document may not present itself as a record
    def test_living_documents_carry_no_point_in_time_anchor(self):
        for rel, (fields, _) in sorted(self.docs.items()):
            if fields.get("freshness_policy") != "living":
                continue
            self.assertNotIn(
                "as_of_commit", fields,
                f"{rel} is living but declares as_of_commit. A document that "
                "must stay current cannot also claim to be a record of a "
                "moment; if it is a record, its policy is point_in_time.")

    # 4a -- a record must say which moment it records
    def test_point_in_time_documents_declare_their_anchor(self):
        for rel, (fields, _) in sorted(self.docs.items()):
            if fields.get("freshness_policy") != "point_in_time":
                continue
            self.assertIn(
                "as_of_commit", fields,
                f"{rel} is a point-in-time record with no as_of_commit, so "
                "'as of when?' has no answer and the record is not "
                "distinguishable from a claim about today")
            self.assertRegex(
                str(fields["as_of_commit"]), r"^[0-9a-f]{7,40}$",
                f"{rel} has an as_of_commit that is not a commit hash")

    # 4b -- point_in_time documents are never half living
    def test_point_in_time_documents_cannot_declare_living_sections(self):
        """A record with living regions should be declared mixed instead.

        Without this, a point_in_time document could quietly take on the
        obligations of a living one and the two treatments would apply at
        once, with nothing saying which governs.
        """
        for rel, (fields, _) in sorted(self.docs.items()):
            if fields.get("freshness_policy") != "point_in_time":
                continue
            self.assertFalse(
                fields.get("document_living_sections"),
                f"{rel} is point_in_time but declares living sections. A "
                "document that is both a record and living has no coherent "
                "treatment; declare it mixed and say which parts are which.")

    # 5 -- nothing may read repository state
    def test_this_control_suite_does_not_read_repository_state(self):
        """Makes "records are not compared to HEAD" structural.

        If this module never reads git, a point_in_time document cannot be
        compared to HEAD no matter what it contains. Verified by parsing this
        file rather than by asserting on strings, so a comment mentioning git
        does not fail the control.
        """
        with open(os.path.abspath(__file__), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called.add(func.attr)
        for forbidden in ("run", "Popen", "check_output", "check_call",
                          "rev_parse", "rev_list"):
            self.assertNotIn(
                forbidden, called,
                "the classification controls must not read repository state; "
                f"found a call to {forbidden}. Comparing a point_in_time "
                "document to HEAD is exactly what this schema forbids, and it "
                "would be reintroduced here.")

    # 6 -- the samples are still classified
    def test_the_classified_samples_are_still_classified(self):
        for rel in SAMPLES:
            self.assertIn(
                rel, self.docs,
                f"{rel} is a marked sample but is no longer "
                "classified; either re-mark it or record the withdrawal "
                "rather than letting coverage shrink unnoticed")

    # v1.1 -- total coverage. This is the control that closes the v1 hole.
    def test_mixed_documents_declare_total_coverage(self):
        """Every byte of a mixed document must have a declared treatment.

        v1 let content exist outside every anchor with no default, which is
        how the CI contract's preamble held three stale current-state claims
        that no control could see. Preamble and default are now mandatory.
        """
        for rel, fields in self._mixed():
            self.assertIn(
                "document_living_preamble", fields,
                f"{rel} is mixed but does not say whether the content before "
                "its first heading is living. That region is exactly where "
                "stale current-state claims hide, and leaving it unstated is "
                "the v1 hole this control exists to close.")
            self.assertIsInstance(
                fields["document_living_preamble"], bool,
                f"{rel} must state document_living_preamble as true or false, "
                f"not {fields['document_living_preamble']!r}")
            self.assertIn(
                "document_default_policy", fields,
                f"{rel} is mixed but does not declare a default policy for "
                "its undeclared sections, so those sections are neither "
                "maintained nor recorded as history -- they are simply "
                "unclassified.")
            self.assertIn(
                fields["document_default_policy"], SECTION_POLICIES,
                f"{rel} declares document_default_policy "
                f"{fields['document_default_policy']!r}, which is not one of "
                f"{SECTION_POLICIES}")

    # v1.1 -- anchors must be section boundaries, not fuzzy strings
    def test_living_sections_resolve_to_real_headings(self):
        for rel, fields in self._mixed():
            sections = fields.get("document_living_sections")
            self.assertTrue(
                isinstance(sections, list) and sections,
                f"{rel} is mixed but declares no document_living_sections, "
                "so it does not say which of its sections must stay current. "
                "A mixed document with no declared living part is a living "
                "document that admits to being out of date.")
            headings = {text: (level, index)
                        for level, text, index
                        in _headings(self.docs[rel][1])}
            for section in sections:
                self.assertIn(
                    section, headings,
                    f"{rel} declares living section {section!r}, which is not "
                    "a heading in the document. A living section must be a "
                    "section boundary; a vague locator such as a bare word "
                    "marks nothing while appearing to.")

    # v1.1 -- front matter must not swallow the document
    def test_front_matter_contains_no_heading(self):
        """Catches a malformed closing delimiter eating the body.

        Found the hard way: a front matter block written without a trailing
        newline produced '---# Title' on one line. The closing '---' was then
        not a delimiter, so the non-greedy front matter pattern ran on to the
        next horizontal rule and swallowed the title, the date, the
        authorization scope and the whole preamble into the metadata. Every
        control still passed, because a document with a large chunk of itself
        inside its front matter still parses.

        A heading inside front matter is always that bug and never intent.
        """
        for rel in sorted(self.docs):
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8",
                      errors="replace") as handle:
                text = handle.read()
            match = FRONT_MATTER.match(text)
            self.assertIsNotNone(
                match, f"{rel} was classified but its front matter block "
                "could not be located; the opening or closing delimiter is "
                "malformed")
            for line in match.group(1).splitlines():
                self.assertIsNone(
                    HEADING.match(line),
                    f"{rel} has the markdown heading {line.strip()[:50]!r} "
                    "inside its front matter. Front matter is metadata; a "
                    "heading there means the closing delimiter was malformed "
                    "and part of the document was swallowed as metadata.")

    # v1.1 -- structural hygiene of the declarations
    def test_living_sections_are_unambiguous_and_non_empty(self):
        for rel, fields in self._mixed():
            sections = fields["document_living_sections"]
            self.assertEqual(
                len(sections), len(set(sections)),
                f"{rel} declares a duplicate living section; a section listed "
                "twice has no single owner.")
            body = self.docs[rel][1]
            headings = {text: (level, index)
                        for level, text, index in _headings(body)}
            policies, inherited = _resolve(fields, body)
            for section in sections:
                level, index = headings[section]
                self.assertNotEqual(
                    inherited[index], "living",
                    f"{rel} declares {section!r} living, but it sits inside "
                    "another living section, which already covers it. Declare "
                    "the outermost one only. A declaration that adds nothing "
                    "is worse than none, because it reads as though that "
                    "region was considered and found to need no owner. "
                    "Promotion inside a historical parent is fine and is the "
                    "other half of inheritance.")
                content = [line for line in _section_body(body, index)
                           if line.strip() and not HEADING.match(line)]
                self.assertTrue(
                    content,
                    f"{rel} declares {section!r} living but the section has "
                    "no content. An empty section cannot be maintained, and "
                    "declaring one living only serves to look covered.")

    # v1.1 -- the property v1 lacked: nothing is unclassified
    def test_every_region_of_a_mixed_document_has_a_policy(self):
        """Total coverage, computed. Not a proxy for it.

        v1's hole was not that a control failed but that content could exist
        which no declaration and no default described. Asserting that the
        right fields are present is a proxy for that; resolving every region
        and checking none came back empty is the property itself.
        """
        for rel, fields in self._mixed():
            body = self.docs[rel][1]
            policies, _ = _resolve(fields, body)
            unclassified = [text for level, text, index in _headings(body)
                            if index not in policies]
            self.assertEqual(
                unclassified, [],
                f"{rel} has headings that resolve to no policy: "
                f"{unclassified}. Every region of a mixed document must be "
                "either declared living or covered by the default, otherwise "
                "it can hold stale current-state claims that no control sees.")
            first_section = next((index for level, _, index in _headings(body)
                              if level >= 2), None)
            preamble = body.splitlines()[:first_section]
            self.assertTrue(
                any(line.strip() for line in preamble),
                f"{rel} is mixed and was expected to have content before its "
                "first section; if the preamble is empty there is nothing for "
                "document_living_preamble to govern")
            resolved = ("living" if fields["document_living_preamble"]
                        else fields["document_default_policy"])
            self.assertTrue(
                resolved == "living" or resolved in SECTION_POLICIES,
                f"{rel} resolved its preamble to an unknown policy "
                f"{resolved!r}")


if __name__ == "__main__":
    unittest.main()
