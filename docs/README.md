# `docs/` Index

Every document in this directory, one row each, grouped by topic.

**13 are machine-classified** under `DOCUMENT-CLASSIFICATION-CONTRACT.md`
and are constrained by it; **47 are not classified** and are deliberately not
machine-read. The Role column copies the value from each document's own front
matter; where it reads *not classified* the index is asserting nothing. Grouping
by topic is human judgement, **not schema**, and carries no authority — inventing
a second taxonomy is exactly what the classification contract forbids.

Correctness of this file, including the values in the Role column, is enforced by
`tests/unit/test_docs_index.py`.

## Start here

| Document | Role / freshness |
| --- | --- |
| [`API-REFERENCE.md`](API-REFERENCE.md) | not classified |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | not classified |
| [`CAPABILITIES-AND-BOUNDARIES-2026-10.md`](CAPABILITIES-AND-BOUNDARIES-2026-10.md) | `audit_record` / `point_in_time` @ `d691050` |
| [`P0-P1-UX-READINESS.md`](P0-P1-UX-READINESS.md) | not classified |
| [`OPEN-DECISIONS.md`](OPEN-DECISIONS.md) | `contract` / `living` |

## Current state and evidence

| Document | Role / freshness |
| --- | --- |
| [`CURRENT-EVIDENCE-FREEZE.md`](CURRENT-EVIDENCE-FREEZE.md) | `evidence_record` / `point_in_time` @ `2c6079e` |
| [`PDB-ATTRIBUTION-RESULT.md`](PDB-ATTRIBUTION-RESULT.md) | not classified |
| [`TEARDOWN-EVIDENCE-CASE.md`](TEARDOWN-EVIDENCE-CASE.md) | not classified |
| [`TEARDOWN-CRASH-INVESTIGATION.md`](TEARDOWN-CRASH-INVESTIGATION.md) | not classified |
| [`OBSERVABILITY-CAPABILITY-MATRIX.md`](OBSERVABILITY-CAPABILITY-MATRIX.md) | not classified |
| [`M15-ACCEPTANCE-REPORT.md`](M15-ACCEPTANCE-REPORT.md) | not classified |
| [`REAL_WORLD_VALIDATION.md`](REAL_WORLD_VALIDATION.md) | not classified |
| [`AUDIT-2026-10-02.md`](AUDIT-2026-10-02.md) | not classified |
| [`AUDIT-2026-10-02-B.md`](AUDIT-2026-10-02-B.md) | `audit_record` / `point_in_time` @ `3501bc5` |
| [`AUDIT-2026-10-02-C.md`](AUDIT-2026-10-02-C.md) | `audit_record` / `point_in_time` @ `ddffaa1` |

## Contracts

| Document | Role / freshness |
| --- | --- |
| [`DOCUMENT-CLASSIFICATION-CONTRACT.md`](DOCUMENT-CLASSIFICATION-CONTRACT.md) | `contract` / `mixed` |
| [`A1-FORK-INTEGRITY-CONTRACT.md`](A1-FORK-INTEGRITY-CONTRACT.md) | not classified |
| [`A2-CI-INTEGRATION-CONTRACT.md`](A2-CI-INTEGRATION-CONTRACT.md) | not classified |
| [`BUILD-GENERATION-PROBE.md`](BUILD-GENERATION-PROBE.md) | `contract` / `living` |
| [`CAPTURE-CORPUS-CONTRACT.md`](CAPTURE-CORPUS-CONTRACT.md) | `contract` / `living` |
| [`CI-ORCHESTRATION-CONTRACT.md`](CI-ORCHESTRATION-CONTRACT.md) | `contract` / `mixed` |
| [`CONTROL-ADMISSION-CONTRACT.md`](CONTROL-ADMISSION-CONTRACT.md) | `contract` / `living` |
| [`F12-CONTEXT-EID-CONTRACT.md`](F12-CONTEXT-EID-CONTRACT.md) | not classified |
| [`FIXTURE-POPULATION-CONTRACT.md`](FIXTURE-POPULATION-CONTRACT.md) | `contract` / `living` |
| [`GATE3-COLD-WARM-CONTRACT.md`](GATE3-COLD-WARM-CONTRACT.md) | not classified |
| [`LINT-EXECUTION-CONTRACT.md`](LINT-EXECUTION-CONTRACT.md) | `contract` / `living` |
| [`MCP-CONTRACT-GOVERNANCE.md`](MCP-CONTRACT-GOVERNANCE.md) | not classified |
| [`REPORT-SCHEMA-OWNERSHIP.md`](REPORT-SCHEMA-OWNERSHIP.md) | `contract` / `living` |
| [`SCENARIO-LIFECYCLE-ADJUDICATION.md`](SCENARIO-LIFECYCLE-ADJUDICATION.md) | not classified |
| [`SCOPE-DECISION-RENDERDOC-OWNERSHIP.md`](SCOPE-DECISION-RENDERDOC-OWNERSHIP.md) | not classified |
| [`SESSIONMANAGER-MIGRATION-SCOPE.md`](SESSIONMANAGER-MIGRATION-SCOPE.md) | not classified |

## CI, gates and lifecycle

| Document | Role / freshness |
| --- | --- |
| [`CI-PHASE1-INVESTIGATION.md`](CI-PHASE1-INVESTIGATION.md) | not classified |
| [`CI-EXIT-ACCOUNTING-INVESTIGATION.md`](CI-EXIT-ACCOUNTING-INVESTIGATION.md) | not classified |
| [`CRASH-ACCOUNTING-DESIGN.md`](CRASH-ACCOUNTING-DESIGN.md) | not classified |
| [`CRASH-ACCOUNTING-PORTABILITY.md`](CRASH-ACCOUNTING-PORTABILITY.md) | not classified |
| [`D4-EVIDENCE.md`](D4-EVIDENCE.md) | not classified |
| [`D6-PERFORMANCE-EVIDENCE.md`](D6-PERFORMANCE-EVIDENCE.md) | not classified |
| [`FREEZE-CI-2026-09-29.md`](FREEZE-CI-2026-09-29.md) | not classified |
| [`FREEZE-EID-2026-09-29.md`](FREEZE-EID-2026-09-29.md) | not classified |
| [`FREEZE-EXIT-ACCOUNTING-2026-10-01.md`](FREEZE-EXIT-ACCOUNTING-2026-10-01.md) | not classified |
| [`FREEZE-FORK-EXCEPTION-2026-09-29.md`](FREEZE-FORK-EXCEPTION-2026-09-29.md) | not classified |
| [`FREEZE-PIPELINE-PHASE1-2026-09-29.md`](FREEZE-PIPELINE-PHASE1-2026-09-29.md) | not classified |
| [`FREEZE-PIPELINE-READINESS-2026-10-01.md`](FREEZE-PIPELINE-READINESS-2026-10-01.md) | not classified |
| [`FREEZE-REFLECTION-2026-09-29.md`](FREEZE-REFLECTION-2026-09-29.md) | not classified |
| [`FREEZE-TERMINATION-EVIDENCE-2026-10-01.md`](FREEZE-TERMINATION-EVIDENCE-2026-10-01.md) | not classified |
| [`S2-REFLECTION-EVIDENCE.md`](S2-REFLECTION-EVIDENCE.md) | not classified |
| [`SHADER-REFLECTION-INVESTIGATION.md`](SHADER-REFLECTION-INVESTIGATION.md) | not classified |

## Validation evidence (earlier phases)

| Document | Role / freshness |
| --- | --- |
| [`phase2a.md`](validation/phase2a.md) | not classified |
| [`phase3a-closure.md`](validation/phase3a-closure.md) | not classified |
| [`phase4b-trajectory.md`](validation/phase4b-trajectory.md) | not classified |
| [`phase4c-reasoning.md`](validation/phase4c-reasoning.md) | not classified |
| [`phase4d-session-reuse.md`](validation/phase4d-session-reuse.md) | not classified |
| [`phase5a-ci.md`](validation/phase5a-ci.md) | not classified |
| [`phase5b-ide.md`](validation/phase5b-ide.md) | not classified |
| [`phase5c-observability.md`](validation/phase5c-observability.md) | not classified |
| [`phase5d-workload.md`](validation/phase5d-workload.md) | not classified |
| [`perf-baseline.md`](validation/perf-baseline.md) | not classified |

Machine-readable companions, listed for completeness:

* [`phase3a-closure.json`](validation/phase3a-closure.json)
* [`phase4c-answers.json`](validation/phase4c-answers.json)
* [`phase4c-reasoning.json`](validation/phase4c-reasoning.json)

## Coverage

| | Count |
| --- | --- |
| Documents indexed | 60 |
| Machine-classified | 13 |
| Not classified | 47 |
| Of which validation evidence | 10 markdown + 3 json |

## Known limits of this index

* The unclassified documents are grouped by topic only. That grouping is not
  schema and confers no status; a document may be re-grouped without consequence,
  but it may not gain a role here.
* The index does not restate document contents. Where it lists a role or
  freshness value, that value is copied from front matter and the audit fails if
  the two disagree.
* Adding, renaming or deleting a document requires updating this file; the audit
  fails on an unlisted file, a dangling link, or a document listed twice.
* A document that gains front matter must have its Role cell corrected to match
  the declaration, not left reading *not classified*.
* This index does not list itself.
