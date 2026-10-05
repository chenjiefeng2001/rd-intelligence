"""Audit docs/README.md against the documents it indexes.

The index must stay correct without anyone having to remember to update it, and
it must never become a second classification authority. Both are enforced here
rather than trusted.
"""
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
DOCS = REPO / "docs"
INDEX = DOCS / "README.md"
FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
LINK = re.compile(r"\[`([^`]+)`\]\(([^)]+)\)")


def index_text() -> str:
    return INDEX.read_text(encoding="utf-8")


def linked_docs() -> set:
    out = set()
    for _, target in LINK.findall(index_text()):
        if target.startswith("http"):
            continue
        out.add((DOCS / target).as_posix().split("/docs/")[-1])
    return out


def on_disk() -> set:
    """Every document the index must cover. The index itself is excluded: it
    states that it does not list itself, and requiring it to would contradict
    that."""
    out = set()
    for p in DOCS.rglob("*"):
        if not p.is_file() or p.suffix not in (".md", ".json"):
            continue
        rel = p.relative_to(DOCS).as_posix()
        if rel == INDEX.relative_to(DOCS).as_posix():
            continue
        out.add(rel)
    return out


def front_matter(name: str) -> dict:
    t = (DOCS / name).read_text(encoding="utf-8", errors="replace")
    m = FRONT_MATTER.match(t)
    if not m:
        return {}
    body = m.group(1)
    out = {}
    for key in ("document_role", "freshness_policy", "as_of_commit"):
        v = re.search(rf"^{key}:\s*(\S+)", body, re.M)
        if v:
            out[key] = v.group(1)
    return out


class TestIndexLinksResolve(unittest.TestCase):
    def test_every_link_target_exists(self):
        for _label, target in LINK.findall(index_text()):
            if target.startswith("http"):
                continue
            with self.subTest(target=target):
                self.assertTrue((DOCS / target).is_file(),
                                f"index links to a missing file: {target}")

    def test_links_stay_inside_docs(self):
        for _, target in LINK.findall(index_text()):
            if target.startswith("http"):
                continue
            with self.subTest(target=target):
                self.assertFalse(target.startswith("/"),
                                 f"absolute link escapes docs/: {target}")
                self.assertNotIn("..", target)


class TestIndexCoverage(unittest.TestCase):
    def test_every_document_is_listed(self):
        missing = sorted(on_disk() - linked_docs())
        self.assertEqual(missing, [],
                         "documents exist but the index does not list them")

    def test_index_lists_nothing_that_is_absent(self):
        extra = sorted(linked_docs() - on_disk())
        self.assertEqual(extra, [],
                         "index lists documents that do not exist")

    def test_no_document_is_listed_twice(self):
        counts = {}
        for _, target in LINK.findall(index_text()):
            if not target.startswith("http"):
                counts[target] = counts.get(target, 0) + 1
        dupes = sorted(t for t, n in counts.items() if n > 1)
        self.assertEqual(dupes, [],
                         f"index links a document more than once: {dupes}")


class TestIndexIsNotASecondTaxonomy(unittest.TestCase):
    """The classification contract is the only authority. The index may copy a
    declared value; it may not invent one."""

    def test_declared_roles_in_the_index_match_front_matter(self):
        text = index_text()
        for name in sorted(linked_docs()):
            fm = front_matter(name)
            if not fm.get("document_role"):
                continue
            with self.subTest(doc=name):
                row = [ln for ln in text.splitlines()
                       if (f"({name})") in ln and "`" in ln]
                self.assertTrue(row, f"{name} is classified but not indexed")
                cell = " ".join(row)
                self.assertIn("`{}`".format(fm["document_role"]), cell,
                              f"{name}: index role disagrees with front matter")
                self.assertIn("`{}`".format(fm["freshness_policy"]), cell,
                              f"{name}: index freshness disagrees with front matter")

    def test_unclassified_documents_are_not_given_a_role(self):
        text = index_text()
        roles = {"contract", "evidence_record", "audit_record", "historical_note"}
        for name in sorted(linked_docs()):
            if front_matter(name).get("document_role"):
                continue
            for line in text.splitlines():
                if (f"({name})") not in line:
                    continue
                for role in roles:
                    self.assertNotIn(f"`{role}`", line,
                                     f"{name} has no front matter but the index "
                                     f"assigns role {role}")

    def test_index_states_the_classified_and_unclassified_counts(self):
        classified = sum(1 for n in on_disk()
                         if front_matter(n).get("document_role"))
        text = index_text()
        unclassified = len(on_disk()) - classified
        with self.subTest(classified=classified, unclassified=unclassified):
            self.assertIn(f"**{classified} are machine-classified**", text)
            self.assertIn(f"**{unclassified} are not classified**", text)


class TestIndexClaimsNoAuthority(unittest.TestCase):
    def test_index_points_at_the_contract_as_the_authority(self):
        # Checked in the preamble, not anywhere in the file: the contract is also
        # listed in the Contracts table, so a whole-file search would pass even
        # if the index stopped declaring who the authority is.
        preamble = index_text().split("\n## ", 1)[0]
        self.assertIn("DOCUMENT-CLASSIFICATION-CONTRACT.md", preamble,
                      "the index no longer names the classification contract "
                      "as its authority in its preamble")

    def test_index_states_the_authority_precedes_the_grouped_tables(self):
        preamble = index_text().split("\n## ", 1)[0]
        self.assertNotIn("| [`", preamble,
                         "the authority statement must be prose, not a table row")

    def test_index_declares_its_topic_grouping_is_not_schema(self):
        text = index_text()
        self.assertIn("not schema", text)
        self.assertIn("second taxonomy", text)

    def test_index_names_the_test_that_enforces_it(self):
        self.assertIn("test_docs_index.py", index_text())


if __name__ == "__main__":
    unittest.main()
