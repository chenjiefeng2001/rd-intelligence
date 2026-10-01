# Freeze — Termination Evidence Classification

Date: 2026-10-01
State: **IMPLEMENTED / VERIFIED / FROZEN**
Extends `aae843c` (phase 1 design), corrects `3866cfe`, supersedes the predicate
recommendation it contained.

Scope: the diagnostic reliability harness only. No gate verdict, exit mapping,
`release_gate.py` behaviour, integration `INFRASTRUCTURE_FAILURE` handling,
release blocking, or workload promotion was touched.

---

## 1. What the defect was

`tests/workload/test_workload_reliability.py` classified a child's death with
`if code < 0`. Measured across clean exit, non-zero exit, traceback, `abort`,
a compiled native access violation and an external kill, **`code < 0` is never
true on Windows.** The predicate could not fire. A real access violation left
`REPORT["reliability"]["crashes"]` at `0`, so the report said the opposite of
what happened.

Two adjacent gaps came out of the same investigation:

- **Timeouts recorded nothing.** `run_isolated` passed `timeout=600` and did
  not catch `subprocess.TimeoutExpired`, which on both platforms has no
  `.returncode`. A hung scenario killed the child and left no entry.
- **`os.WIFSIGNALED` / `os.WTERMSIG` are unusable.** Measured on WSL Ubuntu:
  `WIFSIGNALED(7)` is True after an ordinary `sys.exit(7)`, and
  `WTERMSIG(-9)` is 119 rather than 9. Following the recommendation in
  `3866cfe` would have shipped the mirror image of this bug.

## 2. The change

New `tests/workload/termination.py` classifies evidence and nothing else.
`observe()` returns three layers:

```
execution_result       process_returncode (verbatim, nullable), returncode_present
termination_observation class: normal_exit | python_failure | nonzero_exit
                              | signal_termination | native_termination_suspected
                              | timeout | indeterminate
evidence               platform, completion_sentinel_present, traceback_present,
                       signal_number (posix, = -returncode), ntstatus (nt only)
```

The raw return code is never rewritten; `ntstatus` and `signal_number` are
derived views. `harness.run_isolated` now returns a dict carrying the
observation, catches `TimeoutExpired` and records it. The per-class breakdown
went to a new top-level `REPORT["terminations"]` with a capped
`REPORT["terminationEvidence"]`, **not** into `REPORT["reliability"]` —
`scripts/workload_run.py:51-52` evaluates `all(v == 0 for v in
REPORT["reliability"].values())`, so a nested dict there would silently turn
the workload gate False and read as a workload failure. `reliability["crashes"]`
is now the count of `native_termination_suspected`.

### Boundary, recorded because it is the thing most likely to drift

> **Termination observation is evidence classification, not fault attribution.**

`is_crash()` exists solely to make that mechanical: it **always returns
False**, so a caller reaching for a crash predicate gets a refusal and an
explanation instead of writing its own. The invalid chain

```
native_termination_suspected -> crash -> RenderDoc defect
```

was severed by measurement at the first arrow — on Windows a genuine access
violation and a deliberate `sys.exit(3221225477)` are byte-identical. No
control, field or report line may rejoin it.

`assertEqual(code, 0)` was **kept unchanged**. It detects execution failure,
which is a different question from how the process ended. The defect was
correct detection with wrong attribution, never a swallowed failure.

## 3. Controls — 27, all passing

`tests/unit/test_termination_classification.py` (20, in the unit gate) holds
the pure truth table: raw value preserved, absent returncode representable,
Windows NTSTATUS error range versus warning severity, POSIX negative-only signal
rule, `WIFSIGNALED`/`WTERMSIG` absent from the AST, and six harness-wiring
controls that stub `run_isolated` and assert what lands in the report.

`tests/workload/test_termination_evidence.py` (7) holds the real-process layer:
real `exit(0)`, real `exit(1/2/5/7)`, a real Python traceback, a **gcc-compiled
NULL dereference**, a deliberate `sys.exit(0xC0000005)`, a real external
`taskkill`, and a **real `subprocess.run` timeout**. It skips with a stated
reason where no C toolchain exists rather than faking a return code.

Not gate-enforced, so three unit controls assert that file still exists and
still covers every required case — otherwise it could be deleted silently.

## 4. Revert-only and restore

`harness.py` and `test_workload_reliability.py` reverted to their pre-fix state
at HEAD, `termination.py` retained:

```
Ran 26 tests    FAILED (errors=6)
```

The six failures are exactly the wiring controls: the real timeout escaped
`run_isolated`, the native-status run recorded nothing, the traceback run
recorded nothing, and the report-shape controls could not find their fields.
The defect reappeared.

After restore: `Ran 33 tests    OK` across both control files.

The 20 module-level controls necessarily did not fail during revert, because
the module they test is new. Stated plainly rather than presented as coverage.

## 5. Mutation sweep — 9 injected defects, all caught

| Mutation | Caught |
| --- | --- |
| restore the `code < 0` verdict | yes |
| drop the Windows NTSTATUS branch | yes |
| treat an ordinary non-zero exit as a crash | yes |
| lose the traceback marker | yes |
| use `WIFSIGNALED`/`WTERMSIG` on POSIX | yes |
| `is_crash` returns True | yes |
| stop catching `TimeoutExpired` | yes |
| nest a dict inside `reliability` | yes (3 controls) |
| overwrite the raw `process_returncode` | yes |

## 6. Verified end state

```
python -m unittest tests.workload.test_workload_reliability
Ran 3 tests    OK

ci pipeline: BLOCKED_INFRA (exit 3, conclusion failure)
  unit                    PASS  executed=370   (343 + 27)
  transport               PASS  executed=58
  integration   INFRASTRUCTURE_FAILURE executed=63
  boundary_audit          PASS
  cold_warm_equivalence   PASS
  fork_integrity          PASS
  benchmark_archive       UNKNOWN
```

Gate verdicts, exit codes and the overall conclusion are **unchanged from before
this work**. Ruff clean. The integration teardown AV is untouched and still
`BLOCKED_INFRA`, which remains the honest report.

## 7. Errors made in this phase

Four. Three are the same observation-layer failure as before, which is itself
the finding.

- **An over-broad text control.** `assertNotIn("WIFSIGNALED", source)` flagged
  the docstring sentence that explains why the helper is forbidden. The check
  now parses the AST and looks for real attribute access. Third instance of
  this pattern after the `tests/workload` corpus path and the `ut.TestSuite`
  flattening.
- **A process error that cost rework.** I ran the revert-only experiment with
  `git checkout HEAD --` after backing up only `termination.py`, which destroyed
  my own uncommitted harness edits. They had to be re-applied. Revert-only
  needs a copy of the *fixed* state, not just the ability to get the old one.
- **A mutation aimed at the wrong location.** The report-shape mutation added a
  top-level key while the control inspects `REPORT["reliability"]`, so it was a
  no-op that first read as a missed control. Re-aimed at the real risk — a
  nested dict *inside* `reliability` — and caught by three controls.
- **A naive string check reported `code < 0` still present**, when the only
  match was my own explanatory comment. Confirmed by AST that the sole remaining
  comparison is `code == 0`, which is the correctness check and is unchanged.

## 8. Non-goals observed

`release_gate.py` untouched. Gate 1–5 untouched. Exit mapping 0/2/3/4 untouched.
The integration teardown AV still reports `BLOCKED_INFRA`. No release blocking.
No RenderDoc destructor work. `tests/workload` not promoted to a gate. No new
verdict state. Nothing inferred about a real crash beyond what was measured, and
no exit code treated as proof of one.
