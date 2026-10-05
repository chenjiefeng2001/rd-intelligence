---
document_role: contract
freshness_policy: living
document_living_note: >-
  Describes the two served front ends and the change-notification surface, both
  of which change with the UI. Living: the claim that index.html is a frozen
  fixture is checked against git on every run by
  `tests/unit/test_ide_stream.py::TestTheFrozenPageIsUntouched`, not trusted here.
---

# IDE Interface Contract

## 1. Two front ends, one server

| Path | What it is | May it change |
| --- | --- | --- |
| `/` | the original page | **no** |
| `/ui/` | the React page | yes |

`index.html` is not a UI preference. It is the **fixture** the frozen IDE controls
cut their functions out of: `test_ide_d11_request_identity` and
`test_ide_d9_explain` `extract()` `showFailure`, `showOk`, `enter`, `claim`,
`isStale`, `enterSeq`, `esc`, `api` and `statusSpan` by regex, concatenate them
with `const FAILURE_TEXT` into a standalone Node program, and run request-race
scenarios against it. `test_ide_page_parses` runs `node --check` on every
`<script>` block.

A React rewrite moves all of that into JSX, so every one of those extractions
returns empty and the request-identity scenarios stop being tested. That is the
shape of failure this repository has already been bitten by twice: not "the code
got worse" but "the check that would have noticed went missing, and it looked
green". So the page stays, reachable at the same URL, and the new one is served
beside it.

`TestTheFrozenPageIsUntouched` asks git whether the content in the index has
moved, which is the right question under `core.autocrlf=true`; comparing the
working file against `git show` would report a difference on a repository that
has not changed at all.

## 2. Change notification

`GET /api/events`, `text/event-stream`.

A stream has to be able to say "nothing changed since you looked", which is only
possible with a **revision**: a counter that increases on every observable
change. Without it, a dropped connection and an idle one look identical on the
wire, and the failure is a client that looks healthy while showing stale data.

| Property | Value |
| --- | --- |
| Snapshot | `GET /api/state` — `ready`, `capture`, `ci`, `revision` |
| Stream | named events carrying `id:`, `event:`, `data:` |
| Reconnect | `retry: 2000`, plus `Last-Event-ID` header or `?lastEventId=` |
| Heartbeat | `: heartbeat` every 15s |
| History | 256 events, then the oldest is dropped |

Two decisions carry the design.

**The stream carries changes; `/api/state` carries state.** A client reads the
snapshot and then applies events with a greater revision. Nothing infers state
from a stream alone.

**An evicted revision is reported, not papered over.** `replay_since()` returns
`None` — distinct from `[]` — when the requested revision has fallen out of the
buffer or came from another server lifetime, and the server answers `event:
resync`. An empty list means "you are current"; `None` means "I no longer have
what you missed". Handing a client a silently short list is how a debug tool ends
up confidently showing stale data.

The heartbeat is a comment line rather than a named event on purpose: it exists
to hold an idle connection open, and emitting it as an event would make every
idle minute look like a state change.

## 3. Additive by construction

`publish()` is called from exactly two places, `configure()` and `dispose()`, and
is published outside `_config_lock` so a slow subscriber cannot delay an ownership
transfer. A failed `configure()` raises without publishing: a capture that never
became the owner is not a state anyone should be told about.

A full subscriber queue raises on `put_nowait`, and that is swallowed. A
notification channel must never be able to stall a query.

No existing endpoint consults the revision, and no existing route changed
behaviour. The seven original endpoints answer exactly as before.

## 4. Browser-level evidence

`browser-level UI propagation` was recorded as **NOT ESTABLISHED**: the HTTP
semantics had been observed at a real socket but never verified as rendered.

`tests/unit/test_ide_ui_browser.py` drives an installed Chrome or Edge through
Playwright against a real server. It establishes, in a browser:

- the React page renders and the SSE client reports itself **live**
- the language toggle changes rendered text and `documentElement.lang`
- a failing query produces a **visible** banner
- that banner is **painted**, checked via computed colour
  (`rgb(232, 196, 104)`), because `is_visible()` can be satisfied by layout
  alone

That last point is the one the frozen record specifically flagged as unverified
for the old page: the DOM write was verified while its visual visibility was not.
The new page has a CSS rule for `.banner-warn`, and the colour is asserted rather
than assumed.

| Item | Status |
| --- | --- |
| The **old** page at `/` rendered in a browser | **NOT ESTABLISHED** — unchanged and no longer the surface under test |
| React page renders, SSE goes live, banner is painted | **VERIFIED** by the browser controls, on an unconfigured server |
| SSE against a **configured** capture, carrying real query results | **NOT ESTABLISHED** — the browser controls run with no capture, so they exercise error paths |
| The four-outcome envelope in the browser | **PARTIAL** — error paths verified; a successful trace render is not |
| CI runs the browser controls | **NOT ESTABLISHED** — the CI job has no browser installed, so they skip there |

## 5. Serving the bundle

`/ui/` resolves inside `static/ui/dist` and the resolved path is checked to be
inside that root. A server that concatenates a request path onto a directory
without that check serves any file the process can read, and a debug tool is
exactly the kind of program people point at a machine they do not fully trust.

Unknown deep paths fall back to the app shell rather than 404, because the
bundler would have handled client-side routing.

`static/ui/dist` is declared in `[tool.setuptools.package-data]` and checked by
`scripts/build_package.py`. Only `dist/` ships: `node_modules` is a build input,
and shipping it would add tens of megabytes of third-party code to every install.
An empty asset glob is deliberately not sufficient for the check — the shell
alone renders a page with no script in it — so at least one built asset is
required too. The asset filename is content-hashed, which is why the requirement
is a prefix rather than a literal name.

## 6. What is not established

| Item | Status |
| --- | --- |
| Accessibility of either page | **NOT ESTABLISHED** — `lang` is asserted; nothing else is |
| React page against a real capture with real trace data | **NOT ESTABLISHED** — see section 4 |
| Long-running stream stability over hours | **NOT ESTABLISHED** — heartbeat and bounded history are unit-tested, not endurance-tested |
| Browser controls in CI | **NOT ESTABLISHED** — no browser in the CI image |