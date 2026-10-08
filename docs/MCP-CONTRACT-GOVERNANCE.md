# `test_mcp_contract` Governance Attribution — Investigation

Date: 2026-10-01
State: **INVESTIGATION COMPLETE / GOVERNANCE CONCLUDED**
Scope: investigation only. **No production code changed, no gate semantics
changed, no exit mapping changed, no release blocking.**

Predecessor: `afbd3fa` CLOSED / FROZEN (teardown crash, root cause open). This
workstream does not reopen it.

---

## 1. The failure, reproduced precisely

Run directly, bypassing the slow `unittest` wrapper:

```
python -m tests.workload.isolated_runner mcp_contract
```

| field | value |
| --- | --- |
| argv | `['-m', 'tests.workload.isolated_runner', 'mcp_contract']` |
| exit | `1` (`0x00000001`) |
| elapsed | ~2.2 s |
| `SCENARIO_OK` in stdout | **no** (stdout empty) |
| unittest state | failure |
| error | `AttributeError: module 'rdebug_mcp.server' has no attribute '_session_factory'` |
| site | `tests/workload/scenarios.py:122` |

Deterministic: 3 runs out of 3, byte-identical error.

Via the unittest path: `python -m unittest discover -s tests/workload -t .`
gives `Ran 10 tests`, `FAILED (failures=1)`, in ~18–21 minutes. Running the
scenario directly costs 2.2 s, so the direct path is what any future
investigation should use.

Two facts about this failure matter more than the failure itself:

- It happens **before any replay**. No capture is opened, no worker is spawned,
  no MCP tool is called. RenderDoc is not involved.
- It is a **stale reference in the test's own setup**, not a contract violation.

## 2. What the scenario actually validates

```python
valid   = {"capture": cap, "x": 320, "y": 240, "max_draws": 4}
invalid = {"capture": cap, "resource": "bogus"}
for i in range(200):
    ... server.trace_pixel(**valid)   -> payload must contain "summary"
    ... server.trace_resource(**invalid) -> payload must contain "error"
```

So the per-call assertions are **semantic/API Contract**: a valid query returns a
result body, an invalid one returns an error body. The 200-iteration loop is a
**soak / repetition** axis.

Its own framing agrees: the file is `test_workload_reliability.py`, the class is
`TestReliabilityScenarios`, the module docstring reads "Workload D/E/F/H: error
injection, capture isolation, LRU cycling, MCP contract stability", and the
scenario records itself as `record_correctness("reliability[mcp_contract]", ...)`.

**Classification: contract-shape assertions wrapped in a reliability harness.**

The intent is still expressible against today's API — both tool signatures match
what the scenario passes:

```
trace_pixel(capture, x, y, target=None, eid=None, mip=0, slice=0,
            sample=0, max_draws=16, expand_reads=True, max_writers=8) -> str
trace_resource(capture, resource, eid=None, include_other=False) -> str
```

What is obsolete is only the mechanism: it monkeypatches
`server._session_factory` and disposes `server._MANAGER`. Neither exists. The
module now holds `_WORKERS: WorkerManager`.

That change was deliberate. `src/rdebug_mcp/server.py` lines 8–14:

> M1.3: each capture is served by a dedicated worker process, one replay runtime
> per capture, instead of an in-process SessionManager … the RenderDoc in-process
> replay runtime does not safely support multiple live controllers, which
> produced silent value corruption, native hangs and 0xC0000005 (W1-R1 F-1/F-2).

## 3. Coverage: already held by two release-blocking gates

**Layer 1 — `tests_transport` (blocking, stubbed, no GPU).** Asserts the MCP
response shape, argument mapping, error propagation and telemetry:

- `test_operational_error_returned_as_json` — `"error"` in payload
- `test_mcp_arguments_reach_the_worker_unrenamed` — guards MCP → worker dispatch
- `test_worker_error_becomes_a_json_error_payload` — worker failure → JSON error
- `test_mcp_wrapper_records_result_shape` — `_safe` wrapper records shape

**Layer 2 — `tests/integration` `TestM15Matrix` (blocking, real capture, real
worker).** This is the stronger coverage, and it was executed to confirm rather
than assumed:

```
python -m unittest \
  tests.integration.test_m15_acceptance.TestM15Matrix.test_row_failure_semantics_mcp_json_body_and_query_error \
  tests.integration.test_m15_acceptance.TestM15Matrix.test_row_failure_semantics_query_error_is_observable
Ran 2 tests in 11.938s
OK
```

- `:214–220` valid call against a real capture, after `_WORKERS.dispose()` and
  recovery: `assertNotIn("error", payload)` **and** `assertIn("summary", payload)`
- `:228–229` invalid resource against a real capture: `assertIn("error", payload)`

Those are **exactly** the two halves `test_mcp_contract` asserts, at real-replay
fidelity, inside a release-blocking gate.

**Therefore: the contract-shape coverage is duplicated, and the only unique axis
is the 200× repetition.**

There is a sharper problem still. `test_m15_acceptance.py:124–129` does not
merely tolerate the migration, it **asserts the old symbols must be absent**:

```python
for gone in ("_MANAGER", "_session_factory", "_open", "_session"):
    self.assertFalse(hasattr(self.server, gone),
                     f"server.{gone} should not exist after M1.3")
```

`scenarios.py` depends on precisely two of them. So the scenario is not merely
stale — it is in direct contradiction with an assertion an existing blocking
gate already enforces.

## 4. Is the verdict stable, decidable and fail-closed?

**The harness wrapper is sound.** It asserts `code == 0` *and*
`SCENARIO_OK` in stdout. It cannot silently pass, and it cannot pass on a
scenario that crashed after printing success.

**The current failure is stable and fail-closed:** 3/3 deterministic, exit 1,
~2 s, no GPU dependency.

**But the verdict is about the wrong thing.** An `AttributeError` in the
scenario's own setup, before any MCP call, carries zero information about MCP
contract stability. The test is named for a property it does not currently test,
and it is permanently red for a reason unrelated to its name — which is the
state in which people learn to ignore a red test.

Two further defects in the surrounding instrument, found while establishing the
above. Both are independent of the MCP scenario:

**4a. Native crashes are silently uncounted on Windows.** `run_isolated` returns
`proc.returncode`, and the classifier reads:

```python
if code < 0:
    record_failure("crashes", f"{scenario}: exit {code}")
```

`code < 0` is Unix semantics. The frozen `ci_pipeline_report.json` records the
same API's value for this repository's access violation as
`process_exit_code = 3221225477` — **positive**. Therefore `code < 0` is `False`
and a native crash is **not** counted as a crash. The `elif` fallback requires
both `"error"` and `"Traceback"` in stderr, which a hard access violation does
not produce. Net effect: on Windows, native crashes in workload scenarios never
appear in `REPORT["reliability"]["crashes"]`.

This is not hypothetical for this repository, which reproducibly produces such
crashes. It is the same failure shape as the one just frozen in
`FREEZE-EXIT-ACCOUNTING`: a process-level fact dropped by a classifier that
inspects only one representation of it.

**4b. A dead intensity knob.** `harness.py` defines
`ENV_MCP_CALLS = int(os.environ.get("WORKLOAD_MCP_CALLS", "200"))` and nothing
reads it; `scenarios.py` hardcodes `range(200)`. A reviewer could believe the
soak intensity had been tuned when it had not.

## 5. Conditions it would need as a gate

- **Corpus**: `require_corpus()` skips unless `tests/workload/corpus/*.rdc`
  exists *and* `RDEBUG_RENDERDOC_PATH` is set. 14 `.rdc` are present;
  **0 are tracked in git**. Same evidence gap as the integration corpus.
- **Runtime**: post-M1.3 the path goes through `WorkerManager`, so real worker
  processes, real replay and a GPU, subject to the recycle policy
  (q250 / 128 MB / 1800 s).
- **Dependencies**: `mcp` (FastMCP) and `pydantic_settings`; importing the server
  emits `IncompleteFieldDefinitionWarning`. The `mcp` extra is pinned
  `mcp>=1.0,<2` in `pyproject.toml`: SDK 2.x renamed FastMCP to MCPServer, so an
  unbounded range resolves a transport the server cannot import -- the install
  succeeds and the first launch exits 1. Verified against 2.3.0 (fails) and
  1.30.0 (initialises, lists four tools). The bound keeps the protocol dependency
  off base installs: a plain install pulls `psutil` alone and has no `mcp` at all.
- **Accounting**: it would need its own `requires` (env / module / capture /
  capabilities) and a `min_executed` floor, and a decision about the 200× scale.
- **§5 test**: a 200-call soak is machine-dependent by nature — timing, memory,
  recycle thresholds. CI-ORCHESTRATION-CONTRACT §5's criterion is that anything
  which fails because of machine differences rather than a defect is not a gate.

## 6. Governance conclusion

**`tests/workload` remains a §5 diagnostic. `test_mcp_contract` is not promoted
to a gate.** Grounds, in order of weight:

1. **It would be a duplicate gate.** Both of its contract-shape assertions are
   already held by two release-blocking gates, and the integration gate holds
   them against real captures and real workers. Promotion would add a third,
   slower, GPU-dependent gate for coverage already held.
2. **What is genuinely unique is a soak axis, not a correctness axis.** The
   200× repetition is a reliability signal, and §5's own criterion classifies
   those as diagnostic.
3. **It cannot honestly be promoted in its current state.** It produces no MCP
   verdict at all.

Promotion would also require this test to stop contradicting
`test_m15_acceptance:124–129`, and would make a permanently-red test into a
release blocker — turning an unowned stale test into an owned stale blocker.

### Recommended follow-ups, each needing its own authorization

Not done in this round:

- **Repair or retire the scenario**, so it stops being a permanently-red unowned
  test. The intent is still expressible: point at `_WORKERS` and drop the
  in-process monkeypatch. Retiring it is also legitimate, since the coverage is
  already held elsewhere. What is not legitimate is leaving it red.
- **Fix the `code < 0` crash classification** so Windows native crashes are
  counted. A diagnostic-accuracy defect, and this repository demonstrably
  produces the crashes it cannot currently see.
- **Remove or wire up `WORKLOAD_MCP_CALLS`.**

## 7. Non-goals observed

Teardown crash not reopened. No PDB attribution. RenderDoc untouched.
`CI-ORCHESTRATION-CONTRACT §5` unchanged. The workload failure was not promoted
to a regression. Nothing was excluded to make the pipeline green. No gate
semantics, exit mapping or release blocking changed. The frozen `afbd3fa`
evidence was not touched.

## 8. Observation-layer discipline

### 8.1 Event carried over from the previous workstream

An unnecessary full enumeration of the shared scratch directory
`%LOCALAPPDATA%\Temp\opencode`. The actual deletions remained strictly scoped to
the five directories this session created; no external state was damaged and no
incorrect project conclusion resulted, so no rollback was required.

Recorded as an **observation-layer discipline event, not a project defect**.
The common factor across this event and the two earlier ones is always the same:
acting on the observation layer before verifying it.

### 8.2 Two such errors made in this round

- **Two wrong `unittest` class-name guesses**, producing `_FailedTest` load
  errors reported as `Ran 2 tests, FAILED (errors=2)`. Read as evidence for a
  moment, they were not; the correct class was `TestM15Matrix`.
- **An asserted sign.** I computed `3221225477 - 2**32` and concluded that
  Python's `subprocess` returns a negative value on Windows, making `code < 0`
  true and the crash counter functional. That was arithmetic standing in for an
  observation. The frozen pipeline report records the same API returning
  **positive** `3221225477`, so `code < 0` is false and the counter is blind on
  Windows. The defect is real; my first evidence for it was wrong, and only the
  measured artifact settled it.

Both are recorded because each would have produced a confident wrong conclusion,
and one of them inverted the finding it was used to support.
