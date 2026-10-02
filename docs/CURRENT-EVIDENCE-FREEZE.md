---
document_role: evidence_record
freshness_policy: point_in_time
as_of_commit: 8679553
document_point_in_time_note: >-
  本文档是冻结证据，不追随 HEAD。其中的测量结果（如 unit 计数）
  属于某一时点，按裁决不做自动数值校验；身份事实与语义事实仍受控。
---
# CURRENT EVIDENCE FREEZE

冻结日期：2026-10-02（前一版 2026-09-29，基线 `ed59113`；本日两次刷新，
前一刷新基线为 `a81600e`）
baseline_commit: b17fa11
baseline_drift: 1
冻结点 commit：`a898381`（102 commits）

`baseline_drift` 是本文档自陈的陈旧度，容许上界 5。它**不做等值断言**：写入
本文档的那个提交本身就是下一个提交，任何要求「声明值 == 实际值」的规则在提交
落地瞬间即失效。允许滞后 1 个提交，不允许低报陈旧度，超过上界则控制失败。
覆盖仓库：`rd-intelligence`（`rdebug-validation` 冻结物**本轮只读未复验**，见下）

> **本版与上一版的差异来源**：审计（`docs/AUDIT-2026-10-02.md`）发现本文件与
> `STATUS.md` 均停留在 `ed59113`，落后本轮全部工作。刷新时**只写本轮实测事实**；
> 凡本轮未复验者一律显式标注，不沿用旧值充当新证据。

```text
CURRENT EVIDENCE FREEZE
──────────────────────────────────────────────
§2.1 fork integrity      COMPLIANT WITH DECLARED EXCEPTION
  └ core.cpp +32 tracked ── 仍存在，1 tracked / 1 declared，
                              provenance 绑定、被 F1–F4 强制
  └ audit_fork_integrity exit 0（本轮实测）
  └ git status --porcelain 仍**非空**（2 行），本冻结不宣称其为空
  └ ✅ 已接线为 blocking 门禁（§4 门 5），非「无人运行则不阻止任何事」
14 frozen artifacts      14/14 hash MATCH（本轮实测）
  └ 验证机制 = pipeline_readiness._probe_corpus 的 manifest_match
§4 automation            RESOLVED WITH OBSERVED CONSEQUENCE (A2) → 门禁已接线并可运行
context_eid             FIXED / VERIFIED（real capture confirmation 仍 pending）
CI gate verdict (§4.1)   DEFINED / FROZEN
G1 / G2 verdicts         COMPLETE / VERIFIED
§4 门 1 unit             IMPLEMENTED / blocking / PASS 370→387
§4 门 1 transport        IMPLEMENTED / blocking / PASS 58
§4 门 1 integration      IMPLEMENTED / blocking / INFRASTRUCTURE_FAILURE 63
                                       (process exit 3221225477)
§4 门 2 boundary_audit   IMPLEMENTED / blocking / PASS 18/18 + 1 deviation
§4 门 3 cold_warm_equivalence
                         IMPLEMENTED / blocking / PASS（bounded coverage）
§4 门 4 benchmark_archive
                         PROCESS_ONLY / not blocking / UNKNOWN（Gate 4）
§4 门 5 fork_integrity   IMPLEMENTED / blocking / PASS（audit exit 0）
Pipeline Phase 1         COMPLETE / FROZEN
  overall               BLOCKED_INFRA / exit 3 / failure   ← 本轮由 exit 4 变更
Pipeline readiness      COMPLETE / VERIFIED / FROZEN
Execution accounting    COMPLETE / VERIFIED / FROZEN
Teardown crash          REPRODUCED / LOCATION ESTABLISHED / ROOT CAUSE OPEN
  module                renderdoc.dll（非 renderdoc.pyd）
  fault                 mov rbx,[rax]; rax==0; c0000005
  function attribution  NOT_ESTABLISHED（PDB 未提供该地址私有符号）
Termination evidence    COMPLETE / VERIFIED / FROZEN
  classification        跨平台实测（Windows + WSL Ubuntu）
  crash claim           恒不成立（is_crash 恒 False）
workload mcp_contract   RETIRED（covered_by_existing_blocking_gates）
Gate 4 (§4.4)            PROCESS_ONLY / UNKNOWN
release blocking         NOT AUTHORIZED
CI configuration wiring  NOT AUTHORIZED（.github/workflows/ci.yml 仅为声明）
runner environment       已建立可探测模型；**从未在真缺能力机器上执行**
capture distribution     NOT ESTABLISHED（0 tracked .rdc）
shader reflection       CONTRACT DEFINED
reflection catch        DEFERRED / defensive
D6                      MEASURED / NO REGRESSION
D4                      DEFER
D7                      OPEN
N3-05B                  NOT AUTHORIZED
F-N3-1                  NOT AUTHORIZED
RenderDoc 归属 scope     RULED / FROZEN
  upstream report       ACCEPTED as future path（仅证据包，不声称归因）
  fork modification     NOT AUTHORIZED
  replay exclusion      NOT AUTHORIZED to amend
──────────────────────────────────────────────
```

## Checkpoint 事实（2026-10-02 实测）

| 项 | 值 |
| --- | --- |
| commits | 86（`a81600e`） |
| 工作树 | clean |
| unit | **370 OK**（上版 130；本轮新增 119 项控制） |
| transport | 58 OK |
| integration | 63 tests OK，**但 process exit 3221225477 → INFRASTRUCTURE_FAILURE** |
| audit | 18/18 + 1 recorded deviation |
| workload 全量 | **16 tests OK / exit 0**（上版为 10 tests 含 1 失败） |
| ruff | clean |
| fork | 1 tracked / 1 declared；`audit_fork_integrity` exit 0 |
| 14 冻结物 | **14/14 hash MATCH（本轮实测）** |

## 本轮两处必须点明的状态变化

**1. `overall` 由 `NEEDS_REVIEW / exit 4 / neutral` 变为
`BLOCKED_INFRA / exit 3 / failure`。**

这不是回归，而是 execution accounting 修复后的**正确结果**：integration
完成全部 63 项测试后无法干净退出，accounting 同行并列保留
`tests_executed 63 / tests_failed 0 / test_result OK / process_exit_code
3221225477`，并据此判为基础设施失败而非通过。修复前该行被记为 `PASS`。

**2. `integration` 由「63 OK」变为「63 OK 且 INFRASTRUCTURE_FAILURE」。**

旧表述只记录了测试结果，未记录进程退出事实。两者都成立，缺一不可。

## 本轮已闭环的新增项

| workstream | 冻结文档 | 控制 |
| --- | --- | ---: |
| Pipeline readiness | `FREEZE-PIPELINE-READINESS-2026-10-01.md` | 47 |
| Execution accounting | `FREEZE-EXIT-ACCOUNTING-2026-10-01.md` | 27 |
| Scenario 生命周期（RETIRED） | `SCENARIO-LIFECYCLE-ADJUDICATION.md` | 18 |
| Termination evidence | `FREEZE-TERMINATION-EVIDENCE-2026-10-01.md` | 34 |
| RenderDoc 归属 scope | `SCOPE-DECISION-RENDERDOC-OWNERSHIP.md` | — |

前三项与 termination 的控制均位于 **unit gate 内受强制**；termination 的
真实子进程层（7 项）不在任何门禁内，故另有 3 项控制断言其仍存在。

## 保持生效的 scope decision（为何现在不开启）

| 项 | 不开启的理由 |
| --- | --- |
| **Release blocking** | teardown 缺陷未解；启用后 required gate 每次通过测试却无法干净退出，将**永久阻断**。这是前置条件，不是改进项。 |
| **CI configuration 接线** | `.github/workflows/ci.yml` 仅为声明，**无 git remote，从未执行**。全部门禁证据来自单机。 |
| **修改 RenderDoc fork** | `replay` 是 blocking 门禁 `fork_integrity` 的**排除面**，且现有 exception 明文「不向后延续」。若归因落在 replay，正确序列是重开 scope decision → 提交治理变更 → 修改 exception contract → 重新证明 blast radius。 |
| **修订 replay 排除列表** | 唯一可得链条是 `crash → suspect replay → 扩大 exception`，不被允许。可接受链条尚未到达。 |
| **F-N3-1** | ExecuteIndirect 已被正式降为 extra coverage sample 并移出 frozen acceptance scope。重开将直接突破现有 scope decision。 |
| **N3-05B** | N3-05A 已完成 frozen acceptance；05B 属 renderer/generalization 扩展，**不是当前 correctness blocker**。 |
| **D7 / D5** | 属「增加证据能力」，当前**没有新的 correctness defect 在等待**。D7 另受实际硬件矩阵限制，单机无法推导 cross-machine claim。 |

## 🔁 Reopen trigger（保留）

> **未来一旦获得真实 reflection failure，立即重开 §2.11；
> 不需要因为「catch 看起来可疑」提前修改。**

`DESIGN_SPEC.md` §2.11.4 的三项重开条件不变：真实 capture 使路径可达（已满足
S2.1）、在该 capture 上复现失败、证明 consumer 响应。

Teardown 归因的重开条件（`PDB-ATTRIBUTION-RESULT.md` §6.4）：该构建的完整非裁剪
PDB、可符号化的 RenderDoc build、或源码级对应关系。

## 尚未解决、且本轮**新发现**的缺口

| # | 缺口 | 性质 |
| --- | --- | --- |
| G3 | workload 全量 discover 已于本轮复验并关闭（16 OK） | ✅ 已关闭 |
| G4 | 0 tracked `.rdc` → `integration` / `cold_warm` / workload **无法仅凭仓库复现** | 结构性证据缺口 |
| G5 | 无 remote，`ci.yml` 从未执行；全部门禁证据为单机 | 结构性证据缺口 |
| G6 | `overall` 当前永不可能 PASS（Gate 4 `PROCESS_ONLY` + integration INFRA，两个独立的 by-design 原因） | 结构性 |
| G7 | teardown 缺陷使 release blocking 今日不可用 | 依赖 |

G4 尚待裁决：语料应纳入版本控制，还是被正式声明为外部前置条件。目前可复现性
**无处被断言**，且静默依赖本机状态。

## 下一次开启工作时

**单独选择一个 workstream，并从它自己的 Contract / evidence question 开始**，
而不是自动从 OPEN 状态表中挑一个继续。

## 本冻结**不**授权

```
Release blocking 接线 / 放行门禁配置              NOT AUTHORIZED
CI workflow 实际执行（需 remote）                NOT AUTHORIZED
修改 RenderDoc fork / 修订 replay 排除面          NOT AUTHORIZED
teardown 修复（exit masking / os._exit / wrapper） NOT AUTHORIZED
修改 reflection catch 行为 / 新增 error flag      NOT AUTHORIZED
修改 semantic schema / diff logic / error contract NOT AUTHORIZED
新增语料 / 语料入版本控制                        NOT DECIDED
O3（构造失败条件以证明该 catch）                  NOT AUTHORIZED
重开 F-N3-1                                       NOT AUTHORIZED（突破 scope decision）
N3-05B / D5 / D7                                 NOT AUTHORIZED
把 workload 纳入 gate                             RULED AGAINST
把 diagnostic 结论升级为 crash 断言               RULED AGAINST（is_crash 恒 False）
```
