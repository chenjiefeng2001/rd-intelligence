---
document_role: evidence_record
freshness_policy: point_in_time
as_of_commit: 2c6079e
document_point_in_time_note: >-
  本文档是冻结证据，不追随 HEAD。其中的测量结果（如 unit 计数）
  属于某一时点，按裁决不做自动数值校验；身份事实与语义事实仍受控。
---
# CURRENT EVIDENCE FREEZE

冻结日期：2026-10-02（前一版 2026-09-29，基线 `ed59113`；本日两次刷新，
前一刷新基线为 `a81600e`）
baseline_commit: 9a4f48e
baseline_drift: 0

`baseline_drift` 是本文档自陈的陈旧度。**刷新节奏为 milestone** ——
即已授权工作流完成并冻结、实现状态改变、或 OPEN 项得到裁决时才刷新；
普通实现或文档修正不触发（裁决 F4，见
`docs/DOCUMENT-CLASSIFICATION-CONTRACT.md` §9.2）。

因此本文档的声明值在两次刷新之间**必然落后于**实际值，这是预期状态。
两条可强制的规则：

* **不得高报** —— 声明值不得高于实际值。声称比实际更新，会让读者把陈旧
  事实当作当前事实。
* **有界** —— 实际陈旧不得超过 **19 commits**。

19 不是「永远正确」，而是由实测刷新间隔分布
（`[1,1,1,2,1,1,3,3,3,2,2,1,19,9,1,1,3]`，最大 19）校准出的初始窗口。
节奏若改变则重新校准，**不得为消除报警而调阈值**。

「声明值 == 实际值」不可强制：写入本文档的那个提交本身推进 HEAD，任何等值规则
在落地瞬间即失效。
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
Teardown crash          REPRODUCED / FAULTING BYTES ESTABLISHED
  previous interp       SUPERSEDED -- see TEARDOWN-CRASH-INVESTIGATION 13
  faulting instruction  mov rbx, qword ptr [rax]  (48 8b 18)
  instruction start     0x4A0A4E  (runtime-measured fault address)
  faulting register     RAX == 0 at the fault; it is the dereferenced pointer
  rbx / [rbx]           RBX = 00007ffb`0c1edc80 (non-null);
                         [rbx] = 0x1, readable -- EXCLUDED as fault source
  prior byte claim      SUPERSEDED -- "ff 50 virtual call / vtable pointer zero"
                         refuted by runtime measurement (TEARDOWN 9 and 13)
  root cause            OPEN -- which global [rip+...] is, which static owns
                         it, and why it is zero are all unestablished
  module                renderdoc.dll（非 renderdoc.pyd）
  access                read of address 0 (c0000005)
  function attribution  NOT_ESTABLISHED（PDB 未提供该地址私有符号）
Termination evidence    COMPLETE / VERIFIED / FROZEN
   Report schema owner.   IMPLEMENTED / VERIFIED  (commit 2bb188e)
     direction             contract 6.1 <-> pipeline report, both directions
     field split            diagnosis fields follow the contract; naming follows
                            the implementation. Section 6.2's invariants depend
                            only on executed/attempted/required_execution/state,
                            so no gate semantics moved
     report schema          rdebug-ci-pipeline-report /2 -> /3, produced by a
                            real run (7/7 gate rows carry all five fields)
     history preserved     release-gates /1-/6 and ci-pipeline /2-/4 all
                            present; append-only control added after this round
                            truncated the history it was extending
     open by decision      evidence_ref, duration_s -- removing a contractual
                            requirement is a relaxation, not a cleanup
   Lint execution          COMPLETE / VERIFIED / FROZEN  (commit 2c6079e)
     direction             ruff as a precondition of the existing unit gate
     gate count            7 — unchanged; lint is not an eighth gate
     spec schema           release-gates /5 -> /6 (gate sub-records only)
     mapping               0 -> PASS; 1 -> REGRESSION; other -> INFRA
     availability probe    required; `python -m ruff` exits 1 when absent,
                           which is also ruff's 'violations found' code
     open by decision      noqa permanent approver; expiry auto-check
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
| Lint execution | `LINT-EXECUTION-CONTRACT.md` | 19 |
| Report schema ownership | `REPORT-SCHEMA-OWNERSHIP.md` | 9 |

前三项与 termination 的控制均位于 **unit gate 内受强制**；termination 的
真实子进程层（7 项）不在任何门禁内，故另有 3 项控制断言其仍存在。

## Lint execution 的验收记录（真实 pipeline 运行）

commit `2c6079e`，worktree clean，7 gates。

向**仅由 unit 门执行**的文件（`tests/unit/test_pixel_diff.py`）注入一条真实
`UP031` 违规，其余不动：

```
baseline    exit 3 / BLOCKED_INFRA    unit PASS 434
            integration INFRASTRUCTURE_FAILURE 63 (process_exit 3221225477)
            accounting_consistent True / 0 条不一致

violation   exit 2 / FAIL_REGRESSION  unit REGRESSION  executed=0  exit=None
            integration INFRASTRUCTURE_FAILURE 63 (process_exit 3221225477)
            accounting_consistent True / 0 条不一致

restored    exit 3 / BLOCKED_INFRA    unit PASS 434
```

**7/7 断言通过**：

| # | 断言 | 结果 |
| --- | --- | --- |
| 1 | `unit` == `REGRESSION` | ✅ |
| 2 | `integration` 仍为 `INFRASTRUCTURE_FAILURE` | ✅ |
| 3 | 总体 == `FAIL_REGRESSION` | ✅ |
| 4 | `exit == 2` | ✅ |
| 5 | accounting 未报假不一致 | ✅ |
| 6 | unit 未执行测试（`executed == 0`） | ✅ |
| 7 | lint 子记录保留独立 outcome | ✅ |

**`exit=None` 是刻意的。** unit 的进程从未运行，把 lint 的 exit 1 填进
unit 的 process exit 会凭空制造一个不存在的进程事实，并让 accounting 报出
「非零退出但裁决未承认」这一并不存在的矛盾。

**`unit.lint` 在 PASS 路径上为 `null` 是预期结构**，不是「lint 未运行」：
只有前置失败短路时才写入子记录。

**第一次验收注入的是 `scripts/cold_warm_gate.py`，即 `cold_warm_equivalence`
门自己的脚本**，于是该门一并失败，accounting 报出的不一致**是真实的**而非
误报。那次失败属于**验收构造错误**，不作为实现缺陷记录。

**本轮冻结不改变 pipeline verdict。** `overall` 仍为 `BLOCKED_INFRA / exit 3`，
成因**仍然只有** integration 的 RenderDoc native teardown `0xC0000005`。
lint 完整通过，未改写、未解决、也未掩盖该问题。

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

## 当前阻塞边界（2026-10；「双重边界」）

**这是当前证据的结论，不是进度落后。** 技术路径已耗尽；治理与外部输入成为前置条件。

| 项 | 状态 | 阻塞类型 |
| --- | --- | --- |
| teardown | **OPEN / BLOCKED_BY_ATTRIBUTION** | 无可执行修复路径 |
| attribution（函数级） | **OPEN / BLOCKED_BY_EXTERNAL_INPUT** | 本地 PDB 属 `6A8B9BFE`，故障映像为 `6A8B9BA9`，**已测定不可行** |
| R2 / Layer B | **OPEN / BLOCKED_BY_EXTERNAL_DETERMINISM_EVIDENCE** | 需外部提供 O1 重复生成确定性证据 |
| release blocking | **OPEN / NOT AUTHORIZED** | 现启用会**永久阻断** CI |
| RenderDoc fork 修复 | **OPEN / NOT_EXECUTABLE UNDER CURRENT EVIDENCE** | 归因不可得 → 无法写出正确修复 |

**以上均为 OPEN，不是 CLOSED。** 开放项可以已被充分测定，却仍未满足关闭条件；把
「已解释为什么不能推进」写成「问题已解决」是错误记录。

### 明确禁止的绕过方式

不得通过退出码掩码、子进程 wrapper、`os._exit`、排除门禁、扩大 replay 排除面
来绕过上述边界。

### 重新开启本工作流所需的事件（任一）

1. 与 **`6A8B9BA9`** 完全匹配的 PDB / 可符号化构建进入 → 重新进入 attribution；
   第一步不是改代码，而是重跑 `fault → function → source → ownership →
   permitted modification scope`，链条闭合才产生修复可执行性。
2. 上游修复或替换 RenderDoc 构建进入 → 重新进入修复验证。
3. O1 确定性证据进入 → Layer B 具备评估前提。
4. 出现一份**独立于 teardown 崩溃推断**的正式治理提案 → 可决定是否改变治理边界。

在四者皆未发生前，**不得**把 `teardown crash → 怀疑 replay → 扩大 replay 排除面`
当作新的证据链 —— 该链已被明确排除。

## P9a / P9b 分装与 P9a Contract（已接受，未执行）

P9 拆为两个**成本结构完全不同**的部分，不得合并：

| | P9a：HTTP Boundary | P9b：Browser Rendering |
| --- | --- | --- |
| 依赖 | **现有依赖即可** | **需新增 Playwright**（未授权） |
| 能证明 | 真实 status / body / kind 端到端 | 页面执行、DOM、CSS、时序、可见性 |
| 不能证明 | **任何视觉主张** | — |

### P9a 证据问题（Contract ACCEPTED，待授权执行）

| ID | 证据问题 | 目标 |
| --- | --- | --- |
| Q1a | IDE 页面及其静态资源能否通过真实 HTTP 完整取得 | **必须证明** |
| Q1b | 页面 JavaScript 是否在真实浏览器中执行并建立交互 | **属于 P9b** |
| Q2 | `bad_request` 是否真实经过 HTTP → 400 → JSON body | **必须证明** |
| Q3 | API / transport / malformed failure 是否真实形成对应 JSON | **必须证明** |
| Q4 | 合法空结果是否仍被当作成功结果 | **必须证明** |
| Q5 | `deep=true/false` 是否真实经过 HTTP 边界保持语义 | **可证明** |
| Q6 | `max_draws` 是否真实经过 HTTP 边界 | **可证明** |
| Q7 | `eid` 对 Trace/Resource 的范围是否真实保持；Diff/Explain 不带 eid | **必须证明** |
| Q8 | 实际 capture + RenderDoc replay 能否支撑至少一个真实 IDE query | **建议证明** |

**Q1 必须拆为 Q1a / Q1b。** 用 HTTP 客户端冒充浏览器来回答「页面能否执行」，
会把浏览器证据域偷渡进可用依赖的工作流。

### P9a 明确不回答

* CSS 是否让 banner 醒目
* `#result` 是否视觉上清晰
* button 是否真的可点击
* stale response 在真实 browser event loop 中的行为
* loading / disabled / focus / keyboard 行为
* 人是否能快速理解结果

上述全部留给 P9b / P10。

### P9a 执行约束（来自 Track A 已冻结的根因）

Q8 是 P9a 中唯一会打开真实 capture 的操作。Track A 已确认根因是
**不可重复的 shutdown 使次次初始化失效**，且 RenderDoc 不允许一个进程内两个 replay runtime。
因此：

* P9a 必须在**隔离进程**中运行，不得与任何其他打开 capture 的进程并发；
* corpus 是共享资源，并发访问会引入与本轮无关的失败；
* 本条约束不修改任何冻结代码，只约束**如何运行**。

### 可行性事实（已只读确认）

| 项 | 状态 |
| --- | --- |
| `renderdoc` 模块 | **可导入**（`renderdoc\\x64\\Release\\pymodules\\renderdoc.pyd`，需加入 path） |
| 真实 capture | **存在**（`tests/workload/corpus/*.rdc`） |
| HTTP 客户端 | `requests` / `httpx` **可用** |
| 浏览器自动化 | **playwright / selenium 均未安装** |

### 发现：无对应 CSS（记录，本阶段不处置）

`showFailure()` 写入 `<div class="banner banner-warn">`，但样式表中**不存在** `.banner`
或 `.banner-warn` 规则；`#result` 带 `class="muted"`。trace 截断横幅使用同样的两个 class。

此处**严格区分**：

| 结论 | 状态 |
| --- | --- |
| 失败横幅存在于 DOM | **VERIFIED**（P2） |
| 失败横幅对人可见且可辨识 | **NOT_ESTABLISHED** |
| D2 截断横幅的可见性 | **NOT_ESTABLISHED**（DOM presence VERIFIED） |

CSS 缺失本身不能仅凭静态检查定性为 UX defect，因浏览器实际渲染尚未观察。
**P9 不修正**：若为使验证通过而临时补 CSS，将把验证工作流变成实现修改工作流，
破坏 P2/P3 冻结边界。可见性结论留给 P9b / P10。

## Q8 Gating Probe — PASS（仅 Q8，Q1a–Q7 未执行）

隔离进程、单 capture、无 IDE HTTP server、无浏览器、未安装 Playwright、
未修改任何冻结代码。前置条件已核验：**无并发持有 `.rdc` 的进程**（0 个）。

| # | 步骤 | 结果 |
| --- | --- | --- |
| 1 | 加载 `renderdoc`（通过 `RDEBUG_RENDERDOC_PATH`） | **loaded** |
| 2 | 打开 `w00001_frame11.rdc` | **opened** |
| 3 | replay 初始化（隐式于构造函数） | `initialise_epoch=1`, `live_sessions=1` |
| 4 | 低风险语义操作：绘制枚举（`pixel_diff`/`pixel_trace` 的首个调用） | `last_draw_event_id=11`, `draw_rows=1`, `valid_event_ids=4` |
| 5 | 显式关闭 + `shutdown_replay()` | **clean**，进程退出码 **0** |

语义操作选择理由：绘制枚举与 `pixel_diff` / `pixel_trace` 的首个调用是同一个，
因此它确实需要 replay runtime，能区分「文件可打开」与「replay 可用」，
而不触碰更重的操作。

### Q8 带出的一个意外确认：合法 eid 是稀疏的

```
valid_event_ids = 4
valid 范围 = [1, 12]
```

`core.py` 的错误消息写的是 `events 1..12`。但合法值只有 **4 个**——**区间是连续的，
合法集合是稀疏的**。

这也就是为什么 P3-EID 不得从错误文本推导范围：若 UI 按 `1..12` 校验，
会放行 **8 个不存在的 event**（静默错误答案），同时拒绝任何位于 `1..12` 之外的合法 event。
**P3 当时的选择被实际数据证实**。

### Q8 PASS 不意味着什么（边界保持）

* **不意味着 Track A `verified repair` 已建立**。Acceptance 3/4 因 CDB 同名模块寻址限制而未直接观察的
  gap **完全不受影响**。
* Q8 只证明：**当前这个隔离进程、这个 capture、这个最小 replay 操作，在当前环境能够工作**。
* 本 capture 仅 `draw_rows=1`，较薄；它证明了可用性，**未证明任何需要更复杂 replay 操作的能力**（如 `pixel_history`、shader 取值）。

### 本轮进程中我的两个错误

1. 首次探测调用了不存在的 `CaptureSession.open()`（实际是 `__init__` + context manager）——探测脚本错，非 Q8 failure。
2. 隔离性检查我写成了「无 python 进程」，而约束的正确表述是「无并发**打开 capture** 的进程」。
   实际核验按正确口径重做，结果为 0，前置条件成立。

## Q8b Representative Semantic-Query Probe — PASS

隔离进程、单 capture (`w00001_frame11.rdc`)、无 HTTP server、无浏览器、未修改任何冻结代码。
前置条件：无并发持有 `.rdc` 的进程（0）。坐标采用 **IDE 自身默认值**
A=(320,240)、B=(10,10)，资源 id 由只读枚举取得。结果经 `to_json()` 校验——
即 IDE worker 在返回前实际用到的序列化路径。

| 查询 | 结果 | 证据 |
| --- | --- | --- |
| `trace_pixel` | **PASS** | 6 edges；summary 含 `truncatedDraws` / `contextEventId` / `modificationCount` |
| `diff_pixel` | **PASS** | 6 layers，`comparison="different"` |
| `trace_resource` | **PASS** | keys: `readers` / `writers` / `other` / `evidence` / `summary` / `contextEventId` |

关闭干净，进程退出码 **0**。

### 实际数据定义了 P3 的两个假设

**1. D8 的 resource ID 格式**——实际枚举得到：

    ResourceId::1000000000000000182

完全匹配 `canonicalResourceId()` 的 `^ResourceId::\d+$`。该纯函数在 P2-D 被提出为可行为
Contract，目前已由真实 replay 数据证实。

**2. 合法 eid 稀疏**（Q8 已录宗）——`valid_event_ids=4` 但范围 `[1,12]`。

### 这一轮我的探测脚本结错三次（均非产品缺陷）

三次失败的全部是我的探测脚本而非 capture 能力，且若不查证就会形成严重的假结论：

| # | 错误 | 若未发现会得出的错误结论 |
| --- | --- | --- |
| 1 | `diff_pixel` 返回 `DiffResult` 包装，我按 dict 检查 | “Diff 查询无法完成” |
| 2 | 资源 id 属性名猜错，查询**根未执行** | “Resource 查询无法完成” |
| 3 | `to_json()` 返回 **字符串**，未 `json.loads` | “返回结构不合法” |

**最危险的是第 4 次探查才显现的邻近错误**：若直接对 `DiffResult` 调 `to_json()`，
`sanitize()` 会 `return str(value)`，产生字符串——很容易得出「IDE 的 diff 路径返回字符串而非 diff 对象」
这个**严重但完全虚假**的结论。查证后才发现 worker 的 `_df` 先调 `.to_dict()`，
产品路径完好。

**新原则（已记录）**：探测必须镜像**产品实际的组合**，而不是各分析函数。
直接调 `diff_pixel` 而不调 worker 封装，就是在探测一个产品不使用的组合。

### Q8b PASS 不意味着什么

* **不意味着 Track A `verified repair` 已建立**；Acceptance 3/4 的 CDB 同名模块寻址 gap 不受影响。
* 本 capture 仅 `draw_rows=1`。三类查询可完成，**但仅在这个薄 capture 上**；未证明更复杂场景。
* 未执行 `pixel_history`（按授权不为覆盖度而扩展）。
* Q1a–Q7 仍未授权。

## Q1a HTTP 页面取证 — RETRIEVAL PASS，CLEAN SHUTDOWN NOT_ESTABLISHED

隔离进程启动**真实 IDE**（`python -m rdebug_ide.app <capture> --port`，即 production 路径）。
前后置均核验：无并发持有 `.rdc` 的进程（0 → 0）。
无浏览器、无 JS 执行、未修改任何代码。

### 取证证据（PASS）

| path | status | Content-Type | bytes | 与磁盘字节一致 | 未截断 |
| --- | --- | --- | --- | --- | --- |
| `/` | **200** | `text/html; charset=utf-8` | 16968 | **YES** | doctype + `</html>` 完整 |
| `/index.html` | **200** | `text/html; charset=utf-8` | 16968 | **YES** | 同上 |

另：`sanitize`/UTF-8 解码成功，`<script>` 块完整。页面由服务端每次从磁盁现读，
因此**字节一致性**是本次可得的最强完整性证据。

### 静态资源集合 = 单一页面（观察，非假设）

```
<link>      0        <script src>  0        <img>  0        css url()  0
```

`static/` 目录仅有 `index.html`。页面**完全自包**，无任何外部引用。
因此 Q1a 的「页面及其实际引用的静态资源」归结为**单一页面**，
且 Q1b（浏览器执行）不依赖任何额外网络拉取。

**`Content-Length` 头未发送**（`null`），服务端依赖连接关闭。
因此完整性只能由完整读取 + 字节比对验证，不能由头部声明。

### 关闭：NOT_ESTABLISHED（不得读作 PASS）

授权要求「完成后显式关闭 server；确认进程正常退出」。实际结果：

```
proc.terminate()  ->  exit_code = 1
```

**归因已验证**：在 Windows 上对**带 cleanup handler 的平凡进程**执行 `terminate()` 也统一返回 1。
即 **exit 1 是 `TerminateProcess` 的固有产物**，既不能读作产品关闭失败，也不能读作成功。

**但它同时意味着 IDE 的 `finally: dispose()` 未被执行**——骤杀不展开栈。
因此 Q1a **不能声称完整 PASS**：取证成立，**干净关闭未建立**。

这是**探测机制的限制**，不是产品发现。要让 `dispose()` 实际运行，需要能被 Python 将互不解堆的
信号（Windows 上需 `CTRL_C_EVENT` 投递到进程组），而非 `TerminateProcess`。
此机制尚未建立，且属于新的探测能力而非既有 Contract。

**边界保持**：Q1a PASS 不等于页面 JS 能执行（Q1b 属 P9b）；
未对 `.banner` 可见性作任何判断；Q2–Q7 未执行。

## Q2 `bad_request` HTTP 往返 — PASS / VERIFIED

隔离进程启动真实 IDE，仅观察 wire contract：**status、Content-Type、body 结构**。未解释结果，未判断页面行为。**7/7 案例全部符合预期。**

| 案例 | 期望 | 实测 | `kind` | body keys | 文案 |
| --- | --- | --- | --- | --- | --- |
| trace malformed eid | 400 | **400** | `bad_request` | `error, kind` | `eid must be an integer; got: abc` |
| trace illegal eid | 400 | **400** | `bad_request` | `error, kind, tool` | `context event 99999 is not an event in this capture (events 1..12)` |
| trace valid eid (11) | 200 | **200** | — | `edges, nodes, resourceFlows, summary` | — |
| trace 无 eid | 200 | **200** | — | 同上 | — |
| diff **带** `eid=abc` | 200 | **200** | — | `a,b,comparison,equal,evidence,firstDivergence,layers` | — |
| diff 无 eid | 200 | **200** | — | 同上，**21090 bytes 逐字节相同** | — |
| resource malformed eid | 400 | **400** | `bad_request` | `error, kind` | `eid must be an integer` |

全部 `application/json; charset=utf-8`，全部可解析为 JSON。

### 三项 Contract 级在线证据

**1. `bad_request → HTTP 400` 跨三个边界实测成立，且两条来源都在**：

* IDE 参数层（`_eid_param` → `QueryError(kind=...)`）→ body keys `["error","kind"]`
* **worker 子进程层**（action-tree membership → 跨进程保留 kind）→ body keys `["error","kind","tool"]`

多出的 `tool` 正是**跨进程分类保留**的痕迹，与 `workers.py:288` 的实现吻合。

**2. P3 E1'（eid 作用范围）获得正面证据**：`diff?eid=abc` 与无 eid 的 diff
结果**逐字节相同**（21090 bytes）。这是「Diff 不受 eid 影响」的**证明**，而非「静默忽略」的猜测。

**3. 稀疏 eid 得到第三次实测确认**：错误文案仍写 `events 1..12`，
而 Q8 已测得该 capture 仅 **4 个**合法 event id。**若 UI 按文案区间校验，会放过不存在的 event。**

### 残留进程：本次 run 未观察到泄漏

后置检查曾瞬时报告 1 个持有 `.rdc` 的进程。未据此下结论，
改为 **30 秒连续采样**，结果全部为 0。判定为**收尾竞态**（worker 子进程晚于父进程退出）。

记录口径：这是**本次 run 的观察**，**不声称已证明绝无泄漏**。

## Q3 — NOT_OBSERVABLE_IN_P9a / DEFERRED_TO_P9b

Q3 同时要求三类 failure 的现状，而它们在不同层：

| Q3 子项 | P9a HTTP 客户端能否观测 |
| --- | --- |
| HTTP / API error | **能**（已由 Q2 覆盖） |
| `api()` 的 `transport_error` | **不能** |
| `api()` 的 `malformed` | **不能** |

后两者是 **IDE 浏览器端 `api()` 函数的客户端分类**，服务器无此概念。
在 P9a 执行 Q3 只能得到「HTTP/API failure path observed」，而不能得到 Contract 要求的
「transport_error / malformed 在真实客户端执行中正确呈现」。

**这是能力边界，不是产品缺陷。** 不标 FAIL，也不为完成 Q3 引入浏览器。
