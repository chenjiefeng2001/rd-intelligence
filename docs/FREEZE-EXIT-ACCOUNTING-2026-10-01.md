# Freeze — Integration Shutdown Exit Accounting

Date: 2026-10-01
Scope: Gate 1 execution accounting in `scripts/release_gate.py`, and the field
set the pipeline report carries.
State: IMPLEMENTED / VERIFIED / FROZEN.

Precedence, as authorized and pinned:

| tests failed or errored | process exit | outcome |
| --- | --- | --- |
| yes | 0 or non-zero | `REGRESSION` |
| no | 0 | `PASS` |
| no | non-zero | `INFRASTRUCTURE_FAILURE` |
| unparseable or unexecuted | — | `INFRASTRUCTURE_FAILURE` |

## The defect, in one line

A gate that reported clean results and then failed to exit cleanly was recorded
as `PASS`. The integration gate did exactly this on every run: `Ran 63 tests`,
`OK`, `exit_code: 3221225477`, `outcome: PASS`.

## The fix

Two changes, both minimal.

`release_gate.py` — one new branch in the unittest ladder, after the
counted-failure branch and before the skipped branch, so content always
outranks the process exit. No new verdict state, no change to any other runner
kind, no change to `overall()`.

`record()` gained the two-fact field set, with `execution_clean` derived from
`process_exit_code` rather than set beside it.

`ci_pipeline.py` — the pipeline report now carries `tests_executed`,
`tests_failed`, `tests_errors`, `test_result`, `process_exit_code` and
`execution_clean`. Without this the fix would have been cosmetic: the report a
reader actually sees would still show a bare `INFRASTRUCTURE_FAILURE` that reads
exactly like "the tests failed".

No verdict logic, precedence table, exit-code table or runner kind was touched.

## Verification

27 controls in `tests/unit/test_exit_accounting.py`, covering the pinned table,
the retained facts, the reason text, the derivation, and every verdict that had
to stay put.

**Revert-only**: `release_gate.py` reverted to its pre-fix state at HEAD, 13
controls bit, restore returns 22/22. The controls are written against the
defect, so this is the check that they are not tautologies.

**Mutation sweep**: 8 injected defects, all caught.

| Mutation | Caught |
| --- | --- |
| move the process-exit check ahead of the counted-failure check | yes |
| new branch returns `PASS` (the forbidden compatibility path) | yes |
| `execution_clean` hardcoded instead of derived | yes |
| `test_result` blanked, one fact overwritten by the other | yes |
| reason no longer names both facts | yes |
| `execution_clean` field removed | yes |
| `tests_executed` reporting `total` instead of `executed` | **missed, then fixed** |
| restore the defect | yes |

`tests_executed` reporting `total` was invisible because every other control
used a run with `skipped=0`, where the two are equal by construction. A control
now uses a run with `total=3, skipped=2`.

**Real RenderDoc run**:

```
integration   INFRASTRUCTURE_FAILURE
              tests_executed 63   tests_failed 0   tests_errors 0
              test_result OK      process_exit_code 3221225477
              execution_clean False
overall       BLOCKED_INFRA   exit 3
accounting_consistent   True
accounting_inconsist.   none
```

This is the pinned consequence, not a regression, and not a request for a green
pipeline: the non-zero OS exit has entered the frozen four-state model.

**Content still outranks the crash**, checked against real `unittest` runs
rather than scripted output:

| case | outcome | overall |
| --- | --- | --- |
| real failing test, exit 1 | `REGRESSION` | `FAIL_REGRESSION` / exit 2 |
| real passing test, exit 0 | `PASS` | `PASS` / exit 0 |
| real loader failure | `INFRASTRUCTURE_FAILURE` | `BLOCKED_INFRA` / exit 3 |

## Two errors I made, and what they cost

Both were in my verification harness, and in both cases **the classifier was
right and I was wrong**. Worth recording, because the failure mode was
believing a fix was broken.

1. I ran a hand-built failing test with `env={}`. An empty environment stopped
   the child importing, so the run was genuinely a discovery failure and
   `INFRASTRUCTURE_FAILURE` was correct.
2. I then ran it with `cwd` at the repo root, where a temp-directory module is
   not importable — same correct verdict, different cause.
3. I then ran a file with no `unittest.main()` entry point, so it printed
   nothing, failed to parse, and was again correctly `INFRASTRUCTURE_FAILURE`.

Each time I read the verdict as a bug in the fix. A hand-written
`FAILED (failures=1)` string in the synthetic controls would have hidden all
three. So `TestAgainstRealUnittestRuns` now pins the precedence rule against
genuine `unittest` processes, including the loader-failure case that caused the
confusion in the first place.

A separate control error, corrected rather than the code: my helper did not
accept `min_executed`.

## One deviation from the authorized example

`test_result` is emitted as `OK`, not `PASS`. `PASS` is a four-state verdict;
putting it beside `outcome: INFRASTRUCTURE_FAILURE` would use one word in two
roles and invite a reader to treat the test result as the gate verdict. `OK` is
what the runner printed, so nothing is translated, and two controls pin the
choice — including one asserting `test_result` is never one of the four states.

## Readiness was not modified, and that was verified

Readiness's `accounting_inconsistencies` named the row while the outcome was
`PASS`, and now reports `accounting_consistent: True` with an empty list,
because `INFRASTRUCTURE_FAILURE` is a state it already accounts for. The
frozen Readiness Contract needed no change. Verified on the real run rather
than assumed, because "no change required" is exactly the kind of claim that
should be checked.

## Left open, deliberately

- **The native crash itself is not fixed.** Minimal reproducing set is
  `{test_ide_ci_workflow, test_ide_ownership, test_real_replay}`: all three
  pairs clean 6/6, the triple crashes 5/5, under discovery and explicit module
  arguments alike. That is a RenderDoc replay-lifecycle teardown problem, in a
  different subsystem, and it is **not authorized here**. What is fixed is only
  whether such a run may be reported as a pass.
- `tests/workload` has one real failure, `test_mcp_contract`, and belongs to no
  gate. Kept as an independent record. Folding it into an existing gate to make
  gate output tidier is not acceptable; bringing it under governance needs its
  own Contract and authorization.
- Provisioning, workflow wiring, release blocking, Gate 4, Gate 3 coverage,
  nested-action capture, D7 and F-N3-1 remain untouched.

## What would qualify this for the next stage

The pipeline now reports `BLOCKED_INFRA` because a runner in this repository
cannot shut down cleanly. That is the honest state, and it is also a state in
which release blocking would block everything forever. Fixing the teardown is a
prerequisite for ever turning blocking on, not an optional improvement.
