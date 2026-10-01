# CI Crash Accounting Portability — Phase 1 Investigation

Date: 2026-10-01
State: **INVESTIGATION COMPLETE / NO CODE CHANGED**
Scope: locate the existing classification paths and establish cross-platform
semantics. **No production code, gate semantics, exit mapping or release
blocking changed.**

---

## 1. Headline finding, and a correction to the framing

The issue was raised as "the pipeline may fail to count the integration
teardown crash". The evidence says something narrower and different:

- **The pipeline does surface it.** The frozen accounting reports
  `execution_clean: false`, `process_exit_code: 3221225477` and
  `test_result: "OK"` on the same row, and the overall verdict is
  `BLOCKED_INFRA / exit 3`. The crash is visible, correctly, to a reader.
- **Exactly one classification path in the repository is platform-fragile, and
  it is not a gate.** It is a counter in a diagnostic harness.

So the defect is real but smaller than "CI crash accounting" implies, and it is a
*misattribution* problem rather than a *missed failure* problem. Both halves of
that matter for how it should be fixed.

## 2. Inventory of every path that interprets a process exit

| site | predicate | platform-safe? |
| --- | --- | --- |
| `tests/workload/test_workload_reliability.py:19` | `code < 0` → `record_failure("crashes", …)` | **NO — dead on Windows** |
| `scripts/release_gate.py:296` (`exit_code` runner) | `proc.returncode != 0` | yes |
| `scripts/release_gate.py:320` (`exit_code` runner) | `proc.returncode != 0` | yes |
| `scripts/release_gate.py:214` | `execution_clean = exit_code == 0` | yes |
| `scripts/release_gate.py` unittest branch | clean counts + `returncode != 0` | yes |
| `scripts/ci_pipeline.py:90` | `probe.returncode != 0` | yes |
| `scripts/audit_fork_integrity.py:114` | `out.returncode != 0` | yes |
| `scripts/pipeline_readiness.py:338` | exit ↔ report-state agreement | yes |
| `src/rdebug/worker_manager.py:440` | `not w.alive()` → `reason="worker_died"` | yes — **liveness, not exit code** |

Every site except one asks "was it zero / is it still alive", which is
platform-agnostic. The single site that asks "does this number look like a
crash" is the fragile one.

`worker_manager` is worth calling out as the in-repo counter-example: a dead
worker is detected by **liveness**, never by exit code. `WorkerError` carries
`rc` only inside its message text (`worker_manager.py:218`). That design is
already correct on every platform, and it is the model the fix should follow
rather than reinvent.

## 3. Measured Windows semantics — real subprocesses

Every row is a real child process, measured through
`subprocess.run(...).returncode` on this machine.

| case | returncode | hex | `code < 0`? |
| --- | ---: | --- | --- |
| clean `sys.exit(0)` | 0 | `0x00000000` | False |
| `sys.exit(1)` with stderr | 1 | `0x00000001` | False |
| `sys.exit(7)` | 7 | `0x00000007` | False |
| **`os.abort()`** — real abnormal termination | 3221226505 | `0xC0000409` | **False** |
| **C program, NULL dereference** — real AV, no Python involved | 3221225477 | `0xC0000005` | **False** |
| `sys.exit(3221225477)` — *deliberate* | 3221225477 | `0xC0000005` | **False** |

Two conclusions:

1. **`code < 0` is never true on Windows**, for any of these. The existing
   predicate cannot fire. This is now measured rather than inferred.
2. **Exit status alone is ambiguous.** A program that deliberately calls
   `sys.exit(3221225477)` produces a value *identical* to a genuine access
   violation. Any predicate built purely on the NTSTATUS value will therefore
   have false positives, and this is a property of the signal, not of a
   particular implementation.

The C-level AV also independently reproduces the value the frozen pipeline
report recorded for the RenderDoc teardown fault (`0xC0000005`), confirming the
teardown finding is an ordinary access violation and not a Python artefact.

## 4. The Unix side, stated as documented semantics

Not measured — there is no POSIX environment here, and guessing would repeat the
mistake recorded in §6.

CPython documents that on POSIX a child killed by signal *N* yields
`returncode == -N`, so the idiomatic test is `rc < 0` or `os.WIFSIGNALED(rc)`.
That is the convention the current predicate was written for, and it is correct
*there*. The defect is that it was written for one platform and never qualified
for the other.

`os.WIFSIGNALED` and `os.WTERMSIG` do not exist on Windows, so any shared helper
must branch on `os.name` rather than assume.

## 5. What the current failure actually does — precision

The workload path is:

```python
if code != 0 or "SCENARIO_OK" not in out:
    ok = False
    if code < 0:                       # never true on Windows
        record_failure("crashes", …)
    elif "error" in err and "Traceback" in err:
        record_failure("unhandledExceptions", …)
self.assertEqual(code, 0, …)
```

So on Windows, when a scenario dies from an access violation:

- the test **still fails** — `assertEqual(code, 0)` does not care why;
- `REPORT["reliability"]["crashes"]` stays **0**;
- the `elif` fallback does not rescue it, because a hard AV produces no Python
  `Traceback`.

The failure is therefore **not silent**. What is wrong is the *kind* recorded:
a crash is filed as neither a crash nor an unhandled exception, so
`workload-report.json` under-reports the exact failure mode this repository
reproducibly produces. Anyone reasoning from that report would be told the
scenarios are clean of crashes.

## 6. Candidate predicate — definition only, not implemented

Two tiers, because §3 shows the exit status is ambiguous on its own.

**Tier 1 — unambiguous: liveness or a completion sentinel.**

The harness already has one. A scenario prints `SCENARIO_OK` only on success, so
`"SCENARIO_OK" not in out` means "did not complete" with no ambiguity at all.
This is the occurrence signal, and it is already in use.

**Tier 2 — heuristic: label the kind from the exit status.**

- POSIX: `rc < 0` → killed by signal `-rc` (`WTERMSIG`).
- Windows: `status = rc & 0xFFFFFFFF`; treat as abnormal termination when
  `status & 0xFFFF0000 == 0xC0000000` — the NTSTATUS severity/customer shape
  that covers `0xC0000005` access violation, `0xC0000409` abort, `0xC0000374`
  heap corruption, `0xC000001D` illegal instruction. This deliberately excludes
  ordinary small exit codes and `0x8000xxxx` warning statuses.

Tier 2 should be described as a **heuristic for labelling**, never as proof of a
crash, because §3's deliberate-`sys.exit` case is indistinguishable from a real
fault. Any report field it produces should be named for what it is, e.g.
`abnormal_termination_suspected`, not `crashed`.

**Requirements for any implementation, if authorized later**

- Must branch on platform, not assume POSIX.
- Must not weaken the existing `assertEqual(code, 0)`. That assertion is correct
  and fail-closed today.
- Must not touch `release_gate.py`'s verdicts, `ci_pipeline.py`'s report schema,
  or any frozen contract.
- Must carry a control that runs on Windows and fails without the fix, since the
  defect is invisible on POSIX and a POSIX-only suite would never catch it.

## 7. Adjacent observation, out of scope

`release_gate.py:320` classifies **any** non-zero exit of a subprocess gate as
`REGRESSION`:

```python
if proc.returncode != 0:
    return record(REGRESSION, f"exit {proc.returncode}: {tail[:120]}", …)
```

If the *gate binary itself* crashed, that is an infrastructure failure, not a
content regression — the same distinction the just-frozen accounting draws for
unittest gates. This is platform-agnostic, so it is **not** part of this
workstream, and changing it would be a gate-semantics change. Flagged for a
decision, not proposed here.

## 8. Errors made in this phase

Recorded because each could have produced a confident wrong conclusion, and one
nearly inverted its own finding.

- **Two wrong `unittest` class-name guesses** in the previous phase produced
  `_FailedTest` load errors that briefly read as evidence. The correct class was
  `TestM15Matrix`.
- **An asserted sign.** I computed `3221225477 - 2**32`, concluded that Python
  returns a negative `returncode` on Windows, and therefore that the `code < 0`
  crash counter was functional. The frozen pipeline report records the same API
  returning **positive** `3221225477`. The defect is real; my first evidence for
  it was wrong, and only a measured artifact settled it. This phase re-measured
  rather than re-argued, which is why the matrix in §3 exists.
- **A first synthetic AV attempt that did not fault.** `msvcrt.memset` at address
  1 returned exit `0`. Had I stopped there it would have looked like evidence
  that crashes surface as `0`. It was replaced with a compiled C program and
  with the in-project teardown observation.

The common factor is unchanged: acting on the observation layer before verifying
it. Two of these three errors are inherited from earlier phases, which suggests
the pattern is not situational.

## 9. Non-goals observed

Teardown crash not reopened. No PDB attribution. RenderDoc untouched. Frozen
gate contracts and `afbd3fa` evidence untouched. `test_mcp_contract` not promoted.
No gate semantics, exit mapping or release blocking changed. No crash-accounting
workaround applied. Nothing excluded to reduce red.
