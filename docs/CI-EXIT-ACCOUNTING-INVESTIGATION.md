# Integration Shutdown Exit Accounting — Investigation & Contract

Date: 2026-10-01
Scope: Gate 1 execution accounting / `release_gate.py` orchestration.
State: INVESTIGATION COMPLETE / CONTRACT PROPOSED / **no code changed**.

Authorized scope is strictly the trustworthiness of an *execution result*, not
the presence of an environment. Readiness is frozen and untouched. Provisioning,
workflow wiring, release blocking, Gate 4, Gate 3 coverage, nested-action
capture, D7 and F-N3-1 are all out of scope and not done.

---

## 1. The observed fact

`release-gates.json` declares the integration gate as:

```
command: ["python","-m","unittest","discover","-s","tests/integration","-t","."]
runner:  "unittest"
min_executed: 55
```

Running exactly that command:

```
stdout:  (empty)
stderr:  Ran 63 tests in 154.018s
         OK
exit:    -1073741819  ==  0xC0000005  ==  3221225477  (STATUS_ACCESS_VIOLATION)
```

Deterministic: 7 runs out of 7 produced `0xC0000005`. The gate row nonetheless
carries `outcome: PASS`, `executed: 63`, `exit_code: 3221225477`.

`0xC0000005` is not a Windows status this project produces deliberately; it is
`STATUS_ACCESS_VIOLATION`.

## 2. Localization

| Run | Tests | Exit |
|---|---|---|
| `unit` discover | 298 | `0x00000000` |
| `transport` discover | 58 | `0x00000000` |
| each of the 7 integration modules, alone | — | `0x00000000` (7/7) |
| minimal `CaptureSession` probe, then exit | — | `0x00000000` |
| integration discover, all 7 modules | 63 | `0xC0000005` (7/7) |

Cumulative bisect under the gate's own discovery invocation:

| modules | exit |
|---|---|
| 1 `context_eid` | `0x00000000` |
| 3 `+ide_*` | `0x00000000` |
| 4 `+m15_acceptance` | `0x00000000` |
| 5 `+real_replay` | `0xC0000005` |

Minimal reproducing set: **`{test_ide_ci_workflow, test_ide_ownership,
test_real_replay}`**. All three pairs clean (6/6 runs); the triple crashes (5/5
runs), identically under discovery and under explicit module arguments.

Two consequences for how this defect is understood:

- **It is not attributable to any single test module.** Each module is clean
  alone. It is an interaction, so "the flaky test" is not the right frame and
  no per-test skip is a legitimate remedy.
- **It is not caused by test count.** `m15_acceptance + real_replay` runs 37
  tests and exits `0`; the crashing triple runs 28.

Root-causing the native teardown interaction is a different fix, in
`renderdoc`'s replay lifecycle, and is **not authorized here**. This workstream
fixes only whether such a run may be reported as a pass.

---

## 3. The six questions

### Q1 — Which runner/entrypoint produces this exit code?

The declared entrypoint above, spawned as a child process by
`scripts/release_gate.py:219` (`subprocess.run(..., capture_output=True)`).

The two results come from different producers inside that one child:

- `Ran 63 tests` / `OK` — `unittest`'s `TextTestRunner`, written to the child's
  **stderr**.
- the exit code — **not unittest**. `unittest.main()` computes
  `sys.exit(not result.wasSuccessful())`, which for 63 passing tests is `0`. The
  value `0xC0000005` is delivered by the OS while the interpreter was
  finalizing, *after* the summary had been written and after unittest had already
  requested exit `0`.

So the exit code is a process-level fact about the runner, produced strictly
later than the test-result fact, and it overrode the exit code unittest asked for.

### Q2 — Where do "63 tests PASS" and the process exit code respectively come from?

| Fact | Source in code |
|---|---|
| counts and `OK`/`FAILED` | `_parse_unittest` (`release_gate.py:80-100`) regexes `RAN`, `SKIPPED`, `FAILURES`, `ERRORS`, `FAILED` over `stdout + stderr`; a `FAILED` match beginning `OK` yields `verdict: "OK"` |
| `executed = 63` | `total - skipped` from the same parse |
| `exit_code` | `proc.returncode`, populated at `release_gate.py:220-223` |

Two independent channels over one process. They can and do disagree, and nothing
in the classifier reconciles them.

### Q3 — How does the current Gate 1 Contract distinguish test-result success from process execution failure?

**It does not.** This is a gap in the frozen Contract text itself, not only in
code, and it is readable directly from `docs/CI-ORCHESTRATION-CONTRACT.md`:

- **§4** enumerates exactly four execution-accounting situations: `skipped`,
  `0 executed`, missing environment, discovery anomaly. A run that produced
  results and then failed to exit cleanly is **not among them**.
- **§6.1** lists `exit_code` / `duration_s` as **过程证据** (process evidence) —
  a field to be recorded, explicitly not a verdict input.
- **§6.2** states the invariants, and they constrain only `attempted = true` and
  `executed > 0`. **No invariant binds `exit_code` to `outcome`.**

The classifier mirrors the Contract exactly. The unittest ladder
(`release_gate.py:243-280`) branches on `counts` and on test identities, never on
`proc.returncode`.

### Q4 — Should a shutdown crash be `INFRASTRUCTURE_FAILURE`, or is there a more precise state?

The question presumes one verdict must carry both facts. It should not, and a
fifth verdict state is **not** an option: the four-state semantics of §4.1 are
frozen, and `NEEDS_REVIEW`/`BLOCKED_INFRA`/`FAIL_REGRESSION` must stay
distinguishable at the exit code.

Splitting the facts is the precise answer:

- **Gate verdict: `INFRASTRUCTURE_FAILURE`.** §4's own wording for a discovery
  anomaly is that a module which cannot be imported is 基础设施问题，不是内容回归.
  A runner that dies in its own teardown is the same category. It is not
  `REGRESSION`: that verdict would send an investigator hunting a rendering
  regression that does not exist — the same misdirection §4.1 already corrected
  once.
- **`INFRASTRUCTURE_FAILURE` alone is not sufficient**, because it would erase the
  true fact that 63 tests ran and passed. The row must therefore carry the
  test-result facts (`executed=63`, `failures=0`, `errors=0`, `verdict=OK`)
  *and* the process facts (`exit_code`, `execution_clean=false`), with a reason
  naming both.

MUST NOT report `PASS`: the run was not clean, and `PASS` is the defect.
MUST NOT introduce a fifth state.

### Q5 — Where in `release_gate.py` is the exit code lost?

**Not in the plumbing.** `record()` defaults `exit_code: None` (line 202) and
every branch in the unittest ladder passes `exit_code=proc.returncode` (lines
253, 258, 266, 272, 277, 280). The value is present in the report — which is
exactly how the frozen readiness accounting was able to name
`integration pass_with_nonzero_exit (3221225477)`.

**Lost at the decision.** `proc.returncode` appears in no `if` condition
anywhere in the unittest branch, so line 278 executes:

```python
return record(PASS, f"{counts['executed']} checks executed, all passed",
              exit_code=proc.returncode, **counts)
```

The defect is an **inconsistency between runner kinds**, not a missing field. The
`exit_code` runner branch at line 282 does gate on the process:

```python
if proc.returncode != 0:
    return record(REGRESSION, f"exit {proc.returncode}: {tail[:120]}", ...)
```

So `scripts/audit_boundaries.py`, `audit_fork_integrity.py` and the other
subprocess gates treat a non-zero exit as decisive, while every unittest gate
ignores it. The same non-zero exit is a verdict for one runner kind and inert
evidence for the other.

### Q6 — Is there a risk of a normal test failure being misclassified by the same fix?

**Yes, and it is the primary design hazard.** Measured on this machine: a genuine
content failure exits non-zero as well —

| case | stderr | exit |
|---|---|---|
| real content failure | `FAILED (failures=1)` | `1` |
| results OK, crashes in teardown | `OK` | `0xC0000005` |

Both are non-zero. A rule of the form "non-zero exit ⇒ `INFRASTRUCTURE_FAILURE`"
would therefore convert **every real regression** into an infrastructure failure
and hide it — the exact mirror image of the defect being fixed. Exit code alone
cannot discriminate; only counts and identities can.

Required precedence, preserving the existing order:

1. missing prerequisites → `INFRASTRUCTURE_FAILURE` (pre-run, unchanged)
2. `executed == 0` → `INFRASTRUCTURE_FAILURE` (unchanged)
3. below `min_executed` → `INFRASTRUCTURE_FAILURE` (unchanged)
4. discovery anomalies → `INFRASTRUCTURE_FAILURE` (unchanged)
5. `failures or errors` → **`REGRESSION`** (unchanged, and still first)
6. `skipped` → `UNKNOWN` (unchanged)
7. **NEW** counts clean **and** `proc.returncode != 0` → `INFRASTRUCTURE_FAILURE`,
   reason naming both the clean result and the unclean exit
8. counts clean and `returncode == 0` → `PASS` (unchanged)

Under this order a crash that accompanies real failures stays `REGRESSION` — the
content conclusion stands — while the crash is still carried in the row.

Second hazard, explicitly forbidden by the authorization: the new branch must be
able to **withhold** `PASS`. No "non-zero exit but still a pass" compatibility
path is permitted.

---

## 4. Contract

**Status: IMPLEMENTED / VERIFIED / FROZEN — 2026-10-01.** See
`docs/FREEZE-EXIT-ACCOUNTING-2026-10-01.md`. The precedence table below is the
authorized ruling and is pinned by `tests/unit/test_exit_accounting.py`.

### 4.1 Two facts, one verdict field

A gate row carries a **test-result verdict** and a **process-execution fact**,
and the row must never be readable as though only the first existed.

New required fields on every row:

| field | meaning |
|---|---|
| `execution_clean` | derived: `process_exit_code == 0` |
| `test_result` | the runner's own word, `OK` / `FAILED`, as `_parse_unittest` read it |
| `process_exit_code` | the process's own exit code |
| `tests_executed` | checks that ran, `total - skipped` |
| `tests_failed` / `tests_errors` | counted failures and errors |

`exit_code` is retained for existing consumers. `execution_clean` is **derived**
from `process_exit_code`, never set independently: two names for one number
drift the moment one is edited alone. A control asserts the derivation for
`0`, `1` and `3221225477`, and a mutation that hardcoded `execution_clean: True`
was caught.

### 4.1.1 One deliberate deviation

The authorized example shows `test_result: PASS`. This implementation emits
`OK`.

`PASS` is a member of the frozen four-state verdict vocabulary. Writing
`test_result: PASS` beside `outcome: INFRASTRUCTURE_FAILURE` puts the same word
in two roles in one row, reads as self-contradictory at a glance, and invites a
consumer to treat the test result as the gate verdict. `OK` is what
`_parse_unittest` matched out of the child's stderr, so nothing is translated
and the field cannot be mistaken for `outcome`. Two controls pin this,
including one asserting `test_result` is never one of the four states.

### 4.2 The pinned rule

| tests failed or errored | process exit | outcome |
| --- | --- | --- |
| yes | 0 or non-zero | **`REGRESSION`** |
| no | 0 | **`PASS`** |
| no | non-zero | **`INFRASTRUCTURE_FAILURE`** |
| unparseable or unexecuted | — | **`INFRASTRUCTURE_FAILURE`** |

Implemented as a single new branch placed **after** the counted-failure branch
and **before** the skipped branch, so content always outranks the process exit.

One precedence point the ruling did not specify: `skipped > 0` *and* a non-zero
exit. INFRA was chosen over UNKNOWN, because UNKNOWN means "no content
conclusion for the skipped part", which presumes a clean run, and an unclean run
has not earned that presumption. No gate currently reaches this case — the
integration gate reports `skipped=0` — so the choice has no behavioural effect
today and is recorded for future gates rather than left implicit.

### 4.3 MUST

- A non-zero process exit MUST be able to withhold `PASS`.
- The reason for an unclean execution MUST state the test results *and* the exit
  code, so a reader never has to choose which of the two to believe.
- The row of a crashed-but-clean run MUST still report `tests_executed`,
  `tests_failed`, `tests_errors` and `test_result`.
- The pipeline report MUST carry all of them. Dropping them at the reader would
  make `INFRASTRUCTURE_FAILURE` indistinguishable from a run whose tests failed,
  which is the misreading this change exists to prevent.
- Any classification that infers content from the exit code alone is FORBIDDEN.

### 4.4 MUST NOT

- MUST NOT reclassify a counted failure or error as anything but `REGRESSION`.
- MUST NOT introduce a fifth verdict state; the four states of §4.1 are frozen.
- MUST NOT add a compatibility path that returns `PASS` on a non-zero exit.
- MUST NOT modify the frozen Readiness Contract. Readiness reports
  `INFRASTRUCTURE_FAILURE` as an accounted state, so its
  `accounting_inconsistencies` correctly stops naming this row once the outcome
  is honest. Verified on the real run, not assumed.

### 4.5 Expected consequence

The integration gate moves `PASS` → `INFRASTRUCTURE_FAILURE`. Overall moves
`NEEDS_REVIEW / exit 4` → `BLOCKED_INFRA / exit 3`. Confirmed on the real run.
This is the correct direction, and it is not a request to make the pipeline
green: the non-zero OS exit has entered the frozen four-state model.


---

## 5. Incidental finding, outside every gate

`tests/workload` has one real failure:
`tests.workload.test_workload_reliability.TestReliabilityScenarios.test_mcp_contract`
(`Ran 10 tests`, `FAILED (failures=1)`).

`tests/workload` is **not** a gate in `release-gates.json`, so this does not
affect the pipeline verdict and is **not** fixed here — CI-ORCHESTRATION-CONTRACT
§5 classifies machine-dependent items as diagnostic and forbids them from
influencing the overall verdict. It is recorded because it is a real failure that
no gate currently reports.

## 6. Verification required before freeze

- A defect-version control suite that fails against today's `release_gate.py` and
  passes after the minimal fix.
- Revert-only regression: re-apply the pre-fix `release_gate.py`, confirm the
  controls fail, restore, confirm they pass.
- A real RenderDoc run: the integration gate end to end, asserting the new fields
  and that `accounting_inconsistencies` no longer names the row.
- Mutation injections, including one that moves the process-exit check ahead of
  the counted-failure check, to prove precedence cannot be silently reordered.
