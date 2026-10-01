# CI Crash Accounting Portability — Phase 1 Design

Date: 2026-10-01
State: **DESIGN PROPOSED / NO PRODUCTION CODE CHANGED**
Extends `3866cfe` (phase 1 investigation) and **corrects its predicate
recommendation** — see §6.

Scope: make the diagnostic harness classify abnormal termination correctly on
both platforms, without changing any gate verdict semantics.

---

## 1. Measured platform behaviour matrix

Real subprocesses only. No hand-written returncode. The same script ran on
Windows and on WSL Ubuntu 2 (python3.12), each with a gcc-compiled native NULL
dereference.

| case | Windows `returncode` | POSIX `returncode` | traceback in stderr |
| --- | ---: | ---: | --- |
| clean `exit(0)` | 0 | 0 | no |
| explicit `exit(7)` | 7 | 7 | no |
| Python traceback | 1 | 1 | **yes** |
| `os.abort()` | `0xC0000409` (3221226505) | **-6** | no |
| native AV (C NULL deref) | `0xC0000005` (3221225477) | **-11** | no |
| deliberate `exit(3221225477)` | `0xC0000005` (3221225477) | **5** | no |
| externally killed child | **1** | **-9** | no |
| `subprocess.run(timeout=…)` | raises `TimeoutExpired` | raises `TimeoutExpired` | no |

Four facts follow, and two of them invalidate what I recommended before.

**1. `code < 0` is never true on Windows.** Confirmed across clean, non-zero,
traceback, `abort`, native AV and external kill. The existing predicate cannot
fire on this platform, ever.

**2. A native AV and a deliberate `sys.exit(3221225477)` are byte-identical on
Windows** — 3221225477, no stderr either way. Exit status alone can never
establish that a crash occurred.

**3. An external kill on Windows reports plain `1`.** `taskkill /F` terminates
with exit code 1, indistinguishable from a Python exception by returncode, and
distinguishable only by the absence of a traceback. So on Windows, "killed from
outside" is largely invisible.

**4. On POSIX the exit status is masked to 8 bits**, so a deliberate
`exit(3221225477)` becomes `5`. The Windows ambiguity does not reproduce there.

## 2. `os.WIFSIGNALED` and `os.WTERMSIG` must not be used

This is the correction, and it is the most consequential measurement here.

| expression | reality |
| --- | --- |
| `os.WIFSIGNALED(7)` after `sys.exit(7)` | **True** |
| `os.WTERMSIG(7)` in that case | `7` |
| `os.WIFSIGNALED(1)` after a Python traceback | **True** |
| `os.WTERMSIG(-9)` after SIGKILL | **`119`**, not 9 |

`WIFSIGNALED` reports true for ordinary low exit codes because of how the
status word is decoded, and `WTERMSIG` masks rather than sign-extends. Using
them would classify a normal `sys.exit(7)` as "killed by signal 7" — the exact
mirror image of the Windows bug being fixed, and it would have shipped on the
strength of my own earlier recommendation.

**The only safe POSIX signal test is `returncode < 0`, with the signal number
taken as `-returncode`.** That is CPython's documented convention and it is what
the measurements agree with.

## 3. The timeout path currently records nothing

`harness.run_isolated` passes `timeout=600` and does not catch
`subprocess.TimeoutExpired`. Measured on both platforms: the exception has **no
`.returncode` attribute**, though it does carry `.stderr`. So a hung scenario
propagates out of the test as an error, the child is killed, and
`REPORT["reliability"]` receives no entry at all. Any design must therefore make
`process_returncode` optional and add a distinct termination class for it.

## 4. Proposed layered observation

Keeps the raw value, names only what the evidence supports, and never says
"crash" about an ambiguous number.

```yaml
execution_result:
    process_returncode: int | null      # verbatim; null when no code was produced
    returncode_present: bool

termination_observation:
    class: normal_exit | python_failure | nonzero_exit
         | signal_termination | native_termination_suspected
         | timeout | indeterminate

evidence:
    platform: nt | posix
    completion_sentinel_present: bool   # SCENARIO_OK seen
    traceback_present: bool
    signal_number: int | null           # posix only, = -returncode
    ntstatus: int | null                # nt only, = returncode & 0xFFFFFFFF
```

`process_returncode` is never rewritten or normalised. `ntstatus` and
`signal_number` are derived views of it, not replacements.

## 5. Classification rules, each traceable to a measured row

**POSIX** (`os.name == "posix"`)

| condition | class |
| --- | --- |
| `returncode == 0` | `normal_exit` |
| `returncode < 0` | `signal_termination`, `signal_number = -returncode` |
| `returncode > 0` and traceback present | `python_failure` |
| `returncode > 0`, no traceback | `nonzero_exit` |
| no returncode (timeout) | `timeout` |

**Windows** (`os.name == "nt"`)

| condition | class |
| --- | --- |
| `returncode == 0` | `normal_exit` |
| `(returncode & 0xFFFF0000) == 0xC0000000` | `native_termination_suspected` |
| traceback present | `python_failure` |
| otherwise | `nonzero_exit` |
| no returncode (timeout) | `timeout` |

**Unknown platform** → `indeterminate`. Never silently treated as normal.

## 6. Reporting rules

- The diagnostic may say **"abnormal termination, native suspected"**. It may
  not say "crash occurred".
- `REPORT["reliability"]` gains a per-class breakdown so a reader can see the
  basis, and `crashes` — if kept at all — is defined as the count of
  `native_termination_suspected` and documented as suspected rather than proven.
- The existing `elif "error" in err.lower() and "Traceback" in err` is replaced
  by `traceback_present`, whose marker is measured:
  `Traceback (most recent call last)`. The old test required an `"error"`
  substring anywhere in stderr, which is both case-mangled and far too weak.

## 7. What must not change

- **`assertEqual(code, 0)` stays.** It is correct and fail-closed today; §1's
  crashes were never silent, only misattributed.
- No gate verdict, exit mapping, `release_gate.py` behaviour, integration
  `INFRASTRUCTURE_FAILURE` handling, or release blocking.
- No new verdict state. This is a diagnostic report, not a gate.
- Nothing inferred about a real crash beyond what §1 measured.
- `tests/workload` stays a §5 diagnostic.

## 8. Control requirements for the implementation phase

The user's constraint — controls must not only exercise hand-built strings —
is binding, and §1 shows how easily a string-based control passes while the
platform disagrees.

Required controls, each spawning **real** subprocesses on the running platform:

1. real `exit(0)` → `normal_exit`
2. real `exit(7)` → `nonzero_exit`, **not** `signal_termination`, and on POSIX
   specifically not via `WIFSIGNALED`
3. real Python traceback → `python_failure`
4. real native AV via a compiled NULL-deref binary → on Windows
   `native_termination_suspected`, on POSIX `signal_termination` with 11
5. real external kill → on POSIX `signal_termination` with 9, on Windows
   `nonzero_exit` (because `taskkill /F` yields 1)
6. real timeout → `timeout` with `process_returncode: null`
7. the deliberate `exit(3221225477)` case must be classified
   `native_termination_suspected`, with an explicit assertion that the design
   does **not** claim a crash — this pins the ambiguity rather than hiding it

Mutation injections required: restore `code < 0`; drop the Windows NTSTATUS
branch; treat an ordinary non-zero exit as a crash; lose the traceback marker;
use `WIFSIGNALED` on POSIX.

Platform-conditional assertions must skip rather than fake the other platform.
A POSIX run of these controls is possible here through WSL Ubuntu, but a CI
runner on Windows would exercise only the Windows branch — so the POSIX branch
needs its own recorded run rather than an assumed one.

## 9. Open items this phase did not resolve

- Whether the compiled-AV fixture can be built on a CI runner without a
  toolchain. If not, control 4 needs a prebuilt binary or a different real
  abnormal-termination source, and that is a decision, not a detail.
- The Windows external-kill case is close to unobservable (§1 fact 3). Whether
  to add a sentinel-based liveness check, as `worker_manager` already does, is
  a design question beyond "fix the predicate".
- Nothing here changes what the integration teardown AV *is*; that root cause
  remains open in `TEARDOWN-CRASH-INVESTIGATION.md`.

## 10. Errors made in this phase

- **My earlier predicate recommendation was wrong.** I proposed
  `WIFSIGNALED`/`WTERMSIG` for POSIX in `3866cfe`. Measurement shows both
  misreport, and following that advice would have shipped a mirror-image bug.
  The error was recommending an API from its documentation without exercising
  it — the same observation-layer failure as the sign assertion and the
  synthetic AV that did not fault.
- **A nested PowerShell heredoc produced no output at all**, and I nearly read
  that as an environment problem. The script was written to a file and invoked
  directly instead.
