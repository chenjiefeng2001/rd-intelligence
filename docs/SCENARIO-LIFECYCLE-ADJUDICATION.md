# Scenario Lifecycle Adjudication — `scenario_mcp_contract`

Date: 2026-10-01
State: **GOVERNANCE DECISION — no code changed**
Predecessors: `3c287d7` (governance investigation), `afbd3fa` (teardown, frozen),
`3866cfe` (crash accounting portability, phase 1).

Scope: adjudication only. **`tests/workload/` untouched, `release_gate.py`
untouched, CI exit semantics untouched, M15/transport contracts untouched,
workload not admitted to gates, Windows crash classification untouched.**

---

## 1. Decision

> ## Status: `RETIRED`

Not `ACTIVE_DIAGNOSTIC`. Not `PROPOSED_GATE`.

The scenario represented a contract that two release-blocking gates already
hold, and its one candidate unique axis turned out not to be exercised at the
scale it was written for. `PROPOSED_GATE` has no supporting evidence and is
recorded here only as rejected.

## 2. Coverage matrix

| scenario assertion | held by an existing gate? | unique value? | decision |
| --- | --- | --- | --- |
| valid MCP call returns JSON containing `summary` | **Yes, twice.** `test_m15_acceptance:214-220` (real capture, real worker, after dispose + recovery) — executed, `OK`. `tests_transport/test_transport.py:128` (stub) | no | retire |
| invalid MCP call returns JSON containing `error` | **Yes, twice.** `test_m15_acceptance:228-229` (real capture). `test_transport:128` | no | retire |
| MCP → worker argument mapping unrenamed | **Yes.** `test_transport:133` | no | retire |
| worker failure → JSON error + telemetry | **Yes.** `test_error_boundary:86`, `test_observability:134` | no | retire |
| legacy MCP symbols absent after M1.3 | **Asserted, and inverted.** `test_m15_acceptance:124-129` requires `_MANAGER` / `_session_factory` **not** to exist. The scenario *depends* on them | none — it contradicts a blocking gate | retire |
| 200× repetition, MCP-shaped, real replay | no direct equivalent | **no — see §3** | retire |
| isolation of a native crash into a data point | mechanism belongs to `harness.run_isolated`, shared by all four reliability scenarios | not a property of *this* scenario | unaffected by retirement |

`tests_transport` and `tests/integration` are both `required_execution: true,
blocking: true` in `release-gates.json`.

## 3. Why the 200× axis is not unique value

The plausible argument for keeping it was "repeated MCP calls under real replay
is the only coverage of worker-recycle stability". Measured, it does not hold:

- The effective policy on this machine is `max_queries=250`,
  `max_private_memory_delta_mb=128`, `max_lifetime_s=1800`.
- The scenario performs **exactly 200 calls, all on one capture, therefore all
  on one worker**. `200 < 250`, so the query-count trigger **cannot fire by
  construction**.
- The other two triggers are unmeasured here, and no estimate is offered in
  their place. It does not matter: **the scenario only asserts response
  shape**. It never reads `_WORKERS.recycle_events`, never compares worker PIDs
  before and after. A recycle that did occur would be invisible to it.
- The recycle axis is already covered deterministically and cheaply:
  `tests/unit/test_worker_manager.py` lowers the policy to `1`, `7` and `10`
  rather than brute-forcing repetition, and `test_m15_acceptance` asserts PID
  and recycle state directly.

So the axis is both unexercised by this scenario and covered elsewhere by better
instruments. A soak whose subject it never inspects is not evidence.

## 4. Retirement record

**Why retired.** Both of its contract assertions are already held by two
release-blocking gates, one of them at real-replay fidelity. Its only candidate
unique axis is not exercised at the configured scale and is covered elsewhere by
instruments that assert the recycle state directly.

**Original failure cause, preserved verbatim.**

```
python -m tests.workload.isolated_runner mcp_contract
exit 1 (0x00000001), ~2.2s, stdout empty, no SCENARIO_OK
tests/workload/scenarios.py:122
AttributeError: module 'rdebug_mcp.server' has no attribute '_session_factory'
```

Deterministic 3/3. Via the unittest path: `Ran 10 tests`, `FAILED (failures=1)`,
~18–21 minutes.

**This is explicitly not a code regression.** The failure occurred in the
scenario's own setup, before any capture was opened, before any worker was
spawned and before any MCP tool was called. RenderDoc was not involved. The
cause is a test-fixture reference to a symbol that M1.3 deliberately removed and
that a blocking gate now actively asserts must be absent.

**History is not deleted and nothing is rewritten as passing.** The scenario
remains in the tree as a retired record until an implementation round marks it,
so that the failure and its cause stay readable.

## 5. Blast radius of this decision

- **Sibling scenarios are unaffected.** `error_injection`, `isolation` and
  `lru_cycles` use `CaptureSession` / `SessionManager` directly and never import
  `rdebug_mcp`. That is precisely why they still pass — the breakage is isolated
  to the one scenario that reached into MCP server internals.
- **The isolation mechanism is unaffected.** `harness.run_isolated` is shared by
  all four reliability scenarios.
- **No gate outcome changes.** `tests/workload` is not a gate; no
  `release-gates.json` entry, no exit mapping and no release-blocking behaviour
  is involved.
- **Nothing is excluded to reduce red.** The retirement is not a route to a
  greener pipeline, because the workload suite is not in the pipeline.

## 6. Not decided here

- **Implementing** the retirement — marking the scenario retired, removing it
  from the default reliability statistics — touches `tests/workload/`. That
  sits close to the boundary of "do not delete a test to make things green", so
  it needs its own authorization. It should carry its own control asserting the
  retirement record exists, so the scenario can be neither silently deleted nor
  silently re-enabled.
- **`code < 0` crash classification on Windows.** Separate workstream, already
  scoped in `CRASH-ACCOUNTING-PORTABILITY.md`. Deliberately not run in parallel:
  merging it here would put diagnostic semantics and scenario lifecycle in the
  same change, which is the pattern that has repeatedly produced confused
  observations.
- **`WORKLOAD_MCP_CALLS` dead knob.** Lowest priority cleanup, not started.
- **Repairing the scenario instead of retiring it** would only be justified if
  someone later defines a soak axis that the scenario actually inspects. That is
  a new proposal, not this decision.

## 7. A note on the alternative that was rejected

`A3 / PROPOSED_GATE` is rejected on the evidence, and the three questions that
would have to be answered are recorded so the rejection is auditable:

- **Which risk does it cover that a blocking gate does not?** None
  demonstrated; §2 maps every assertion to an existing blocking gate.
- **Is failure release correctness?** The 200-call axis is a soak, and CI
  ORCHESTRATION-CONTRACT §5 classifies machine-dependent signals as diagnostic.
- **Does it have a stable execution environment?** No. It needs a GPU, a
  non-versioned corpus (14 `.rdc` present, **0 tracked** in git) and the `mcp`
  dependency stack.

## 8. Non-goals observed

`release_gate.py` not modified. CI exit semantics not modified. Windows crash
classification not modified. Workload not admitted to any gate. No test deleted
to create a green result. M15 and transport contracts not modified. Frozen
`afbd3fa` evidence not touched. No production code changed in this round.

---

## 9. Implementation record — RETIRED landed

Authorized as: lifecycle governance for `tests/workload` `mcp_contract` only,
plus non-silent-recovery controls. Production code, gate contracts, CI verdicts
and MCP behaviour untouched.

### What changed

| file | change |
| --- | --- |
| `tests/workload/retired_scenarios.json` | new. Machine-readable record: owner, dated adjudication + commit, `reason=covered_by_existing_blocking_gates`, `not_a_regression` with its reason, six `replacement_coverage` entries with resolvable test ids, the reproduction command, and the preserved `last_failure` (exception, site, `exit_code: 1`, determinism) |
| `tests/workload/test_workload_reliability.py` | `test_mcp_contract` → `_retired_test_mcp_contract`, off the `test` prefix so default discovery skips it. Body kept and documented |
| `tests/unit/test_retired_scenarios.py` | new. 18 controls, in the unit gate deliberately |

`scenario_mcp_contract` stays in `scenarios.SCENARIOS`, so the original failure
remains reproducible on demand. Retirement means unreachable by default, not
gone.

### Controls

18, all passing, all in `tests/unit` — governance that nothing checks is a
comment. They enforce three properties:

- **Records are complete and honest.** Every field present and non-empty;
  `owner`, ISO date, hex commit, adjudication doc exists on disk; `reason` must
  name coverage rather than difficulty; and the record may not contain "fixed",
  "passing", "passed", "resolved", "obsolete", "not a bug" — a retired scenario
  did not start working.
- **Retirement cannot be undone silently.** The retired method is not collected
  by discovery, keeps a non-`test` name, its body still exists, and the scenario
  is still in `SCENARIOS`.
- **The coverage that justified it still exists** — the load-bearing one. Every
  named replacement is imported and resolved. If `test_m15_acceptance` were
  renamed or deleted, the retirement would silently stop being justified, and
  nothing inside `tests/workload` would notice, because the workload suite does
  not import the gates.

Plus two guards on the prohibitions: the M1.3-removed symbols are asserted still
absent from `rdebug_mcp.server`, and no gate command references `tests/workload`.

### Mutation verification — 10 injected defects, all caught

| Mutation | Caught |
| --- | --- |
| delete the retirement record outright | yes |
| drop `owner` | yes |
| rewrite `reason` to `fixed` | yes |
| claim `not_a_regression: false` | yes |
| empty the `replacement_coverage` | yes |
| point coverage at a test that does not exist | yes |
| erase the failure evidence (`exit_code: 0`) | yes |
| restore the `test` prefix, re-entering the active set | yes |
| delete the retired method body | yes |
| remove the scenario from `SCENARIOS` | yes |

### Verified end state

```
python -m unittest tests.workload.test_workload_reliability
Ran 3 tests    OK                      (was: Ran 4, FAILED failures=1)

python -m tests.workload.isolated_runner mcp_contract
exit 1, AttributeError ... _session_factory     (evidence still reproducible)

ci pipeline: BLOCKED_INFRA (exit 3, conclusion failure)
  unit                    PASS   executed=343   (325 + 18 controls)
  transport               PASS   executed=58
  integration   INFRASTRUCTURE_FAILURE executed=63
  boundary_audit          PASS
  cold_warm_equivalence   PASS
  fork_integrity          PASS
  benchmark_archive       UNKNOWN
```

Gate 1/2/3/5 PASS, Gate 4 UNKNOWN, overall `BLOCKED_INFRA` / exit 3 — **exactly
the pre-implementation state. No release verdict changed**, and nothing was
excluded to reduce red, since `tests/workload` is not in the pipeline.

### Errors made in this round

Five, all in the control or mutation layer rather than the change itself. The
pattern is unchanged from earlier phases, which is itself the finding.

- **`TestSuite` has no `.id()`.** `loadTestsFromModule` returns a suite; I
  iterated it as if it were flat.
- **An over-broad substring check.** `assertNotIn("tests/workload", json.dumps(spec))`
  failed, because `captures.cold_warm_equivalence` legitimately points at
  `tests/workload/corpus/*.rdc` — a corpus directory, not the test suite. The
  check is now scoped to gate `command` fields, and asserts the corpus path is
  *present* so the false positive cannot silently return.
- **`partition(".")` splits on the first dot.** Resolving
  `tests.integration.test_m15_acceptance.TestM15Matrix.…` produced the module
  name `tests`, after which the walk looked for a submodule that was never
  imported. Now resolves the longest importable prefix.
- **A mutation harness that deleted its own backups on the first iteration**,
  which left the manifest mutated and aborted the sweep mid-run. Rebuilt and
  re-run with backups created once.
- **A mutation aimed at the wrong file.** `SCENARIOS` lives in `scenarios.py`, not
  `test_workload_reliability.py`, so that mutation was a no-op and initially
  read as a missed control. Re-aimed and confirmed caught.

Two of these would have produced a *false PASS* — a control that cannot fail is
worse than no control, because it is trusted. The `tests_transport` import also
needed its directory on `sys.path`, since those modules do a top-level
`from test_transport import ...` and are only importable the way their own gate
runs them.
