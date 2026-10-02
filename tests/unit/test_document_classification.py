"""Document classification controls. Schema v1, 4 sample documents.

These check that a document declares how it is meant to be treated, not that
its contents are correct. Deciding whether a stale sentence is a defect or a
record is impossible without the declaration, so the declaration is what gets
checked.

Scope is deliberately narrow -- see
docs/DOCUMENT-CLASSIFICATION-CONTRACT.md §6. Not done here, by ruling:
numeric synchronisation, tense checking, rewrite suggestions, and any new gate.
This module lives inside the existing `unit` gate and changes no gate count,
exit mapping or readiness combination.

Note that this module must never read repository state. That is what makes
"a point_in_time document is not compared to HEAD" a structural property
rather than a promise: there is no HEAD here to compare against. The last
control enforces that.
"""

import ast
import os
import re
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

#: Documents marked in the first batch. A control asserts each is still
#: classified, so none can be quietly unmarked.
SAMPLES = {
    "docs/CI-ORCHESTRATION-CONTRACT.md": ("contract", "mixed"),
    "docs/CURRENT-EVIDENCE-FREEZE.md": ("evidence_record", "point_in_time"),
    "docs/AUDIT-2026-10-02-B.md": ("audit_record", "point_in_time"),
    "docs/CAPTURE-CORPUS-CONTRACT.md": ("contract", "living"),
}

ROLES = ("contract", "evidence_record", "audit_record", "historical_note")
POLICIES = ("living", "point_in_time", "mixed")

FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def _parse_front_matter(text):
    """Minimal front matter reader. No yaml dependency, by design.

    Handles `key: scalar`, `key:` followed by `  - item` lines, and `key: >-`
    folded notes. A note's content is kept as the marker only; no control
    inspects prose.
    """
    match = FRONT_MATTER.match(text)
    if not match:
        return None
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
            # scalar and every item is dropped without complaint, which is
            # how a mixed document ended up declaring no living anchors at
            # all while appearing to declare them.
            fields[key] = []
        else:
            fields[key] = value.strip('"')
    return fields


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
            fields = _parse_front_matter(text)
            if fields is not None:
                # Body only. Anchors are searched in the body because they
                # are declared in the front matter, and searching the whole
                # document lets an anchor satisfy itself: replacing a real
                # anchor with a nonsense one still passes, since the
                # nonsense string is then present in its own declaration.
                body = text[FRONT_MATTER.match(text).end():]
                found[rel] = (fields, body)
    return found


class TestDocumentClassificationSchema(unittest.TestCase):
    """Schema v1: a document must declare how it is meant to be treated."""

    @classmethod
    def setUpClass(cls):
        cls.docs = _documents()

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

    # 4b -- nothing here may compare a record to HEAD
    def test_this_control_suite_does_not_read_repository_state(self):
        """Makes control 4 structural instead of a promise.

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
                f"the classification controls must not read repository state; "
                f"found a call to {forbidden}. Comparing a point_in_time "
                "document to HEAD is exactly what this schema forbids, and "
                "it would be reintroduced here.")

    # supporting -- mixed documents must declare verifiable living anchors
    def test_mixed_documents_declare_verifiable_living_anchors(self):
        for rel, (fields, body) in sorted(self.docs.items()):
            if fields.get("freshness_policy") != "mixed":
                continue
            anchors = fields.get("document_living_anchors")
            self.assertTrue(
                isinstance(anchors, list) and anchors,
                f"{rel} is mixed but declares no document_living_anchors, so "
                "it does not say which of its sections must stay current. A "
                "mixed document with no declared living part is a living "
                "document that admits to being out of date.")
            for anchor in anchors:
                self.assertIn(
                    anchor, body,
                    f"{rel} declares living anchor {anchor!r}, which is not "
                    "present in its body. An anchor that does not resolve "
                    "marks nothing as living while appearing to. Note this "
                    "searches the body only -- searching the whole file "
                    "would let an anchor match its own declaration.")

    def test_the_four_samples_are_still_classified(self):
        for rel in SAMPLES:
            self.assertIn(
                rel, self.docs,
                f"{rel} was part of the first batch but is no longer "
                "classified; either re-mark it or record the withdrawal "
                "rather than letting coverage shrink unnoticed")


if __name__ == "__main__":
    unittest.main()
