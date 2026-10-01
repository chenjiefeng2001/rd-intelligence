# Scope Decision — Upstream RenderDoc Ownership

Date: 2026-10-01
State: **RECOMMENDATION PRODUCED / DECISION RESERVED TO THE OWNER**
Scope: governance only. **No symbols fetched, no code changed, no pipeline
verdict changed, no workaround proposed.**

Question answered: *if full symbols or source become available and a defect
inside RenderDoc is confirmed, where does fix responsibility lie?*

Not answered here: which function is wrong, how to fix it, whether to patch, or
whether to bypass the destructor.

---

## 1. The question is conditional, and the condition is not met

Attribution is `NOT_ESTABLISHED`. Nothing in the current evidence establishes
that RenderDoc is at fault at all. `PDB-ATTRIBUTION-RESULT.md` §5 records the
alternatives honestly: a null `rax` during module teardown may originate in
RenderDoc, in a driver, or in state our own usage left behind.

So the ownership question is **preceded** by the attribution question. Deciding
it now is legitimate as forward policy — which is how it is framed — but no
present action follows from it.

## 2. What the repository's own governance already says

This is the part that changes the shape of the answer. The option list was
framed as "in scope / not in scope", but the repository already contains an
enforced third position.

**A modification mechanism exists and is declared.**
`fork-exception.json` carries `n3-headless-capture-trigger`, authorising one
specific change: `renderdoc/core/core.cpp`, symbol
`RenderDoc::ShouldTriggerCapture`, include block only, with provenance in
`rdebug-validation` capture metadata and `not_a_replay_change: true`.

**`replay` is an excluded surface.**
`excluded_surfaces: ["replay", "driver", "serialise", "mcp", "ai",
"semantic_graph", "indexing"]`.

**The exception does not generalise.**
`scope_note`: *"This exception authorises exactly the modification described
above and nothing else. It does not carry forward to any future patch."*

**And the boundary is machine-enforced, in both directions.**
`scripts/audit_fork_integrity.py` states the rule as: the set of tracked
modifications and the set of declared exceptions must agree **exactly, in both
directions**. Its four hard failures include

- **F1** a tracked modification that no declaration covers,
- **F4** a modification landing outside its declared file or symbol scope, or
  **touching a surface the exception excludes**.

`fork_integrity` is a **blocking, `required_execution: true`** gate.

## 3. Consequence

A teardown fix, if attribution ever landed in the replay subsystem, would land
in a **declared excluded surface of a blocking gate**. It is therefore not
merely "out of scope" in the sense of being undesirable — it is **structurally
excluded**, and adopting it would require an explicit amendment to the exclusion
list, which is a governance act with a named cost: a new declared exception,
provenance in capture metadata, and a narrowed blast radius.

Nor could it be done quietly. `audit_fork_integrity` compares the modification
set against the declaration set in both directions and reads blast radius from
`git diff -U0` hunk headers, so a patch landing in `replay` would fail F1 and F4
and turn the overall verdict to `FAIL_REGRESSION`. That is the enforcement
working, not an obstacle to route around.

Separately, a change made in a sibling checkout is not versioned, reviewable or
CI-visible as part of this project. Its history would not exist here.

## 4. Recommendation

**Split the question, because the two halves have different answers.**

| half | recommendation | basis |
| --- | --- | --- |
| **Reporting upstream** | **In scope** (Option A) | Producing a bug report needs no modification, no symbols beyond what a reporter would gather, and no governance amendment. It is also the only path that can resolve §1. |
| **Modifying the fork** | **Out of scope** (Option B) | Not a preference. `replay` is an excluded surface of a blocking gate, and `scope_note` forbids carry-forward. |

This is more precise than either pure option. Option A as written implies the
fix can land here once attribution completes; it cannot, without amending an
enforced declaration first. Option B as written implies upstream reporting is
also unavailable; it is not.

**The excluded middle state is rejected, and is now enforced.** Making the exit
code zero by wrapper, masking or `os._exit` would:
- hide a process failure the accounting was built to make visible,
- convert `BLOCKED_INFRA` into an appearance of `PASS`, and
- contradict the two-facts rule frozen in `FREEZE-EXIT-ACCOUNTING`.

No control would need to be written to catch it: `execution_clean` is derived
from the process exit, so a masked exit is visible in the report by
construction.

## 5. What would change this recommendation

- Attribution landing **outside** the excluded surfaces would move the question,
  and would need a fresh scope decision rather than an amendment.
- An upstream fix or a validated alternative RenderDoc build would make
  `BLOCKED_INFRA` resolvable by a route already supported: the module is located
  through `RDEBUG_RENDERDOC_PATH`, so pinning a different build needs no code
  change here.
- A deliberate decision to amend the exclusion list would be legitimate, but it
  must be taken as its own governance act with its own justification, not
  inferred from a crash.

## 6. Decision record

| option | owner decision |
| --- | --- |
| Report upstream | *pending* |
| Modify the fork | *pending* |
| Amend the `replay` exclusion | *pending, and not recommended* |

The recommendation above is evidence-based and is offered as such. The decision
itself is the owner's, and nothing in this repository should be changed on the
strength of the recommendation alone.

## 7. Non-goals observed

No symbols fetched. No code changed in this repository or in the RenderDoc fork.
No pipeline verdict changed; it remains `BLOCKED_INFRA / exit 3`, which is
correct. No workaround proposed, implemented or implied. No exit-path change. No
attribution reopened. The frozen evidence at `afbd3fa`, `ddec0a1` and
`cb35249` is untouched.
