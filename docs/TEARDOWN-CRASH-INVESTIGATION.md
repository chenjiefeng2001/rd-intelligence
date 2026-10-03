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

---

## 10. Freeze status at `f579b6d`

Workstream **COMPLETE / VERIFIED**. Root cause **OPEN / NOT_EXPLAINED**.

The defect can now be stated exactly this far:

> A deterministic NULL-read access violation occurs in a **C++ static
> destruction phase inside the RenderDoc module**, driven from the CRT onexit
> table, after the test body completed and `OK` was printed.

And **not** any further:

> ~~a known object in RenderDoc's replay teardown failed to destruct~~ — the
> stack shows *module-level static destruction*. Which static it is, and whether
> it belongs to the replay subsystem, is unknown.

| evidence | status |
| --- | --- |
| arity = 3 | **PROVEN** |
| `{B,C,X}` trigger family | **PROVEN** for tested `X in {A,E,F,G}` |
| `{B,C,D}` negative control | **PROVEN** |
| faulting module = RenderDoc | **PROVEN** |
| fault = NULL-read AV (`0xC0000005`) | **PROVEN** |
| faulting address `renderdoc+0x4A0A4E` | **PROVEN, reproduced** |
| faulting thread = main, no worker | **PROVEN** |
| phase = CRT onexit / static destruction | **PROVEN** |
| specific static destructor | **UNKNOWN** |
| specific source object / pointer | **UNKNOWN** |
| NULL dereference mechanism | **UNKNOWN** |
| replay subsystem attribution | **UNKNOWN** |
| `epoch == 2` as cause | **EXCLUDED** |
| `_ctrl = None` as cause | **UNPROVEN** |
| "not simply a missing LocalDumps config" | **PROVEN** (round 3) |
| why WER never engages | **OPEN** |
| accounting workaround | **NONE** |
| production code modification | **NONE** |

### 10.1 Stop boundary

Frozen here. **No mechanism may be inferred from `0x4A0A4E` or from the nearest
export names.** An address plus a nearest-export approximation is not a
function identity, and the three nearest exports on those frames describe work an
image-teardown path would not plausibly be doing.

### 10.2 Feasibility note for a future symbol/source attribution workstream

Recorded as a scoping fact only; no attribution was performed.

A matching `renderdoc.pdb` (4.03 MB) sits beside the loaded module at
`renderdoc\x64\Release\pymodules\renderdoc.pdb`, timestamped
`2026-08-24 09:18:55`, identical to `renderdoc.pyd`. Round 3 resolved frames to
nearest exports only, because the cdb symbol path pointed at the Microsoft
symbol server and not at this local PDB. Attribution therefore looks feasible
without obtaining a symbol package, but whether the PDB actually covers the
faulting offset is **untested** and must not be assumed.

The boundary that would apply, if authorized: attribute the address to a function
and source statement, identify the static and the NULL pointer, trace its
lifetime, and check the attribution against the `{B,C,D}` negative control.
Not in scope: changing the destructor, altering the exit path to avoid
destruction, treating `_ctrl = None` as the faulting pointer, upgrading "belongs
to RenderDoc" into "RenderDoc replay subsystem defect", or touching CI
accounting or exit semantics.

---

## 11. Attribution outcome and closing freeze language

Added after the attribution phase (`ddec0a1`). Workstream status:

```
CLOSED FOR NOW

location:
    ESTABLISHED
    module:  renderdoc.dll        (NOT renderdoc.pyd)
    address: renderdoc.dll image offset 0x4A0A4E
    fault:   NULL-read access violation, c0000005
    phase:   CRT onexit / C++ static destruction, after test completion
    thread:  main

attribution:
    NOT_ESTABLISHED

root cause:
    OPEN
```

### 11.1 Frozen statements

> This round confirms the fault image is **`renderdoc.dll`**, not the Python
> extension `renderdoc.pyd`. The fault address is established to instruction
> level as a NULL-read, but because the current symbol file does not provide a
> private function mapping for that address, the function, the source
> statement, and lifecycle ownership are **all unestablished**. Attribution
> must not be inferred from a nearby export name or from an address offset.

> **`0x4A0A4E` is a fact about an address relative to the `renderdoc.dll`
> image. It is not a function identity.**

### 11.2 Module identity — why this correction matters

Two modules named alike are loaded in the crashing process:

```
00007ffb`0aab0000 00007ffb`0c32d000  renderdoc_7ffb0aab0000   renderdoc.dll
00007ffb`a47c0000 00007ffb`a4df6000  renderdoc               renderdoc.pyd
```

The faulting frame lies in the first range. An unqualified
`renderdoc+0x4A0A4E` bound to the wrong image and disassembled to ASCII string
data, which would have produced an attribution built on a string table. The
offset is stable and correct; only the module identity had to be pinned before
it could mean anything. **This distinction changes the direction of any future
attribution and is therefore part of the frozen record.**

### 11.3 The instruction sequence is not a function conclusion

Established:

```asm
mov  rbx, qword ptr [rax]      ; rax == 0
test rbx,rbx
je   ...
```

The null check follows the dereference, so this path allows a NULL to reach the
read. That is a measured property of the instruction sequence.

**Not established, and not to be inferred:** which object `rax` should have
held, which static this is, which lifecycle, replay ownership, or upstream
responsibility. The instruction sequence carries no attribution.

### 11.4 The correct reading of the PDB result

Neither "the PDB is invalid" nor "RenderDoc has no symbols". Precisely:

> A relationship between the current PDB and the module is a fact — the
> CODEVIEW directory names GUID `{50E88A80-9646-42CB-AD98-05A8D01C46CE}`,
> age 1, and the file is present at 4.03 MB beside the 24.29 MB dll — but the
> debugger obtained **no private symbol resolution for that address**.

`Symbols loaded` from `ld` is therefore **not** equivalent to
"function attribution available". `lm` shows the module as `(export symbols)`,
not `(pdb)`.

### 11.5 Closing position

Further progress requires changing an input condition — a full non-reduced PDB
for this exact build (`Time Stamp 6a8b9bfe`, 2026-08-24), a symbolizable
RenderDoc build, or a source-level build correspondence. All are outside this
repository and outside an evidence-only authorization.

Continuing to drive cdb will not increase attribution confidence, and it
re-opens a known failure mode: nearest export name read as function identity.

Teardown fix remains **UNAUTHORIZED and NOT STARTED**. Exit-code masking,
`os._exit`, and exit-path workarounds remain forbidden. The accounting Contract
is untouched and the pipeline correctly reports `BLOCKED_INFRA / exit 3`.

## 9. 状态更新（2026-10，结论已被 §13 实测推翻）

**status: `REPRODUCED / FAULTING BYTES ESTABLISHED / PREVIOUS INSTRUCTION INTERPRETATION SUPERSEDED / ROOT CAUSE OPEN / SYMBOLIC ATTRIBUTION NOT ESTABLISHED`**

> **本节此前提出的「当前更准确的事实」已被 §13 的直接 CDB 测量推翻。**
> 本节保留仅作为错误记录。冻结记录不是证据本身；直接测量优先于既有文档结论。

本节当时声称以下三条，**三条均已被实测推翻**：

1. 「指令字节 `48 8b 18` 在故障地址 ±96 字节内出现 0 次」——
   实测：该字节序列就在 `0x4A0A4E`，即故障指令处。
2. 「指令首字节为 `0x4A0A4D`，实际字节是 `ff 50` 的间接虚调用」——
   实测：`0x4A0A4E` 处字节为 `48 8b 18`；`0x4A0A4D` 是
   `0x4A0A49` 处 `mov qword ptr [rsp+20h],rdi` 的末位立即数字节，
   **不是指令起点**。（本节未做 ±96 字节全扫描，故此处不主张该范围内
   `ff 50` 的出现次数 —— 未测量即不记录。）
3. 「故障时 vtable 指针为零」——
   实测：为零的寄存器是 `rax`；`rbx` 非空，`[rbx]` 可读且非零。

本节的 `ROOT CAUSE OPEN` 与 `SYMBOLIC ATTRIBUTION NOT ESTABLISHED`
**不受本次推翻影响**，见 §13。

按 scope decision：**未修改 RenderDoc、未启用 WER、未采集 dump、未进行代码修复。**

## 12. 只读调试器观测尝试（2026-10，无结果）

**status: `ATTEMPTED / SUPERSEDED BY §13 / HARNESS INSUFFICIENT`**

> 本节结论**已被 §13 取代**：`rbx` 与 `[rbx]` 实际已由真实 CDB 观测取得。
> 本节保留作为「自建 ctypes 观测器不足以停在该 AV 上」的 harness 记录。

范围：按 B 路径授权，仅尝试在故障时刻读取 `rbx`、`[rbx]`、`rax`、`rcx`、
`rip` 与模块上下文。**未修改** RenderDoc、worker、teardown 路径或 CI
accounting；**未修改故障形状**。

方法：**误判工具缺失** —— 仅检查 `PATH`，未检查磁盘。`cdb.exe` 实际一直存在于
`C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe`。据此错误地
改以 `ctypes` 直接调用 Windows debug API（`CreateProcess` +
`DEBUG_ONLY_THIS_PROCESS` + `WaitForDebugEvent`）自建只读观测器，子进程为
三模块最小复现集（`test_ide_ci_workflow`、`test_ide_ownership`、
`test_real_replay`）。

观测结果（事实）：

- 子进程稳定跑完 `Ran 19 tests / OK`，与无调试器时一致。
- 调试事件循环**确实在接收事件**：观测到大量 `EXCEPTION_DEBUG_EVENT`
  （code=1）。
- **自始至终未出现 `EXCEPTION_ACCESS_VIOLATION`（`0xC0000005`）**；捕获分支
  一次都未触发。

因此 **`rbx` 与 `[rbx]` 仍为未观测（NOT OBSERVED）**，本轮未取得任何故障时刻
寄存器值。

未确立（不得推断）：

- **不能**据此断定故障在调试器下不复现 —— 该结论未经验证。调试器附着会改变
  `BeingDebugged`、未处理异常过滤器与 CRT 故障处理路径；这只是**候选解释**，
  不是证据。
- 异常洪水中是否包含目标违例 —— 未判定。
- 不能从本轮推断任何关于 vtable 为零之成因的信息；第 9 节的
  `ROOT CAUSE OPEN` 不变。

工程结论：在本环境下，同类手段（同环境自建观测器、更换采集工具）已连续失败，
**边际收益低于成本**。有差异的下一通道是**真实调试器或 dump 采集器**
（WinDbg / cdb / procdump）；带符号的 dump 可同时给出 `rbx`、对象来源与
函数级归因。该路径需要安装，本环境未确认网络与管理员权限。

本节不计为根因证据，不改变任何门禁状态：pipeline 仍为
`BLOCKED_INFRA / exit 3`，teardown 修复仍 **UNAUTHORIZED and NOT STARTED**。

## 13. 故障源直接 CDB 观测（B 路径完成，2026-10）

**status: `B COMPLETE / FAULT SOURCE ESTABLISHED BY DIRECT OBSERVATION / rbx AND [rbx] EXCLUDED AS FAULT SOURCE / FUNCTION AND SOURCE ATTRIBUTION NOT ESTABLISHED / ROOT CAUSE OPEN`**

取代 §12。裁决 B 的问题**已回答**。

方法（只读）：`cdb.exe -g`，脚本文件逐行执行，符号路径
`D:\renderdoc_no_mcp\renderdoc\x64\Release\pymodules;srv*https://msdl.microsoft.com/download/symbols`，
目标为三模块最小复现集。未附加 `.ecxr`（在本机报 `0x8000FFFF`），改为在
AV 停点上直接读寄存器。**未修改** RenderDoc、worker、teardown 路径或 CI
accounting；**未修改故障形状**。

### 13.1 故障时刻寄存器（实测）

| 寄存器 | 值 | 读数 |
| --- | --- | --- |
| `RIP` | `00007ffb\`0af50a4e` | 模块基址 `00007ffb\`0aab0000`，image offset **`0x4A0A4E`** |
| `RAX` | `0000000000000000` | **为空 —— 故障解引用源** |
| `RBX` | `00007ffb\`0c1edc80` | **非空**（有效栈地址） |
| `RCX` | `00007ffb\`0c2aa495` | 有效地址 |
| `RDX` = `RDI` | `00000080\`01577dc0` | 有效地址 |
| `RSP` | `00000080\`006df770` | 有效地址 |

`[RBX]` 经 `dq @rbx L1` 实测为 `00000000\`00000001` —— **可读，值为 1，非零**。

> **裁决 B 的结论：`rbx` 非空、`[rbx]` 可读且非零；两者均不是故障源。**
> 故障源是 `rax == 0` 被解引用。

### 13.2 故障点反汇编与字节（观测记录）

```
00007ffb`0af50a3e  8b053c8d2701  mov     eax,dword ptr [rip+...]
00007ffb`0af50a44  48895c2430    mov     qword ptr [rsp+30h],rbx
00007ffb`0af50a49  48897c2420    mov     qword ptr [rsp+20h],rdi
00007ffb`0af50a4e  488b18        mov     rbx,qword ptr [rax]      <== 故障指令
00007ffb`0af50a51  4885db        test    rbx,rbx
00007ffb`0af50a54  7428          je      +0x28
```

`db` 原始字节（`db @rip-10 L26`），故障地址 `0x4A0A4E` 起：

```
00007ffb`0af50a4e  48 8b 18 48 85 db 74 28-48 8b 40 10 48 8d 3c c3  H..H..t(H.@.H.<.
```

即故障地址处字节为 **`48 8b 18`**，且 `0x4A0A4E` **就是故障指令地址**。
`0x4A0A4D` 是 `0x4A0A49` 处 `mov qword ptr [rsp+20h],rdi` 的末位立即数字节，
**不是指令起点**。

空检查（`test`/`je`）位于解引用**之后**，因此该路径允许 NULL 抵达读取 ——
这是指令序列的可测属性，非归因。

### 13.3 关于 `0x4A0A3E` 的表述边界

前置指令 `mov eax,dword ptr [rip+...]` 是一次 **32 位** 写入，因此
`0x4A0A3E` 处的这条指令执行后 `RAX` 的高 32 位被清零。这是**反汇编观察与
寄存器状态的直接事实**。

**仅止于此。** `[rip+...]` 对应哪个符号、哪个对象、哪个 static，以及它为何
为零，均**未确立**，属下一层归因，需独立授权。本节**不命名该全局量**，也
**不把它记述为「某个全局变量已被识别」**。

### 13.4 归因边界（不变）

`ln @rip` 在本地 PDB 与符号服务器路径下仍只给出**最近导出符号**
（`RENDERDOC_EndProfileRegion+0x2a6eee`），**无私有符号解析**。因此
**函数级与源码级归因仍 NOT_ESTABLISHED**；导出名不得读作函数身份（§11.1）。

栈回溯维持既有结论：AV 发生在 **CRT onexit / C++ 静态析构** 阶段
（`ucrtbase!execute_onexit_table` → `LdrShutdownProcess` → `RtlExitUserProcess`），
在测试体完成、`OK` 打印之后，主线程。

### 13.5 冻结裁决

> **B 已完成。故障源已由直接 CDB 观测定位为 `rax == 0` 对 `mov rbx,[rax]`
> 的解引用；`rbx` 及 `[rbx]` 均非故障源。函数级及更高层归因仍
> NOT_ESTABLISHED，ROOT CAUSE OPEN。**

以下**未授权**，作为后续独立授权项：追查 `[rip+...]` 对应的具体全局量、判定
所属 static、解释该值为零的原因、函数/源码级归因、teardown 修复。

`EXCEPTION_ACCESS_VIOLATION` 为 `0xC0000005`，读地址 `0x0`；故障每次复现均
落在同一 offset `0x4A0A4E`。门禁状态不变：pipeline 仍为
`BLOCKED_INFRA / exit 3`，teardown 修复仍 **UNAUTHORIZED and NOT STARTED**。
