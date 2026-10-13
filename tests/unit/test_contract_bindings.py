"""Every contract must name the controls that enforce it.

Nine contracts had no test reference anywhere in the suite. Their rules were
partly implemented -- A1's F1 through F4 run under sixty-eight controls -- but
nothing connected the prose to the code. That is the quiet failure this
project keeps paying for in one form or another: the document moves and the
tests stay green, so nobody is told.

The binding is at symbol level rather than module level on purpose. A module
name survives a rename, so a module-level binding would look valid while
pointing at nothing. Naming a class or function means renaming or deleting a
control breaks this, which is the moment someone should be told.
"""

import ast
import json
import os
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DOCS = os.path.join(REPO_ROOT, "docs")
BINDINGS = os.path.join(DOCS, "CONTRACT-BINDINGS.json")


def _load():
    with open(BINDINGS, encoding="utf-8") as fh:
        return json.load(fh)


def _defined_names(path):
    """Top-level classes and functions, by AST rather than by regex."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


class TestContractsAreBound(unittest.TestCase):
    def setUp(self):
        self.doc = _load()
        self.bindings = self.doc["bindings"]

    def test_every_contract_document_is_bound(self):
        # 'CONTRACT' anywhere in the stem, not just as the suffix.
        # MCP-CONTRACT-GOVERNANCE.md does not end with CONTRACT.md, and the
        # suffix rule silently left that document out of the whole check.
        on_disk = {n for n in os.listdir(DOCS)
                   if n.endswith(".md") and "CONTRACT" in n}
        bound = {b["contract"] for b in self.bindings}
        self.assertEqual(on_disk - bound, set(),
                         "these contracts have no entry in "
                         "docs/CONTRACT-BINDINGS.json, so nothing reports that "
                         "their rules can be edited without any control "
                         "noticing")

    def test_no_binding_names_a_contract_that_does_not_exist(self):
        # 'CONTRACT' anywhere in the stem, not just as the suffix.
        # MCP-CONTRACT-GOVERNANCE.md does not end with CONTRACT.md, and the
        # suffix rule silently left that document out of the whole check.
        on_disk = {n for n in os.listdir(DOCS)
                   if n.endswith(".md") and "CONTRACT" in n}
        for b in self.bindings:
            self.assertIn(b["contract"], on_disk,
                          f"{b['contract']} is bound but is not a contract document")

    def test_every_binding_names_at_least_one_control(self):
        for b in self.bindings:
            self.assertTrue(b["enforced_by"],
                            f"{b['contract']} is bound to nothing, which is "
                            "the same as not being bound")

    def test_every_bound_test_file_exists(self):
        for b in self.bindings:
            for e in b["enforced_by"]:
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO_ROOT, e["test"])),
                    f"{b['contract']} binds {e['test']}, which does "
                    "not exist")

    def test_every_bound_symbol_exists_in_its_test_file(self):
        """The binding must survive a rename of the control it names."""
        for b in self.bindings:
            for e in b["enforced_by"]:
                path = os.path.join(REPO_ROOT, e["test"])
                defined = _defined_names(path)
                for sym in e["symbols"]:
                    self.assertIn(
                        sym, defined,
                        f"{b['contract']} binds {e['test']} to {sym}, which no "
                        "longer defines it; the contract it covers is no "
                        "longer machine-checked by anything this registry "
                        "can see")

    def test_the_registry_declares_no_unbound_contract(self):
        """known_unbound must not be a place to park a contract quietly."""
        for entry in self.doc.get("known_unbound") or []:
            self.assertNotIn("contract", entry,
                             "a known_unbound entry carrying a contract file "
                             "is a claim that nothing enforces it; that belongs "
                             "in this test as a failure, not in the registry")

    def test_the_registry_is_valid_json_and_declares_its_schema(self):
        self.assertEqual(self.doc["schema"], "rdebug-contract-bindings/1")
        self.assertTrue(self.doc.get("purpose"))


if __name__ == "__main__":
    unittest.main()
