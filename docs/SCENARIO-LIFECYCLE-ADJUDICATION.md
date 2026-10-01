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
