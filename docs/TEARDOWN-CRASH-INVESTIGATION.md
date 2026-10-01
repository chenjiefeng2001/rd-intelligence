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

> **Correction, 2026-10-01 (round 2).** The section above is superseded on
> minimality. Measured across all 7 modules: every single (7/7) and every pair
> (21/21) exits `0x00000000`, so the minimum **arity** is 3 — but the
> membership is not unique. `test_real_replay` is **replaceable**: `{B,C,F}` and
> `{B,C,G}` crash 3/3 each. So `{B, C, E}` is a reproducing set of minimal
> arity, not a minimal set uniquely. See §7.
>
> The earlier discovery-pattern error recorded in
> `CI-EXIT-ACCOUNTING-INVESTIGATION.md` §2 remains, and is the reason this round
> used per-module argv with a self-check instead of patterns.


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

---

## 7. Round 2 — faithful minimisation

Method: per-module argv, one list entry per module, no pattern. Before any run
the harness spawns a child that echoes `sys.argv` and asserts it received
exactly the intended entries; a collapse aborts the whole batch. This is the
methodology control the two operational errors earned, and it is the reason the
argv layer is now treated as an observation layer that must be proven rather than
assumed. Every row below records exact argv, discovered, executed, skipped,
unittest state, exit code, and whether `0xC0000005` appeared.

Legend: `A` context_eid_contract, `B` ide_ci_workflow, `C` ide_ownership,
`D` m15_acceptance, `E` real_replay, `F` reflection_reachability,
`G` runtime_isolation.

### 7.1 Singles — all clean (7/7)

| set | disc | exec | state | exit |
| --- | ---: | ---: | --- | --- |
| A | 16 | 16 | OK | `0x00000000` |
| B | 4 | 4 | OK | `0x00000000` |
| C | 6 | 6 | OK | `0x00000000` |
| D | 19 | 19 | OK | `0x00000000` |
| E | 9 | 9 | OK | `0x00000000` |
| F | 2 | 2 | OK | `0x00000000` |
| G | 7 | 7 | OK | `0x00000000` |

### 7.2 Pairs — all clean (21/21)

A+B, A+C, A+D, A+E, A+F, A+G, B+C, B+D, B+E, B+F, B+G, C+D, C+E, C+F, C+G,
D+E, D+F, D+G, E+F, E+G — every one `OK`, `0x00000000`.

**Minimum arity is therefore 3.**

### 7.3 Triples — the discriminator

| set | disc | exec | state | exit | crash |
| --- | ---: | ---: | --- | --- | --- |
| B+C+A | 26 | 26 | OK | `0xC0000005` | yes |
| B+C+E | 19 | 19 | OK | `0xC0000005` | yes |
| B+C+F | 12 | 12 | OK | `0xC0000005` | yes (3/3) |
| B+C+G | 17 | 17 | OK | `0xC0000005` | yes (3/3) |
| B+C+D | 29 | 29 | OK | `0x00000000` | **no** |
| B+E+F | 15 | 15 | OK | `0x00000000` | no |
| B+E+G | 20 | 20 | OK | `0x00000000` | no |
| C+E+F | — | — | — | — | not run; B+E+F clean implies C required |
| E+F | 11 | 11 | OK | `0x00000000` | no |
| E+G | 16 | 16 | OK | `0x00000000` | no |

### 7.4 Answers to the two authorized questions

**Q1 — is `{test_ide_ci_workflow, test_ide_ownership, test_real_replay}` truly
minimal?** No, and specifically in two different ways:

- Its **arity is minimal** (3), since nothing of size 1 or 2 crashes.
- Its **membership is not unique**. `test_real_replay` is interchangeable with
  `test_context_eid_contract`, `test_reflection_reachability` or
  `test_runtime_isolation`. The minimal sets are `{B, C, X}` for
  `X in {A, E, F, G}`.

Both `B` and `C` are **necessary**: with a replay-active third module present,
removing `B` gives `{C,F}` and `{C,G}`, clean; removing `C` gives `{B,F}` and
`{B,G}`, clean.

So the corrected claim is: *`{B, C, E}` is a reproducing set of minimal arity,
not a minimal set, and not the only one.*

**Q2 — do `test_reflection_*` / `test_runtime_*` participate?** **Yes.** They are
not bystanders. `{B,C,F}` crashes 3/3 with 12 tests and `{B,C,G}` crashes 3/3
with 17 tests, each substituting for `E`. Their earlier status of "unknown" came
entirely from the mislabelled discovery runs and is now resolved.

### 7.5 The one genuinely new structural fact

`{B, C, D}` — `test_m15_acceptance` — does **not** trigger, despite being the
largest triple at 29 tests. `A`, `E`, `F` and `G` all trigger at 12 to 26 tests.
Test count is therefore irrelevant, and the third member is not interchangeable
with `D`.

This is the first discriminator that separates triggering from non-triggering
third modules, and it points at what the third member has to *do* rather than how
many tests it contributes: `A`, `E`, `F` and `G` each exercise replay, while `D`
apparently does not. That is a lead for fault capture, not yet a mechanism.

---

## 8. Fault capture — attempted, and it produced a negative result

Ordered after minimisation, as required. Three channels tried, none of which
recorded the fault:

| channel | result |
| --- | --- |
| `-X faulthandler` / `PYTHONFAULTHANDLER=1` | no traceback (round 1) |
| Windows Application event log, last 3 days | **no** python or renderdoc events |
| `%LOCALAPPDATA%\CrashDumps` | 10 dumps, none from python; all 9/20–9/26 from unrelated apps |

The third row is the informative one: **the fault never reaches Windows Error
Reporting.** A genuine unhandled access violation in an ordinary process leaves a
WER report or a local dump. This one leaves neither, across many runs.

That does not mean there is no fault; `0xC0000005` is still
`STATUS_ACCESS_VIOLATION` and it is still deterministic. It means the fault is
not occurring where an external observer can see it — consistent with it landing
so late in finalisation that no reporting path is live, or with a code path that
terminates the process in a way that bypasses WER entirely. Both readings remain
open, and neither is established.

Consistent with this, `faulthandler`'s silence should **not** be read as "no
Python object is involved". It only shows the fault lands where the Python-level
handler is already gone.

### 8.1 What fault capture still needs

Nothing available so far: no debugger was used, and no local dump is being
produced. The cheapest next step is configuration, not code — enable WER
LocalDumps for `python.exe`, which would make the next run leave a dump and give
the faulting module, thread and instruction address. That is a machine setting
and touches no production code.

Everything in §4 remains open: which object faults, why only after the body
completes, worker/PID-side state, and the unload ordering. `epoch == 2` stays
excluded, `_ctrl=None` stays an unproven suspicion, and the accounting Contract
is untouched.

---

## 9. Round 3 — WER LocalDumps, and a pivot to an attached debugger

Authorized as machine-level evidence instrumentation, not a production fix.
Goal: faulting module, thread and instruction/exception address from a faithful
run. Matrix held to the two required controls.

### 9.1 Instrumentation configured

`HKCU\Software\Microsoft\Windows\Windows Error Reporting\LocalDumps` plus a
`python.exe` subkey, `DumpType = 2` (full), `DumpFolder` pointed at an empty
directory. No production code touched. Both registry keys verified after write.

### 9.2 Controls behaved; the instrumentation did not

| control | set | result |
| --- | --- | --- |
| positive | `{B, C, E}` | `OK`, 19 executed, `0xC0000005` **CRASH** |
| negative | `{B, C, D}` | `OK`, 29 executed, `0x00000000` clean |

Both behaved exactly as required, through the argv self-check harness. **No dump
was produced.** Not for the crashing run, and the dump directory was still empty
after both.

That is a clean negative for this channel: with a per-executable full-dump policy
actively configured for `python.exe`, a run that reliably exits `0xC0000005` left
no local dump. The "WER absence" recorded in round 2 therefore reproduces under
explicit instrumentation, and is not explained by missing configuration.

### 9.3 Pivot to an attached debugger

`cdb.exe` from the installed Windows Kits was already present. Attaching it is
strictly more direct for the same goal and touches nothing in the repository, so
the positive and negative controls were re-run under it.

**Positive `{B, C, E}` — fault captured:**

```
ExceptionAddress: 00007ffb9c240a4e
ExceptionCode:     c0000005 (Access violation)
Parameter[1]:      0000000000000000
Attempt to read from address 0000000000000000
```

```
renderdoc_7ffb9bda0000!…+0x2a6eee      <- faulting frame, read of NULL
renderdoc_7ffb9bda0000!…+0x2df47
ucrtbase!<lambda_f03950…>::operator()   <- C++ static destructor
ucrtbase!__crt_seh_guarded_call<…>
ucrtbase!execute_onexit_table+0x3d      <- CRT atexit table
renderdoc_7ffb9bda0000!…+0x23c9c5
renderdoc_7ffb9bda0000!…+0x23cae5
```

**Negative `{B, C, D}` — no access violation reported by the debugger at all.**
The discrimination is therefore observed under the debugger, not inferred from
exit codes alone.

### 9.4 What is established

- **Faulting module**: `renderdoc`, the module carrying RenderDoc's replay and
  layer code. Offset `0x4A0A4E` from base `0x00007ffb9bda0000` in that run.
- **Faulting thread**: the only thread in the process. This is the main thread,
  and no worker process or worker thread is involved at the fault.
- **Phase**: the CRT **onexit table**, driving C++ **static destructors**, inside
  an SEH-guarded call. `unittest` had already finished and printed `OK`; the
  fault is inside native module finalisation. This confirms round 2's §2.1 with
  a stack rather than an inference.
- **Fault shape**: a read of `NULL`, deterministically, at an identical
  instruction address across two separate runs.
- The nearest exported symbols on those frames — `RENDERDOC_EndProfileRegion`,
  `RENDERDOC_CheckAndroidPackage`,
  `VK_LAYER_RENDERDOC_CaptureNegotiateLoaderInterfaceVersion` — are **nearest
  export approximations, not real symbol names.** The region has no public
  symbols, and those three names describe things an image-teardown path would
  never plausibly be doing. They must not be read as evidence of anything.

### 9.5 What is *not* established, and must not be inferred from the above

- **Why a RenderDoc static destructor dereferences NULL.** Unknown. This needs
  symbols or source; it is not derivable from an address.
- **That the faulting destructor is the replay path.** The stack shows
  *module-level static destruction*. Which static is running, and whether it
  belongs to the replay subsystem specifically, is not established. Calling this
  "the replay teardown" would be more specific than the evidence allows.
- **`epoch == 2`** stays excluded as a cause. It remains a co-occurring condition
  whose relevance is unknown; the disproof from round 1 is unaffected.
- **`_ctrl = None`** stays an unproven suspicion. It is not shown to be a leak and
  is not shown to be connected to this destructor.
- **Why WER does not engage.** An AV inside an SEH-guarded static destructor
  driven from the onexit table is a *candidate* reason, but round 2's discipline
  applies: no dump is an observation; the mechanism behind it is still open.

### 9.6 Machine state left behind

The two `LocalDumps` registry keys remain in place, as authorized. They produced
nothing, so they are currently inert. Remove with:

```
Remove-Item -Recurse 'HKCU:\Software\Microsoft\Windows\Windows Error Reporting\LocalDumps'
```

Symbol and dump scratch directories are under the temp directory, outside the
repository.

### 9.7 Position unchanged

`{B,C,X}` trigger family proven for tested `X in {A,E,F,G}`; `D` negative
control proven; minimum arity 3 proven; unique minimal set disproven. The
pipeline remains `BLOCKED_INFRA` / exit 3, correctly. No production fix, no
change to the accounting Contract, no exit masking, `epoch` not reinstated,
`_ctrl=None` not promoted.
