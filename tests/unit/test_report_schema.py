"""Report schema ownership: keep contract 6.1 and the pipeline report agreeing.

Audit finding F1 and F2. The lint implementation added a field to the pipeline
report while the governing field table in the CI contract did not even list
fields the report had carried for weeks, and the schema version moved for
release-gates but not for the pipeline. Nothing failed. That is the problem:
schema drift is silent, because both documents are individually plausible.

The control reads the contract table and the real build_report output and
compares them. It is deliberately bidirectional -- the contract may name a
field the report lacks, and the report may carry a field the contract never
mentions -- because each direction was a real defect here.
"""

import ast
import json
import os
import re
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
CONTRACT = os.path.join(REPO_ROOT, "docs", "CI-ORCHESTRATION-CONTRACT.md")
PIPELINE = os.path.join(REPO_ROOT, "scripts", "ci_pipeline.py")
SPEC = os.path.join(REPO_ROOT, "ci-pipeline.json")

#: Contract names that are explicitly awaiting a ruling. Recorded in 6.1 as
#: pending rather than deleted, so the exemption is visible instead of the
#: requirement quietly disappearing.
PENDING_RULING = ("evidence_ref", "duration_s")


def _contract_rows():
    """[(left_names, right_names)] from the 6.1 mapping table.

    Per row, and every backticked name in both cells. The first version
    captured one backtick group per cell, so `tests_executed / tests_failed /
    tests_errors` registered as only the first, and both directions of the
    comparison below failed for the same reason -- the parser, not the drift.
    """
    with open(CONTRACT, encoding="utf-8") as fh:
        text = fh.read()
    section = text[text.index("### 6.1"):text.index("### 6.2")]
    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 4:
            continue
        left = re.findall(r"`([a-z_]+)`", cells[1])
        right = re.findall(r"`([a-z_]+)`", cells[2])
        if left or right:
            rows.append((set(left), set(right)))
    return rows


def _report_fields():
    """Field names build_report actually emits for a gate row."""
    with open(PIPELINE, encoding="utf-8") as fh:
        source = fh.read()
    start = source.index("def build_report")
    body = source[start:source.index("def collect_readiness")]
    return set(re.findall(r'"([a-z_]+)":\s*g\.get\(', body))


class TestContractAndReportAgree(unittest.TestCase):

    def setUp(self):
        self.rows = _contract_rows()
        self.wanted = set().union(*[a for a, _ in self.rows]) if self.rows \
            else set()
        self.offered = set().union(*[b for _, b in self.rows]) if self.rows \
            else set()
        self.emitted = _report_fields()

    def test_the_contract_table_is_parsed_at_all(self):
        self.assertGreaterEqual(
            len(self.wanted), 8,
            "6.1's table yielded almost nothing; a parsing change would make "
            "every control below pass vacuously")
        self.assertIn("executed", self.wanted)

    def test_every_field_the_contract_binds_to_actually_exists(self):
        """The right-hand column is a promise about the report.

        The left-hand column is the contract's original name, which the right
        column may rename, so requiring the left column in the report was this
        control's first version and it was wrong: it failed on gate_id and
        skipped, both of which 6.1 maps deliberately.
        """
        missing = sorted(self.offered - self.emitted)
        self.assertEqual(
            missing, [],
            f"contract 6.1 binds these names to report fields the pipeline "
            f"report never emits: {missing}. Either the field is emitted or "
            "the contract stops binding it.")

    def test_every_contract_requirement_points_at_something_real(self):
        """Satisfied per row, not per name.

        A row whose two columns differ is a rename, and the old name is not
        expected in the report -- requiring it was this control's second wrong
        version. What must hold is that the row resolves onto at least one
        field the report really emits, so a requirement cannot be satisfied by
        a mapping to nothing.
        """
        hollow = []
        for left, right in self.rows:
            if right & self.emitted or left & self.emitted:
                continue
            if left & set(PENDING_RULING):
                continue
            hollow.append(sorted(left or right))
        self.assertEqual(
            hollow, [],
            f"contract 6.1 has rows mapping onto nothing the report emits: "
            f"{hollow}. Each requirement must resolve onto a real field, or "
            "be listed as awaiting a ruling. Silently dropping one is how the "
            "table became unreliable in the first place.")

    def test_every_emitted_field_is_accounted_for_in_the_contract(self):
        """The direction that actually bit: the report grew a field silently."""
        undeclared = sorted(self.emitted - self.offered)
        self.assertEqual(
            undeclared, [],
            f"the pipeline report carries {undeclared}, which contract 6.1 does "
            "not bind to anything. A field added without a contract entry is "
            "schema drift: tools, auditors and readers each learn a "
            "different shape.")

    def test_pending_rulings_are_still_recorded_as_pending(self):
        """The exemption must not outlive the need for it."""
        text = open(CONTRACT, encoding="utf-8").read()
        section = text[text.index("### 6.1"):text.index("### 6.2")]
        self.assertIn("待裁决", section,
                      "the pending rulings note is gone from 6.1. If those "
                      "fields were ruled on, delete them from the contract; if "
                      "not, the note must stay so the exemption is visible.")

    def test_the_facts_are_produced_not_defaulted(self):
        """build_report forwarding a key is not the same as the fact flowing.

        Found by revert-only: removing the field from release_gate's record()
        left every other control green, because build_report writes
        g.get(field, []) and a default satisfies a key's existence. The
        report then carried an always-empty list, which looks exactly like a
        gate with no missing prerequisites -- the value a reader most needs to
        be able to trust is the one nothing checked.

        So this asserts the producing side: the field is in record()'s literal
        output, not merely forwarded.
        """
        source = open(os.path.join(REPO_ROOT, "scripts", "release_gate.py"),
                      encoding="utf-8").read()
        start = source.index("def run_gate(")
        tree = ast.parse(source[start:source.index("def run_all(")])
        produced = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "record":
                for call in ast.walk(node):
                    if isinstance(call, ast.Dict):
                        for key in call.keys:
                            if isinstance(key, ast.Constant):
                                produced.add(key.value)
        for field in ("missing_prerequisites", "discovery_anomaly"):
            self.assertIn(
                field, produced,
                f"release_gate.record() does not emit {field}, so the pipeline "
                "report's copy of it is a default rather than an observation. "
                "The report would claim a gate had no missing prerequisites "
                "purely because nothing wrote one.")

    def test_schema_versions_match_the_code(self):
        """F2: one schema moved and the other did not."""
        with open(SPEC, encoding="utf-8") as fh:
            spec = json.load(fh)
        source = open(PIPELINE, encoding="utf-8").read()
        code = re.search(r'SCHEMA = "([^"]+)"', source).group(1)
        self.assertEqual(
            spec["schema"], code,
            f"ci-pipeline.json declares {spec['schema']} while ci_pipeline.py "
            f"validates {code}. The pipeline reads the spec it ships with, so a "
            "mismatch turns into a precondition failure at run time rather "
            "than a schema error at review time.")

    def test_schema_history_is_append_only(self):
        """Bumping a version must not erase the ones before it.

        This round's own version bump did exactly that. A script assigned a
        freshly-built dict over schema_history, so release-gates went from six
        entries to one and ci-pipeline from three to one -- while the commit
        carrying the change described itself as making the audit trail
        auditable. The history is the record that makes a version bump
        reviewable; truncating it destroys the evidence and leaves every
        earlier schema unexplained.

        No control looked, because every field check read the current version
        and found it present.
        """
        for name in ("release-gates.json", "ci-pipeline.json"):
            spec = json.load(open(os.path.join(REPO_ROOT, name),
                                  encoding="utf-8"))
            history = spec.get("schema_history") or {}
            self.assertGreaterEqual(
                len(history), 2,
                f"{name} has {len(history)} schema_history entries. A schema "
                "file that has been bumped more than once but documents one "
                "version has had its history truncated rather than extended.")
            for version, text in history.items():
                self.assertTrue(
                    text.strip(),
                    f"{name} documents {version} with empty text, so the entry "
                    "records a version without saying what changed")

    def test_the_new_schema_version_has_a_rationale(self):
        """release-gates was bumped to /6 with only a /5 entry for two commits."""
        spec = json.load(open(SPEC, encoding="utf-8"))
        history = spec.get("schema_history") or {}
        self.assertIn(spec["schema"], history,
                      "the shipped schema version has no rationale entry, so "
                      "the file asserts a version it does not explain. That is "
                      "how release-gates ended up at /6 documenting /5.")


if __name__ == "__main__":
    unittest.main()
