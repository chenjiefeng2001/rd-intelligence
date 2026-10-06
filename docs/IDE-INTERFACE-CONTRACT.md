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

`publish()` is called from three places: `configure()`, `dispose()`, and once
per served query. Lifecycle transitions are published outside `_config_lock` so a
slow subscriber cannot delay an ownership transfer. A failed `configure()` raises
without publishing: a capture that never became the owner is not a state anyone
should be told about.

**Queries are announced, and that was a gap rather than a design choice.** The
stream originally carried only the two lifecycle transitions, which left the
history panel with nothing to react to and a manual Refresh button -- the wrong
shape for a page whose purpose is watching a session. A long session produces
queries, not transitions.

The history endpoints are skipped inside `_remember`, in one place, rather than
at the call sites. Checking at the call sites missed the classified-error path, so
one *rejected* history read published an event that made the panel read the
history again, and a read that kept failing kept the loop running. A guard next
to the work it governs cannot be bypassed by the next call site someone adds.

**Frames are compact, and that is a correction rather than a preference.** The
frames were written with `json.dumps(indent=2)` under a single `data:` header. SSE
continues a data payload across lines only when every line repeats the prefix;
anything else is discarded, so a reader received `{` and `JSON.parse` threw. The
React client caught that error and refreshed anyway, which is why a browser
control asserting the refresh passed while the payload never arrived. Every frame
is now one line, and the control asserts the data line parses as the event that
was sent. The `resync` frame is built by hand rather than through `_frame`, so it
is covered separately -- it is the frame the clients that most need help would
receive.

A tolerant reader is still the right client: it should not tear down the page
because one frame was unreadable. But tolerance on its own is what let a broken
wire format look like a working feature, so the reader stays tolerant and the
server-side control is strict.

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

## 5. The React page owes the old page parity

The first React build dropped two controls the old page has: **Generate AI
Prompt** and **Copy prompt**. That was a functional regression wearing the
costume of a rewrite — nothing failed, because no test covered them. Both are
back, and `TestRestoredFeatures` asserts they exist *and* that the D9
availability contract still holds: copy is available when there is a prompt, not
because a diff happened, so an empty prompt cannot be copied as if it were real.

Restoring them also surfaced a second defect. The explain failure path did
`setPrompt("")` and returned, so a failed explain was **silently swallowed**. The
old page routed it through `enterSeq`, which reports the failure and then clears
the prompt. `applyPrompt()` now does both: report, then clear.

Parity is therefore a list, not an adjective:

| Old page | React page |
| --- | --- |
| `/` root | `/ui/` |
| `btnDiff`, `btnTrace`, `btnExplain`, `btnCopy`, `btnLang` | all five |
| `capture`, `cibase`, `result`, `evidence`, `prompt`, `eidscope` | all six |
| truncation banner | present, `role="alert"` |

## 6. Modernisation, and what each claim is checked by

| Change | Why | Checked by |
| --- | --- | --- |
| `AbortController` on every request | a request the user moved past is cancelled, not left running replay work nobody reads | wired to the same claim as the stale check; `api()` returns `kind:"cancelled"`, which never renders |
| `htmlFor` on every control | a placeholder is not an accessible name; it vanishes once the field has a value | every `input`/`textarea` has a label, `aria-label` or `title` |
| `aria-live="polite"` on the result | the result arrives after the click that asked for it; without it a screen reader announces nothing | attribute asserted |
| `role="alert"` on the banner | a failure that arrives after the user looked away is what an assertive region is for | attribute asserted |
| `.sr-only` label on the prompt | the textarea needs a name that is not a visible duplicate of its heading | covered by the accessible-name sweep |
| `<dl>` for term/value pairs | the relationship is real and should be announced as one | — |
| `overflow-wrap: anywhere` | long resource ids are the normal case here, not the exception | a 120-char capture name must not cause horizontal scroll |
| `flex-wrap` + `min-width: min(320px, 100%)` | the previous `min-width:340px` on every card forced a sideways scroll instead of adapting | 420px viewport does not scroll sideways |
| focus-visible outline | keyboard operation needs to be visible, not merely possible | Tab reaches a control with a non-zero outline |
| Enter in a coordinate field | a debug tool is typed into | Enter with a bad coordinate produces the parse failure |
| `prefers-color-scheme: light` | a second palette is a second set of claims | banner has a non-transparent background and a foreground that differs from it |
| `prefers-reduced-motion` | transitions are suppressed when asked for | — |
| no `dangerouslySetInnerHTML` | the strings are ours, but an innerHTML sink in a debugging tool is one nobody should have to audit later | translated prose is React elements |

One control was pinned more tightly because it was looser than it looked: the
banner-colour assertion now sets `color_scheme="dark"` explicitly. Asserting one
literal RGB while inheriting whatever scheme the browser defaults to is a test of
the default, not of the page.

## 7. Structure of the React app

The page is split, and the split is checked rather than described.

```
src/
  main.jsx                    mount only
  App.jsx                     state and orchestration
  api.js                      the client result envelope
  useEventStream.js           the SSE client
  i18n.js                     the two string tables
  components/primitives.jsx   Panel Button Field Checkbox Badge Alert
                              EmptyState Skeleton KeyValues
  panels/QueryPanel.jsx       TopBar, QueryPanel, StatusBar
  panels/EvidencePanel.jsx    evidence chips and the prompt
  views/ResultPanel.jsx       DiffView, TraceView, ResultPanel
  theme.css                   tokens, including both colour schemes
  styles.css                  the primitives
```

`tests/unit/test_ide_ui_design.py` holds the structural controls, including the
ones that stop the split from quietly becoming duplication: `main.jsx` may only
mount, `App.jsx` may not contain markup, and no panel may hold local state.

## 8. Design decisions, and the check for each

| Decision | Why | Checked by |
| --- | --- | --- |
| one `primary` filled button, and it is Diff | the page exists to compare two pixels; two filled controls is not a hierarchy | exactly one `primary` prop, and it is on the diff control |
| the result panel is elevated, the others are not | the eye should land on the answer rather than on whichever card is top-left | both shadow tokens asserted on their own rules |
| `grid-template-areas` names the focal area | the layout states what matters instead of relying on source order | areas asserted |
| skeleton, not a spinner | a spinner beside an empty panel reads as "no result" | shimmer asserted; loading and empty are separate test ids |
| hover, active and focus-visible on every control | an element that gives no sign of being touched is unproven to work | `:hover:not(:disabled)`, `:active:not(:disabled)`, and one shared focus rule naming four selectors |
| a pulsing dot for the live connection | connection state should be legible peripherally | the dot pulses, not the whole pill |
| every colour is a token | a literal hex does not follow the scheme | no hex literal in the stylesheet or in any component |
| every interaction latency comes from a motion token | feedback speed should be one decision | every `transition` rule asserted to use a token |
| animation *periods* may be literal | a spin loop is not feedback latency; moving the number would be theatre | the reduced-motion override is asserted instead |
| both palettes restate the same token names | a token defined in only one scheme makes the page unreadable in the other | set difference asserted empty |

One component bug was found by the split rather than by a test: `Badge`
destructured its props and dropped the rest, so `data-testid` never reached the
DOM and the stream badge had no handle. Component boundaries make that class of
mistake visible, which is most of the argument for having them.

## 9. Serving the bundle

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

## 10. What is not established

| Item | Status |
| --- | --- |
| A screen-reader run of either page | **NOT ESTABLISHED** — the semantics are asserted in a browser; nobody has listened to one |
| React page against a real capture with real trace data | **NOT ESTABLISHED** — the browser controls run unconfigured, so they exercise error paths |
| Keyboard operation beyond Tab and Enter | **NOT ESTABLISHED** — no arrow-key navigation of the evidence chips or the read tree |
| Long-running stream stability over hours | **NOT ESTABLISHED** — heartbeat and bounded history are unit-tested, not endurance-tested |
| Browser controls in CI | **NOT ESTABLISHED** — no browser in the CI image |
| Contrast ratios of either palette | **NOT ESTABLISHED** — colours are asserted as not-transparent, not measured against WCAG |