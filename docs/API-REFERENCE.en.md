# API Reference (English)

Code truth: `src/rdebug_ide/app.py`, `src/rdebug_mcp/server.py`, `src/rdebug/cli.py`.
**This document describes interfaces that already exist. It adds and changes no
contract.**

The Chinese edition of this file is `API-REFERENCE.md`. Both are kept in step by
`tests/unit/test_api_reference_parity.py`, which fails if their endpoint lists,
parameter tables or status-code semantics diverge.

## Evidence levels

Every statement below is tagged with how it is known, so that design intent is
never presented as verified behaviour:

| Tag | Meaning |
| --- | --- |
| **[CODE]** | Read directly from the implementation |
| **[P9a]** | Observed over a real IDE HTTP round trip (`CURRENT-EVIDENCE-FREEZE.md`) |
| **[UNIT]** | Covered by a unit or contract test |
| **[NOT ESTABLISHED]** | Not established; must not be treated as holding |

> **Overall limit**: `browser-level UI propagation = NOT_ESTABLISHED`.
> The HTTP semantics below were observed at a real HTTP boundary but have never
> been verified as rendered in a browser.

---

## 1. The three interface layers

| Layer | Entry point | Consumer | State |
| --- | --- | --- | --- |
| **Semantic API v1** | `rdebug.analysis.*` | everything above | **FROZEN** |
| **MCP transport** | `rdebug-mcp` (4 tools) | external LLM / agent | **FROZEN** |
| **IDE HTTP** | `rdebug-ide` (11 endpoints) | humans / scripts | see below |

**[CODE]** The layering is enforced by `scripts/audit_boundaries.py`:
Rule 2.1 forbids Stable Core from depending on a transport, and **Rule 2.2
forbids `openai`, `anthropic`, `httpx` and `import requests` anywhere in
`rdebug`, `rdebug_mcp` or `rdebug_ide`.**

> **Consequence**: this tool surface holds no model and calls no model. The LLM
> is always an **external agent** that fetches data through an MCP tool call.
> `Generate AI Prompt` only **produces prompt text**; it does not execute AI
> (see section 2.6).

---

## 2. IDE HTTP API

`rdebug-ide <capture> [--port N] [--baseline B] [--rd-path P]`, bound to
`127.0.0.1` only. **[CODE]** Every `/api/*` response is
`application/json; charset=utf-8`; `/` and `/index.html` are
`text/html; charset=utf-8`.

### 2.1 Endpoint summary

| Endpoint | Parameters | Forwards to | Notes |
| --- | --- | --- | --- |
| `/api/info` | — | — | stable |
| `/api/trace` | `x`, `y`, `max_draws`, `eid` | `trace_pixel` | stable |
| `/api/diff` | `a`, `b`, `deep` | `diff_pixel` | stable |
| `/api/resource` | `id`, `eid` | `trace_resource` | stable |
| `/api/explain` | `a`, `b`, `deep` | `diff_pixel` | stable |
| `/api/ci` | — | `ci_check` | stable |
| `/api/stats` | — | — | **resource ownership, not request metrics** |
| `/api/history` | `limit`, `endpoint`, `x`, `y`, `since`, `until`, `failures`, `payloads` | — | only when `RDEBUG_STORE` is set |
| `/api/history/summary` | `endpoint`, `since`, `until` | — | same |
| `/api/state` | — | — | stable; the `revision` counter |
| `/api/events` | `lastEventId` | — | `text/event-stream`, not JSON; section 2.12 |

### 2.2 `/api/info`

**[CODE]** Returns `{"capture": <str|None>, "ci": <bool>, "ready": <bool>}`.
When `ready` is false every query fails with
`RDebugError("IDE capture is not configured; call configure()")`. **[P9a]**

### 2.3 `/api/trace`

| Parameter | Required | Type | Default | Meaning |
| --- | --- | --- | --- | --- |
| `x`, `y` | yes | int | — | pixel coordinates |
| `max_draws` | no | int >= 1 | **16** (library default `MAX_DRAWS_DEFAULT`) | analysis scope |
| `eid` | no | int or empty | empty means the default event | event context |

**[CODE]** Top-level response keys: `edges`, `nodes`, `resourceFlows`, `summary`.
`summary` carries `contextEventId`, `analyzedDraws`, `truncatedDraws`,
`modificationCount`, `totalWriteEvents`, `writeEventCount`, `finalValue`,
`target`, `readsEnumerable`, `evidence`. **[P9a]**

**[P9a]** `contextEventId` sits **inside `summary`**.

### 2.4 `/api/diff`

| Parameter | Required | Type | Meaning |
| --- | --- | --- | --- |
| `a`, `b` | yes | `"x,y"` | the two pixels |
| `deep` | no | `1` / `0` / `true` / `false` | equivalence class, default false |

**[CODE]** `deep` accepts exactly those four values; anything else is a `400`.
**[P9a]** `deep=1` and `deep=true` produce byte-identical bodies, and `deep=1`
differs from `deep=0` by 1359 bytes, which shows the parameter **has an effect**
rather than being ignored.

**[CODE]** **This endpoint does not accept `eid`.** `diff_pixel` has no
`context_eid` parameter and always uses `session.last_draw_event_id()`.
**[P9a]** `diff?eid=abc` and the same request without `eid` return
byte-identical bodies — the event id is ignored rather than rejected.

### 2.5 `/api/resource`

| Parameter | Required | Type | Meaning |
| --- | --- | --- | --- |
| `id` | yes | `ResourceId::<digits>` | resource identifier |
| `eid` | no | int or empty | event context |

**[CODE]** Top-level response keys: `contextEventId`, `resource`, `readers`,
`writers`, `other`, `evidence`, `summary`. **[P9a]**

> **[P9a] Shape inconsistency (structural observation, not a defect)**
> `/api/trace` places `contextEventId` inside `summary`; `/api/resource` places
> it at the **top level**. A client that reads it uniformly from `summary` gets
> **`undefined`** on the resource side.
> There is currently **no shared cross-endpoint response-shape contract**, so
> this is not classified as a defect; it remains a trap for whoever writes the
> client.

### 2.6 `/api/explain`

**[CODE]** Takes the same parameters as `/api/diff` (`a`, `b`, `deep`) and also
calls `diff_pixel` internally. Returns `{"prompt": <str>, "evidenceIds": [...]}`.

> **This endpoint calls no model.** `prompt` is assembled as a pure string by
> `explain_prompt()` and contains model-facing instructions such as
> `You are explaining a GPU pixel diff. Use ONLY the facts below.` The model is
> supplied by the agent on the user's side. **[CODE]**
> Because the underlying call is `diff_pixel`, **this endpoint does not accept
> `eid` either**. **[P9a]**

### 2.7 `/api/ci`

**[CODE]** Without `--baseline` it returns `{"enabled": false}`. With a baseline
it returns `{"enabled": true, "status": "pass"|..., "captureHashMatch": <bool>,
"failures": [...]}`.

### 2.8 `/api/stats`

**[CODE]** Returns:

```json
{"sessions": {"count": 1, "paths": ["A.rdc"], "recycles": 0, "unkillable": []},
 "telemetry": false}
```

Every field comes from the **WorkerManager registry** and expresses resource
ownership and recycling. **[UNIT]**
`tests_transport/test_ide_app.py::test_stats_reports_the_owner_and_recycles`
fixes the "one owner, not one per request" semantics.

> **This endpoint provides no call counts, no latency and no error
> classification.** Request metrics exist only as **opt-in JSONL telemetry**
> (written when `RDEBUG_TELEMETRY` names a file; append-only, with **no query or
> aggregation API**). The IDE front end **does not call this endpoint**.
> The IDE front end **does not call this endpoint**: `/api/stats` expresses resource ownership, not request metrics. **A request-metrics view is now provided by `/api/history` and `/api/history/summary`** (see 2.11), and exists only when `RDEBUG_STORE` is set.

### 2.9 Error and status-code semantics

**[CODE]** The mapping below is transcribed from `route()`:

| Condition | Status | Body |
| --- | --- | --- |
| unknown endpoint | **404** | `{"error", "path"}` |
| worker returns a **classified** error (has `error` and has `kind`) | **400** | `{"error", "kind", "tool"?}` |
| raises `RDebugError` | **400** | `{"error"}` plus `"kind"` when present |
| raises `KeyError` / `IndexError` / `ValueError` / `TypeError` | **400** | `{"error": "invalid request parameters: ...", "endpoint"}` |
| **worker returns an unclassified error** (has `error`, **no `kind`**) | **200** | `{"error", "tool"}` |
| otherwise | **200** | the result payload |

> **[P9a] Critical: HTTP status alone is not a sufficient error discriminator.**
> An **unclassified** worker error returns **200 with an error body**. **[P9a]**
> Measured: `/api/resource?id=<absent id>` returns **200** with
> `unknown resource id ...`.
>
> **The correct client contract is the conjunction of three things**:
> `status` + `body` shape / `error` field + `kind` when present.
> The frozen `index.html` `api()` checks both `r.ok` and `body.error`, which is
> consistent with this, and **no regression was found**.
>
> This is recorded as an **open design question**, not a defect: deciding
> otherwise requires answering whether unclassified worker errors should map to
> 4xx/5xx at all.

### 2.10 Scope of event context (`eid`)

**[CODE] + [P9a]**

| Endpoint | Affected by `eid` | Evidence |
| --- | --- | --- |
| `/api/trace` | **yes** | `eid=11` gives `ctx=11`, `eid=12` gives `ctx=12`, `eid=1` gives `ctx=1` |
| `/api/resource` | **yes** | same, at top-level `contextEventId` |
| `/api/diff` | **no** | the underlying call has no `context_eid` parameter |
| `/api/explain` | **no** | the underlying call is `diff_pixel` |

**Default behaviour** **[P9a]**: with no `eid`, `contextEventId` equals
`last_draw_event_id`.

**Format validation** **[CODE]**: `_eid_param` decides **format only**
(`^-?\d+$`; empty means not supplied). A malformed value raises
`QueryError(kind="bad_request")` and returns **400**. **Legality** is decided
by action-tree membership — **[P9a]** an illegal event returns **400** with
`not an event in this capture`.

> **[P9a] Important: the set of legal events is sparse and must not be inferred
> from the range quoted in the error message.** One capture measured
> `valid_event_ids = [1, 2, 11, 12]` while the message reads `events 1..12`.
> **Eight event ids inside the quoted range do not exist**; querying them always
> yields `bad_request`. A front end must not validate against that range.

---

---

## 2.11 Query history (`/api/history`)

**[CODE]** Requires `RDEBUG_STORE` to name a database file. When it is unset the
response is `{"enabled": false}` with an empty `observations` list -- the store is
never created silently and no data is implied.

**[CODE]** Response body:

```json
{"enabled": true,
 "store": {"recorded": 4, "dropped": 0, "rows": 4, "path": "...", "payloads": false},
 "observations": [{"id": 4, "ts": 1791262090.14, "transport": "ide",
                   "endpoint": "/api/trace", "ok": true, "status": 200,
                   "latency_ms": 12.5, "query": {"x": "320", "y": "240"},
                   "summary": {...}, "payload": null}]}
```

| Parameter | Meaning |
| --- | --- |
| `limit` | default 50, maximum 1000. **`limit=0` yields the smallest useful page (1 row)** rather than being treated as unspecified and returning the default page |
| `x`, `y` | only requests asking about that pixel. **Matched by value**: `320,240` does not match `1320,2401` |
| `endpoint` | exact endpoint match |
| `since`, `until` | unix timestamp window |
| `failures` | failures only |
| `payloads` | include full response bodies (off by default; whether they were written is decided by `RDEBUG_STORE_PAYLOADS`) |

**[CODE]** `/api/history/summary` returns aggregates: request count, failure count,
mean and max latency, a per-endpoint breakdown, the most frequent errors, and how
many records were dropped.

> **[CODE] The load-bearing property**: `/api/history` reads a file the recorder
> wrote and is **not on the query path**, so it cannot affect any query result
> (DESIGN_SPEC 2.8: telemetry must be best-effort and must not change query
> behaviour). The history endpoints are themselves **not recorded**, because
> looking at the history must not grow it.
>
> **[CODE]** Query parameters are stored as strings, because that is what a URL
> contains, and converted for comparison when filtering. The distinction is
> deliberate: what gets stored is the request that was actually sent.

## 2.12 Event stream (`/api/events`)

`GET /api/events` returns `text/event-stream; charset=utf-8` and **stays open** --
it is the one endpoint that does not return JSON. `GET /api/state` returns
`{ready, capture, ci, revision}`.

A frame is `id:` / `event:` / `data:`, with the `data:` payload as **compact
single-line JSON**.

> **[CODE]** The payload has to be one line. SSE continues a data payload across
> lines only when every line repeats the `data:` prefix and unprefixed lines are
> discarded, so indented JSON arrives as `{` and makes `JSON.parse` throw.

| Event | `detail` | Sent when |
| --- | --- | --- |
| `hello` | `null` | on connect with an empty backlog, carrying `state` and `revision` |
| `configured` | the capture path | `configure()` succeeded |
| `disposed` | `null` | `dispose()` |
| `query` | `endpoint`, `ok`, `status`, `latencyMs`, `recorded` | **once per served query**; `recorded` is whether **that row itself** was stored |
| `resync` | `null` | the gap predates the buffer, or the revision belongs to an earlier server lifetime |

The `query` event came later: the stream carried only the two lifecycle
transitions, and a long session produces queries, which left the history panel
with a manual refresh button. The `/api/history*` endpoints **do not announce
themselves** -- otherwise a rejected history read would make the panel read the
history again, fail, and announce once more.

Clients should coalesce `query` events: a diff issues a second request for the
prompt, so refreshing per event turns the observer into load.

`recorded` is the return value of the call that wrote that row, **not** the
recorder's cumulative drop counter. It was once expressed as the counter: after
any single write failure -- a store pointed at a directory that has since been
removed is enough -- every later event was marked unrecorded, including the rows
that were written. A log that lies about its own storage is worse than no log.

**Reconnect semantics.** `retry: 2000` is sent up front. The buffer keeps the
most recent **256** events and drops the oldest past that. A client passes the
revision it last saw as the `Last-Event-ID` header or a `lastEventId` parameter:
absent gets `hello`, still covered replays the difference, and a **gap older than
the buffer gets `resync`**, at which point the client must fall back to a full
`/api/state` snapshot rather than treat the gap as "you are current". A
`: heartbeat` comment line every 15 idle seconds keeps the connection alive; it
is not an event and should refresh no UI.

`revision` increases on every **observable** change, a query included.

## 3. MCP Transport

**[CODE]** `rdebug-mcp` exposes **exactly four tools**, fixed by
`TransportInvariants`. The `workers.py` comment records that this surface is
"what an LLM sees".

| Tool | Parameters |
| --- | --- |
| `trace_pixel` | `capture, x, y, target, eid, mip, slice, sample, max_draws, expand_reads, max_writers` |
| `trace_resource` | `capture, resource, eid, include_other` |
| `debug_pixel` | `capture, x, y, target, eid, primitive, sample, view, max_steps, include_disassembly` |
| `diff_pixel` | `capture, a_x, a_y, b_x, b_y, max_draws, include_shader_values, expand_reads` |

**In common** **[CODE]**: three accept `eid`; **`diff_pixel` does not** — the
same asymmetry as the HTTP side.

**Meaning of `max_draws` / `max_writers`** **[CODE]**, quoted from the tool
docstring:

> clamped to the server-side ceilings; a caller asking for more is capped rather
> than refused, so the limit is a guarantee about cost and not a new failure mode
> for existing callers.

That is, **an over-limit request is truncated rather than refused** — the same
honesty principle as `truncatedDraws` in section 2.3.

**Difference between IDE and MCP** **[CODE]**: `ci_check` is Stable Core but is
**not** on the MCP tool surface; `workers.py` L37-52 records that making it an op
previously produced `unknown tool`.

---

## 4. CLI

**[CODE]** 16 subcommands. Each also takes `--rd-path` (the CLI form of
`RDEBUG_RENDERDOC_PATH`).

| Subcommand | `--eid` | Its own main parameters |
| --- | --- | --- |
| `info` | — | — |
| `events` | — | `--limit` `--name` `--min-eid` `--max-eid` |
| `draws` | — | `--limit` `--name` `--min-eid` `--max-eid` |
| `resources` | — | `--limit` `--name` |
| `textures` | — | `--limit` |
| `buffers` | — | `--limit` |
| `usage` | — | `--resource!` |
| `pipeline` | **required** | `--eid!` |
| `pixel-history` | optional | `--x!` `--y!` `--target!` `--mip` `--slice` `--sample` `--eid` |
| `trace-pixel` | optional | `--x!` `--y!` `--max-draws` `--max-writers` `--target` `--mip` `--slice` `--sample` `--eid` `--no-expand-reads` |
| `trace-resource` | optional | `--resource!` `--include-other` `--eid` |
| `debug-pixel` | optional | `--x!` `--y!` `--target` `--primitive` `--sample` `--view` `--max-steps` `--no-disassembly` `--eid` |
| `diff-pixel` | **none** | `--a!` `--b!` `--include-shader-values` `--max-draws` `--no-expand-reads` |
| `ci-record` | — | `--spec!` `-o!` |
| `ci-check` | — | `--baseline!` `--tolerance` `--ignore-capture-hash` |
| `history` | — | `--limit` `--endpoint` `--x` `--y` `--since` `--until` `--failures` `--payloads` `--summary` |

(`!` means required)

**Where `--eid` is available** **[CODE]**: `pipeline` (**required**),
`pixel-history`, `trace-pixel`, `trace-resource`, `debug-pixel`.
**`diff-pixel` has no `--eid`**, matching section 2.4, because `diff_pixel` has
no such parameter. `usage` also does **not** take `--eid`; its scope is a
resource rather than an event.

---

## 5. Known interface traps

All of the following are recorded from measurement, and are listed so that a
client implementation avoids them:

| # | Trap | Basis |
| --- | --- | --- |
| 1 | HTTP 200 can carry an error body (unclassified errors) | [P9a] |
| 2 | `contextEventId` is inside `summary` for trace and at top level for resource | [P9a] |
| 3 | `eid` affects trace / resource only; diff and explain ignore it | [P9a] |
| 4 | The `events 1..12` in an error message is **not** the legal event set | [P9a] |
| 5 | At the `max_draws` truncation boundary the body may differ by **1 byte**; read `truncatedDraws` rather than comparing lengths | [P9a] |
| 6 | MCP `max_draws` / `max_writers` are **capped, not refused** | [CODE] |
| 7 | `deep=` (empty) is dropped by `parse_qs` and means "not supplied", defaulting to false | [P9a] |
| 8 | `/api/stats` is **not** a request-metrics endpoint | [CODE][UNIT] |

---

## 6. Not established

| Item | Status |
| --- | --- |
| Browser-level UI propagation | **NOT ESTABLISHED** |
| Visual visibility of the failure banner (`.banner` / `.banner-warn` have **no CSS rule**) | **NOT ESTABLISHED** (the DOM write is VERIFIED) |
| Clean shutdown / execution of `dispose()` | **NOT ESTABLISHED** (a limit of the probe) |
| History panel rendering a successful result from a real capture | **VERIFIED** — a browser control configures a real capture and asserts the panel and the evidence chain render real observations |
| Model invocation from the tool side | **NOT AUTHORIZED** (violates Rule 2.2 / DESIGN_SPEC MUST-NOT) |
| A shared cross-endpoint response-shape contract | **does not exist** — which is why the difference in 2.5 is not a defect |

---

## 7. Related documents

| Topic | Document |
| --- | --- |
| Design specification (MUST / MUST-NOT) | `DESIGN_SPEC.md` |
| Event context contract | `F12-CONTEXT-EID-CONTRACT.md` |
| MCP governance | `MCP-CONTRACT-GOVERNANCE.md` |
| HTTP boundary evidence | `CURRENT-EVIDENCE-FREEZE.md` |
| Capabilities and boundaries | `CAPABILITIES-AND-BOUNDARIES-2026-10.md` |
| UI readiness audit (11 defects) | `P0-P1-UX-READINESS.md` |