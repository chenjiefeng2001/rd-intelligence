# Integration Teardown Crash — Investigation (Phase 1)

Date: 2026-10-01
State: **REPRODUCED / PARTIALLY EXPLAINED / ROOT CAUSE NOT ESTABLISHED**
Scope: investigation only. **No production code was modified.**

Prerequisite: `docs/FREEZE-EXIT-ACCOUNTING-2026-10-01.md` is frozen. This
investigation exists because the pipeline is currently and correctly
`BLOCKED_INFRA`: a required gate finishes its tests and then cannot exit
cleanly, so release blocking would block forever.

The question is **why the replay lifecycle faults during teardown**, not how to
make the exit code zero. Masking the exit, wrapping the subprocess or calling
`os._exit(0)` would hide a real native lifetime defect and are out of bounds.

---

## 1. Reproducer

Explicit arguments, three modules, 19 tests:

```
python -m unittest tests.integration.test_ide_ci_workflow \
                     tests.integration.test_ide_ownership \
                     tests.integration.test_real_replay
```

`Ran 19 tests`, `OK` on stderr, stdout empty, `exit=0xC0000005`
(`STATUS_ACCESS_VIOLATION`). Deterministic: 5 runs out of 5, no variation.

Each module alone exits `0x00000000`. All three two-module pairs exit `0`.

This is a **reproducing set, not a proven-minimal one.** See the correction in
`CI-EXIT-ACCOUNTING-INVESTIGATION.md` §2: the earlier discovery bisect used the
pattern `test_[ir]*.py`, whose fnmatch character class matches `i` *or* `r`, so
it silently pulled in `test_reflection_reachability.py` and
`test_runtime_isolation.py` as well. Those rows were mislabelled. The explicit
pair/triple data above was collected with separate argv entries and stands.

---

## 2. Established

### 2.1 The fault is in teardown, after the tests have finished

Every reproducing run prints the complete summary — `Ran 19 tests`, `OK` — and
only then exits non-zero. `unittest` had already computed success and called
`sys.exit(0)`. The `0xC0000005` is delivered afterwards, during interpreter and
module finalisation. This is not a test failure wearing an unusual exit code.

### 2.2 What is still alive when teardown begins

Captured with an `atexit` hook, which runs after `unittest` reports `OK` and
before finalisation. Diagnosis only.

```
core._REPLAY_LIFECYCLE = {'initialised': True, 'sessions': 0,
                          'rd': <module 'renderdoc' ...renderdoc.pyd>,
                          'initialise_epoch': 2}
live CaptureSession objects: 1
  session[0] ctrl=None  cap_is_none=True
live SwigPyObject count: 0
renderdoc module in sys.modules: True
rdebug/renderdoc modules loaded (22), including rdebug_ide, rdebug_ide.app
rdebug.workers collections: {}
```

Three things stand out:

- **`initialise_epoch == 2`** — `InitialiseReplay()` ran twice in one process.
- **One `CaptureSession` outlives the run**, and its replay controller is
  `None`: a session object whose native half is gone but whose Python half is
  still referenced.
- **Zero live SWIG native objects.** Nothing native is still owned from Python
  at that point, which makes "a controller was left open" a poor explanation on
  its own.

### 2.3 How epoch reached 2, and that it is not sufficient

`initialise_epoch` can only advance if `_REPLAY_LIFECYCLE["initialised"]` goes
back to `False` (`core.py:279-292`). The only path that does that is
`CaptureSession.shutdown_replay()` succeeding at `ShutdownReplay()`. The only
caller in the tree is a test:

```
tests/integration/test_ide_ownership.py:144
    core.CaptureSession.shutdown_replay()
```

in `TestIdeOwnershipInvariants.test_i3_shutdown_replay_stays_reachable`.

`core.py` already documents epoch > 1 as the **F-N3-4 double-initialisation
condition**, noting it once crashed 23 of 60 Vulkan spawns.

**But epoch 2 is not sufficient to produce this crash.** Measured:

| run | exit |
|---|---|
| `test_i3_shutdown_replay_stays_reachable` alone | `0x00000000` |
| that test + one `test_real_replay` test | `0x00000000` |

So the double initialisation is a real, reachable, self-documented hazard that
this run walks into — and it is **not the fault**. Treating it as the cause
would be the first plausible-looking wrong answer available here.

### 2.4 Module-level locality, and where localisation stops

All seven integration modules exit `0` alone. The three-module set reproduces
`0xC0000005` 5/5. Below module level, isolation breaks the tests rather than the
crash: pairing one `test_ide_ownership` method with the full `test_real_replay`
module yields 5 of 6 ordinary **failures** (`exit=0x00000001`), because those
tests depend on module-level state established by their neighbours. Method-level
minimisation therefore needs a different strategy than running methods
individually, and that strategy is not built yet.

---

## 3. Two errors I made in this phase

Both were harness errors, and in both cases the data was wrong while the
observed verdict was right. Recording them because both cost real time and both
would have produced a false finding.

1. I passed three module names in a single PowerShell string variable. PowerShell
   forwards that as **one** argv entry, `unittest` failed to load it, and the
   run exited `1`. I briefly read that as "the baseline has become
   non-deterministic". It had not; the crash is 5/5 deterministic.
2. I used `$args` as a function parameter name. `$args` is a PowerShell
   automatic variable, so the invocation was mangled: it reported `442` tests
   for a 10-test selection and then consumed a 50-minute timeout.

Neither is a property of the code under investigation. Both are the kind of
error that produces a confident wrong conclusion, which is why they are written
down rather than quietly fixed.

---

## 4. Open, and not to be assumed

- **Which object faults.** `_ctrl=None` on the single surviving `CaptureSession`
  is the prime suspect and is unproven. Zero live SWIG objects argues against the
  obvious "a controller was left open" story.
- **Why only after the body completes.** Consistent with a finalisation-order
  defect: everything succeeds, and the process dies while dismantling state it
  never released. Not established.
- **Worker / process ownership.** The IDE tests spawn worker processes. The probe
  read the parent only, and `rdebug.workers` showed no live collections there.
  The workers' state at their own exit was not observed.
- **Whether `test_reflection_reachability` or `test_runtime_isolation` are also
  implicated.** The mislabelled discovery runs mean those modules were present in
  runs I attributed to three, so their involvement is genuinely unknown.
- **The fault itself has never been captured.** `-X faulthandler` and
  `PYTHONFAULTHANDLER=1` produced no trace, which is itself informative: the
  fault lands where the fault handler is already gone. Capturing it needs a
  debugger or the Windows Application event log, neither of which was used.

## 5. What a fix would have to look like, and what it must not look like

Not a proposal — a boundary, recorded now so a later fix cannot drift into the
easy version.

The question is why replay state outlives the tests and faults on teardown.
Legitimate directions would be about lifetime: who owns the surviving session,
whether the replay runtime is torn down while a Python reference still points at
it, and whether the IDE path leaves a session alive after `dispose()`.

Explicitly not legitimate: making the exit code zero. A subprocess wrapper, exit
masking, or `os._exit(0)` after the summary would produce `PASS` while the native
lifetime defect survives untouched — and would additionally defeat the execution
accounting frozen in `FREEZE-EXIT-ACCOUNTING-2026-10-01.md`, which now exists
precisely to make such a run reportable. A fix that makes the number green
without removing the fault is a regression dressed as a repair.

## 6. Proposed next step, for authorization

Faithful minimisation first, using exact per-module arguments rather than loose
patterns, to establish whether the true trigger is smaller than three modules
and whether the two `test_r*` modules participate. Then fault capture, since
every remaining question in §4 is downstream of knowing where it happens.

Still untouched and unauthorized: `tests/workload`'s `test_mcp_contract`
(independent record), nested-action capture and `context_eid` (independent),
provisioning, workflow wiring, release blocking, Gate 4, Gate 3 coverage, D7 and
F-N3-1.
