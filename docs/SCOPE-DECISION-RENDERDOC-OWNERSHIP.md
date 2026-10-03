# Scope Decision — Upstream RenderDoc Ownership

Date: 2026-10-01
State: **RULED / FROZEN**
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

Ruled by the owner, 2026-10-01.

| question | ruling |
| --- | --- |
| Upstream reporting | **ACCEPTED as a future path** — evidence report only, attribution not claimed |
| Modifying the fork | **NOT AUTHORIZED** |
| Amending the `replay` exclusion | **NOT AUTHORIZED** |

### 6.1 Upstream reporting — what it may and may not contain

Accepted because it is the only route that changes no governance boundary here
and does not presume responsibility.

**May contain.** The reproducible crash; faulting module `renderdoc.dll`; phase
as CRT `onexit` / static destruction; the instruction-level NULL read; minimal
trigger conditions; the negative controls; and an explicit statement that
attribution is not established.

**Must avoid.** A title or description asserting a RenderDoc replay teardown
defect. No evidence supports that. The accurate framing is of the shape:

> Deterministic NULL-read access violation in renderdoc.dll during process
> finalization after successful test execution

**Must not claim.** That a RenderDoc subsystem caused it; a replay ownership
defect; a specific static destructor bug; or that it is or is not a driver
issue. `ddec0a1` froze RenderDoc, driver and usage-lifecycle as all
unexcluded.

The report's role is therefore a **request for symbolisation / locating
assistance**, not the submission of an already-attributed defect.

### 6.2 Why modifying the fork is refused — constraint conflict, not preference

If attribution later shows `fault ∈ replay surface`, the correct action is not a
quiet patch but:

```
reopen the scope decision -> submit a governance change -> amend the
exception contract -> re-prove blast radius
```

Until that sequence is followed, `audit_fork_integrity` failing is the
governance behaving as designed, not an obstacle.

### 6.3 Why amending the exclusion is not started

Amending the exclusion list requires answering why a new replay modification
surface is worth changing an already-frozen safety boundary. That cannot be
answered now, because the only chain available would be

```
crash -> suspect replay -> widen the replay exception
```

which is not permitted. The admissible chain is

```
attribution established -> confirmed that a fix must live in the replay
surface -> alternatives evaluated -> scope revision proposed
```

which has not been reached.

### 6.4 Trigger for reopening

- Attribution established outside the current assumptions.
- Upstream provides a fix or a replacement build.
- An explicit governance proposal, taken as its own act rather than inferred
  from a crash.

### 6.4.1 Trigger status against current evidence (2026-10, read-only)

| 触发条件 | 状态 | 依据 |
| --- | --- | --- |
| 归因确立于当前假设之外 | **未达成，且已测定受阻** | 故障形状已直接确证（`mov rbx,[rax]` @ `0x4A0A4E`，`RAX == 0`），但**函数/源码归因未确立**；且本地 PDB 与故障映像**不同构建**（`6A8B9BFE` vs `6A8B9BA9`），已**测定不可行**。见 `PDB-ATTRIBUTION-RESULT.md` §5 |
| 上游提供修复或替换构建 | **外部输入，未获得** | 无 |
| 显式治理提案，作为其自身行为而非从崩溃推断 | **唯一当前可内部推进的路径** | 不依赖归因，也不依赖上游 |

§6.3 的可接受链条以「归因确立」为首项，因此在触发条件 1 / 2 下**均被阻断**。
条件 3 是一条独立路径：它必须以自身理由成立，**不得**由崩溃反推。

### 6.5 当前不存在任何可执行的修复路径（枚举证明）

| 可能的修复路线 | 当前可行性 | 依据 |
| --- | --- | --- |
| 在 RenderDoc 内修缺陷 | **不可执行** | 需要知道改哪里；归因未确立且已测定不可行 → 即使授权也写不出正确修复 |
| 退出码掩码 / `os._exit` / 子进程 wrapper / 改退出路径 | **明文禁止** | teardown 调查 §5、§11.5；掩盖缺陷即等于把数字刷绿而不移除缺陷 |
| 把门禁排除 / 把缺失当作通过 | **禁止** | `CAPTURE-CORPUS-CONTRACT.md` §6；execution accounting Contract 已冻结 |
| 扩大 replay 排除面 | **链条不被允许** | §6.3：唯一可得链条是 `crash -> suspect replay -> widen the replay exception` |

结论：**scope 重开目前没有可执行内容**。这不是「尚未推进」，而是**在现有材料下
无处可推进**；记录这一点比制造选项更诚实。

### 6.6 若走触发条件 3，blast radius 需重证的范围（草案，不实施）

当前实测基线（只读 audit，`exit 0`）：fork = `D:\renderdoc_no_mcp\renderdoc`，
声明 = `fork-exception.json`，**PASS：1 项 tracked 改动 / 1 项声明例外**
（`n3-headless-capture-trigger` → `renderdoc/core/core.cpp`）；F1–F4 均 not present。
工作树实际为 2 项（`M renderdoc/core/core.cpp`、未跟踪的
`docs/code_completion_report.md`）。

若任一修复落在 RenderDoc，则需重证：

1. `DESIGN_SPEC.md` §2.1.1 的**允许文件/作用域**与**排除面**判定（`replay` 在排除
   列表内）。
2. `audit_fork_integrity` 重新通过，且 F1（未声明改动）、F2（声明但缺失）、
   F3（provenance 绑定）、F4（越出 blast radius）四项**均需成立**。
3. 新的例外条目需绑定 provenance；既有例外**不向后延续**，不得被新例外隐式覆盖。
4. tracked / declared 计数从当前 **1 / 1** 发生位移，且位移必须被显式声明而非
   被审计吸收。

以上为**重证范围草案**，不构成提案，也不授权任何改动。

### 6.7 使其可执行所需的外部输入

- 与 **`6A8B9BA9`** 构建匹配的 PDB，或可符号化的 RenderDoc 构建（关闭归因缺口）；
- 或上游直接提供修复 / 替换构建。

二者均**不在本仓库内**，也不是本工作流可自行产生的。

### 6.8 Isolation note

The two pre-existing N3 patch entries in the sibling RenderDoc checkout are
outside this decision. They are not part of this round's diff, audit or
CI-visible state, and are not used to support or refute anything above.


## 7. Non-goals observed

No symbols fetched. No code changed in this repository or in the RenderDoc fork.
No pipeline verdict changed; it remains `BLOCKED_INFRA / exit 3`, which is
correct. No workaround proposed, implemented or implied. No exit-path change. No
attribution reopened. The frozen evidence at `afbd3fa`, `ddec0a1` and
`cb35249` is untouched.
