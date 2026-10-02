# Capture Corpus Contract

Date: 2026-10-02
State: **RULED / IMPLEMENTED**
Authority: owner ruling, 2026-10-02 (G4 audit item).

## 1. Decision

```text
Capture corpus:
    ownership:      external prerequisite
    tracked:        false
    provenance:     required
    required_for:   integration replay
                    cold_warm_equivalence
                    workload replay scenarios
    absence:        INFRASTRUCTURE_FAILURE
    absence must never become: REGRESSION, PASS
```

The corpus is **not part of this repository** and is **not version
controlled**. It is supplied from outside.

## 2. Why not version controlled

Not the generic "files are large" argument. A higher-priority constraint leads:
**the source authorisation and provenance of the captures are not closed.**

The corpus consists of third-party and tool-generated artefacts. Tracking them
would create a new and unresolved set of obligations — who the source belongs
to, whether redistribution is permitted, whether they may be retained
permanently, whether licence metadata is required, and whether a hash or
provenance manifest must accompany them. `fork-exception.json` already
establishes a provenance discipline for this project; capture assets are not
ordinary test fixtures and cannot be waved through it.

Until those questions are governed separately, importing captures would convert
a **reproducibility** problem into a **compliance and asset-governance**
problem. Fixing a readiness gap must not manufacture a new boundary gap.

## 3. Why the previous state is also rejected

The corpus was present locally, ignored by git, consumed by gates, and named by
nothing. That state is the worst of the three available options, because it
produces:

- different behaviour between a fresh clone and a developer machine;
- a readiness check that can only rely on ambient environment probing;
- and, when a gate fails, no way to distinguish *corpus absent* from *RenderDoc
  unavailable* from *replay itself failing*.

That violates a principle already established here: **a missing execution
precondition must surface explicitly as `BLOCKED_INFRA`, never as an implicit
assumption.**

## 4. What readiness must report

```text
corpus:
    required:            true
    source:              external
    tracked:             false
    present:             true | false
    provenance_required: true
```

plus the existing observed values `capture_count`, `tracked_captures` and
`manifest_match`. `tracked` is a boolean claim that the corpus is *not* in
version control; it is distinct from `tracked_captures`, which is a count. A
non-zero count is a **contract violation**, not a capability.

`present` is an observation of this machine. `required`, `source`, `tracked` and
`provenance_required` are declarations, and they do not change with the machine.

## 5. Absence semantics

A gate that requires a capture and does not have one is
`INFRASTRUCTURE_FAILURE`, decided **before** the gate runs, with the reason
naming what was missing. This is already implemented in
`release_gate.check_requires` and is unchanged by this Contract; the controls
here exist to keep it that way.

Absence must never be translated into:

- `REGRESSION` — the capture did not report a content difference;
- `PASS` — nothing was verified;
- a skip — a skip is indistinguishable from a green run at the report level.

## 6. Forbidden

- Importing captures into version control under this Contract.
- Generating, synthesising or substituting captures to make a gate run. A
  substitute makes absence invisible, which is the exact failure this Contract
  exists to remove.
- Recording a corpus absence as a regression.
- Recording a corpus absence as a pass.
- Changing gate semantics, verdict vocabulary or exit-code mapping to
  accommodate the absence.

## 7. Out of scope of this document

- Acquisition method, location, or any transfer address. The corpus is supplied
  externally; this Contract names no machine path and no source.
- Redistribution rights and licence metadata. Those questions must be settled
  before any tracking decision is revisited.
- A hash or provenance manifest. `manifest_match` is already reported as an
  observation; defining a corpus manifest is separate work and is not
  authorised here.

## 8. Relationship to other open items

Deliberately independent.

- **Corpus ownership** is execution-asset governance.
- **The teardown crash** is a runtime lifetime defect. It does not depend on
  this Contract, and this Contract does not depend on resolving it.
- **RenderDoc attribution**, **teardown fix**, **release blocking** and
  **fork-exception extension** are all unaffected and unauthorised.

The pipeline will still report `BLOCKED_INFRA / exit 3` after this Contract,
for a different and more auditable reason: a declared external prerequisite
that is not present, rather than an implicit assumption that happens to hold on
one machine.

## 9. Reopen conditions

This decision is revisited only if **all** of the following are settled:

1. Redistribution rights for the capture assets.
2. Licence and attribution metadata requirements.
3. A corpus hash/provenance manifest, so a supplied corpus can be verified
   rather than merely counted.
4. An explicit owner proposal to track captures, approved as its own
   governance act.

A crash, a missing corpus, or a desire to make a gate run is not a trigger.
