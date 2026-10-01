# Freeze — Pipeline Readiness Contract

Date: 2026-10-01
Scope: DESIGN_SPEC §4.2 (runner capability declaration, missing-prerequisite
classification, readable report, mechanical validation).
State: IMPLEMENTED / VERIFIED.

## What this contract settles

A runner declares what it has. Each gate states what it needs. The report says
which gates could run here and which could not, and why. A missing prerequisite
is an infrastructure fact, not a regression and not a pass.

## Design decisions and why

**Readiness declares, it does not provision.** No install, no download, no
clone. Enforced against the parsed module (imports and spawned commands), not
against its text. The first version of that control was a word search and it
was wrong twice: `pip` is a substring of `pipeline`, and the docstring sentence
explaining that nothing is installed matched its own prohibition.

**Readiness never claims to have executed anything.** Every row reports
`attempted=False, executed=0`. The first implementation defaulted `attempted` to
`not missing`, which reported `attempted=True executed=0` for gates the layer
had never touched — the same did-not-run confusion in the other direction. The
report carries `scope: capability`, and the "a required gate did not execute"
rule applies only under `scope: execution`.

**Absent evidence about one thing is not evidence about another.** The RenderDoc
probe read the module version inside the same `try` as the import check, using a
method the Python module does not expose (`GetVersionTuple`; the real one is
`GetVersionString`). The `AttributeError` unwound into `module_importable`, so a
machine that imports RenderDoc perfectly well was reported as lacking it, and
readiness blocked the entire integration path on a false observation. Import,
version and commit are now three independent observations.

**A refusal without a reason is indistinguishable from a bug.** A blocked gate
lists the missing capability names, and they appear in the reason as well.

**A capability no probe populates can only ever resolve False.** Enforced by
checking that every declared capability's source class exists in the probe
result, so a typo cannot silently block a gate forever.

## Accounting: a contradiction is named, not reclassified

Observed here for real: the integration suite prints `OK` for all 63 tests and
then dies during interpreter shutdown with `0xC0000005` (3221225477). The gate
classifier reads test counts and never the exit code, so the row reads `PASS`.

Reclassifying that is a gate semantics change and is **out of scope for this
contract**. Failing to surface it is an accounting failure and is inside it. The
report therefore carries `accounting_inconsistencies` and `accounting_consistent`,
computed from the gate rows' own `exit_code` against their own `outcome`. The
orchestrator exit and the conclusion mapping are untouched: the pipeline still
exits 4 with `conclusion: neutral`.

Closing the false PASS itself requires a change to `release_gate.py` and is
**not authorized here**. See Open items.

## Verification

Controls: 47, all passing. They cover capability declaration, four-state
classification, the required-did-not-run rules, report validation, pipeline
accounting, and the shipped declarations.

Mutation sweep — 15 injected defects, all caught:

| Mutation | Caught |
|---|---|
| version failure flips importability | yes |
| capability row claims `attempted=True` | yes |
| missing required capability → PASS | yes |
| missing required capability → UNKNOWN | yes |
| blocked gate omits the missing names | yes |
| `attempted=False` with `executed=1` accepted | yes |
| overall PASS ignoring an unexecuted required gate | yes |
| `cross_check_exit` stops comparing | yes |
| `missing_requirements` always empty | yes |
| `requires` declarations ignored | yes |
| `capability_satisfied` always true | yes |
| PROCESS_ONLY gate → PASS | yes |
| accounting always empty | yes |
| `pass_with_nonzero_exit` unnamed | yes |
| readiness claims it executed gates | yes |
| readiness failure reported as available | yes |
| readiness rewrites overall exit code | yes |
| readiness rewrites a gate outcome | yes |
| readiness suppresses the accounting check | yes |

Four of these were missed on the first attempt and each miss found a real gap:

- *missing required capability → PASS* and *PROCESS_ONLY → PASS* passed because
  the local machine is fully provisioned, so the missing branch was never
  reached. The controls now construct the absence explicitly.
- *PROCESS_ONLY → PASS* mattered because on this machine that single gate is the
  only thing holding the overall at `NEEDS_REVIEW` / exit 4 rather than PASS.
- *readiness suppresses the accounting check* passed because the comparison used
  only clean rows. It now uses the contradictory row.

Two controls were themselves wrong and were corrected rather than the code:
`capability_satisfied` takes `(environment, requirement)`, not the reverse; and
patching this suite's own copy of `pipeline_readiness` proved nothing about the
module `ci_pipeline` actually imports, which is a different object.

## Result on this machine

Readiness: all seven gates runnable. RenderDoc 1.46, fork present, module
importable, GPU present with replay support, captures present (0 tracked in
git), runtime OK.

Pipeline overall unchanged: `NEEDS_REVIEW`, exit 4, `conclusion: neutral`.
`benchmark_archive` remains `PROCESS_ONLY / UNKNOWN`, which is what keeps the
overall out of PASS.

Accounting: `integration pass_with_nonzero_exit (3221225477)`.

Unit 298 (was 251; +47 readiness controls), transport 58, integration 63,
boundary, cold/warm, fork all as before. Ruff clean.

## Schemas

- `release-gates.json`: `rdebug-release-gates/5` — gates declare
  `requires.capabilities` as dotted names resolvable against a probe result.
- `ci-pipeline.json`: `rdebug-ci-pipeline/2` — declares the four capability
  classes explicitly and links the readiness module.
- `ci-pipeline-report/2` — adds `readiness`, `accounting_inconsistencies`,
  `accounting_consistent`.

## Open items, not authorized here

- The `integration` false PASS (`PASS` with a crashing exit) still exists in
  `release_gate.py`. This contract makes it visible and does not fix it.
- No git remote, so `.github/workflows/ci.yml` remains declarative only; the
  readiness probe has never run on a hosted runner.
- 0 tracked `.rdc`: corpus presence depends on an external directory. Readiness
  reports it as present here and as absent on a clean checkout, which is the
  intended behaviour, but the corpus is not version-controlled evidence.
- Capture requirement is declared per gate; `_probe_gpu` still reads
  `RDEBUG_INTEGRATION_CAPTURE`, so a Gate 3 run needs its capture path set.
- Readiness was never exercised in an environment where a capability is
  genuinely absent. The missing branches are covered by constructed
  environments, not by an observed absence.
