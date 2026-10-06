---
document_role: contract
freshness_policy: living
document_living_note: >-
  Describes the query recorder, its retention bounds and its degraded modes.
  Living: the retention defaults and the stdlib-only property are asserted by
  tests/unit/test_recorder.py rather than trusted here, and this store
  reopens workstream A, which had been closed as NOT IMPLEMENTED.
---

# Query Storage Contract

## 1. Why this exists

A JSONL telemetry log answers "what happened". It cannot answer "what happened
to this pixel over four hours", because answering that means parsing every line
and then aggregating in Python. A debugging session that outlasts one terminal
window therefore became recorded but not queryable.

This store closes that gap, and it reopens workstream A. A was closed as
**NOT IMPLEMENTED** on the grounds that no query or aggregation API existed over
the opt-in JSONL. That ground is now removed, so the previously recorded "IDE
request-metrics view: NOT IMPLEMENTED" is superseded by §7 below.

## 2. Where it lives and what it may touch

| Property | Value | Enforced by |
| --- | --- | --- |
| implementation | `src/rdebug/recorder.py`, `sqlite3` | stdlib-only control |
| enabled by | `RDEBUG_STORE=<file>` | unset means no store at all |
| payloads | `RDEBUG_STORE_PAYLOADS` | off by default |
| importable from `rdebug/analysis`, `rdebug/adapter`, `rdebug/query` | **no** | `audit_boundaries.py` Rule 2.2 |
| read by | `/api/history`, `/api/history/summary`, `rdebug history` | — |
| consulted by a query | **never** | Rule 2.8 |

`sqlite3` is in the standard library. A debugging tool that people `pip install`
should not acquire a storage dependency to keep a log, so there is no
`pyproject` change and nothing new to audit at install time.

## 3. Rule 2.8, and what it forbids

Recording is not on the path of an answer. If the store is unwritable, locked,
corrupt or full, the query returns the same bytes it would have returned with no
store configured. Failures are counted in `dropped`, never raised.

Three controls exist because this is the promise the module is for, and a promise
is not a promise because a comment says so:

| Control | What it breaks |
| --- | --- |
| `test_a_broken_store_returns_instead_of_blocking` | an unwritable path |
| `test_reading_a_broken_store_also_returns_promptly` | reading a broken store |
| `test_the_lock_is_reentrant` | the deadlock described below |

The first two use a `join(timeout=...)` rather than a return-value assertion. That
is deliberate. This control was written **after** the recorder deadlocked on
exactly that path: a plain `Lock` is not re-entrant, `connection()` holds it
while opening the database, and its failure path calls `_note_drop()`, which
takes it again. The suite hung for thirty minutes instead of failing. A
degradation guarantee has to be checked for *timing*, because the failure mode is
a stuck process, not a wrong answer.

## 4. Retention

| Bound | Default | Override |
| --- | --- | --- |
| rows | 50 000 | `RDEBUG_STORE_MAX_ROWS` |
| age | 7 days | `RDEBUG_STORE_MAX_AGE` |

Applied **on write**, not on read and not on a timer. A store nobody queries
still has to stay bounded, and a background thread inside a query library is a
worse trade than a delete that runs when a row arrives.

The consequence is deliberate and worth knowing: rows that age past the bound
while a session is idle survive until the next write. For a debugging session,
where writes are frequent, that is the right end of the trade.

## 5. Reading it back

```
GET /api/history?limit=&endpoint=&x=&y=&since=&until=&failures=&payloads
GET /api/history/summary?endpoint=&since=&until=
rdebug history [--summary] [--limit N] [--x X --y Y] [--failures]
```

`rdebug history` needs **no capture**: asking what happened over a long session
must not require reopening it. With no store configured it prints
`{"enabled": false, ...}` and exits 1, which is a refusal rather than an empty
success.

Three behaviours are specified because each was a bug first:

| Behaviour | Why |
| --- | --- |
| `limit=0` yields 1 row, not the default page | `limit or 50` treated an explicit zero as unspecified, so a caller asking for nothing received fifty rows |
| pixel filters compare by value | `320,240` is a substring of `1320,2401`; and a URL stores `"320"` while a caller passes `320`, so the comparison coerces |
| `parse_qs` lists are flattened | `str(["320,240"]).split(",")` yields `"['320"` and `"240']"`, so every HTTP-recorded row silently failed every pixel filter while the unit tests — which store scalars — kept passing |

Query parameters are stored **as strings**, because that is what the URL
contained, and converted for comparison when filtering. What is stored is the
request that was actually sent, not a normalised version of it.

The last two bugs were invisible to the unit suite entirely. They were found by
pointing a browser at the running server, which is why
`TestStoredRequestShapes` now pins the shapes the wire actually produces.

## 6. What this is not

- **Not a cache.** Nothing is ever read back into a query. A store that fed
  answers could change them, which is what Rule 2.8 forbids.
- **Not a capture store.** It records observations *of* queries. It does not hold
  captures, replay state or results used for answering.
- **Not on the MCP surface.** The four MCP tools are frozen and unchanged.
  History is reachable from the IDE and the CLI only, deliberately.
- **Not telemetry replacement.** `RDEBUG_TELEMETRY` JSONL is unchanged. The store
  is queryable; the JSONL is not. Both can be on at once.

## 7. Superseded and newly established

| Item | Before | Now |
| --- | --- | --- |
| IDE request-metrics view | **NOT IMPLEMENTED** (workstream A closed) | **IMPLEMENTED** via `/api/history/summary` |
| request metrics queryable over a long session | **NOT IMPLEMENTED** | **IMPLEMENTED** |
| JSONL telemetry queryable | **NOT IMPLEMENTED** | **STILL NOT IMPLEMENTED** — the JSONL format is unchanged; the store is a separate thing |
| store size bounded | n/a | **VERIFIED**, both bounds tested |
| retention enforced without a query | n/a | **VERIFIED** |
| browser-level view of the history | n/a | **NOT IMPLEMENTED** — the endpoints exist; no UI panel reads them yet |

The last row is the honest limit: this change makes the data reachable and adds
no view for it. The React page has no history panel.