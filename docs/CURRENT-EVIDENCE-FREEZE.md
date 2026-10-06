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

**适用范围的第二次校准（改的是范围，不是数值）**：
19 未变。变的是它管谁。该上界是为「按 milestone
刷新的**状态文档**」校准的，而本文档自报的分类是

```
document_role: evidence_record
freshness_policy: point_in_time
```

并声明「任何时点声明都自动过期」。按
`DOCUMENT-CLASSIFICATION-CONTRACT.md` §3，`point_in_time` 记录描述**某一个时刻**，
本就应当随 HEAD 前进而老化；要求它跟随 milestone 节奏，
是把证据记录当成状态文档的类别错误。

因此本文档由另一条**同样会失败**的规则约束：`as_of_commit`
必须是 HEAD 的真实祖先。这正是「描述一个已不存在的仓库」
的实际形态，且无法靠等待绕过。任何声明为 `living` 或 `mixed`
的状态文档仍受 19 commits 上界约束。

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

> **范围限定（不得外推）**：仅限于**已分类**的 `bad_request` 案例。
> **HTTP status 单独不是充分的错误判别依据**（见下方观察）。

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

## Q4 合法空结果 — NOT_ESTABLISHED（no suitable legal empty-result case）

隔离进程、真实 IDE、普通查询（未制造特殊语义场景）。结果：

| 候选 | status | 分类 |
| --- | --- | --- |
| `/api/trace?x=0&y=0` | 200 | **non-empty**（3146 B） |
| `/api/trace?x=1&y=1` | 200 | **non-empty**（3146 B） |
| `/api/trace?x=5&y=5` | 200 | **non-empty**（3146 B） |
| `/api/trace?x=100&y=100` | 200 | **non-empty**（3166 B） |
| `/api/resource?id=<absent>` | 200 | **error body** |
| `/api/ci`（无 baseline） | 200 | `{"enabled": false}` |

**trace 在任意被测坐标都返回非空**（输出目标自身的写入总在 edges 中）。

因此本 capture **不存在自然的合法空结果**，`Q4 = NOT_ESTABLISHED`。按 Contract 要求**未制造特殊场景**，
**未为 Q4 扩充 corpus**。

`/api/ci` 的 `{"enabled": false}` **不被主张为合法空结果**：它是**能力标志**（CI baseline 未配置），
而非「查询无结果」，据此判 PASS 属于放宽标准。

## 观察：HTTP status 不是充分的错误判别依据（INSUFFICIENT / OBSERVED）

Q4 的附带探测发现四类真实响应：

```
classified error:      HTTP 400   body.error   body.kind
unclassified error:    HTTP 200   body.error   （无 body.kind）
parameter error:       HTTP 400   body.error   body.endpoint
valid result:          HTTP 200   正常结果 body
```

具体证据：

| 案例 | status | body keys | `kind` |
| --- | --- | --- | --- |
| absent resource | **200** | `error, tool` | **null** |
| malformed resource id | **200** | `error, tool` | **null** |
| `y=notanumber` | 400 | `error, endpoint` | null |
| `diff&eid=abc` | 200 | 正常 diff keys | — |

`absent_resource` 的 body：

> `unknown resource id 'ResourceId::999999999999999999'; use an id from 'rdebug resources'`

成因可在 `app.py:304` 见到：`if payload.get("error") and payload.get("kind")` —— **需要 `kind`**。
worker 仅在 `RDebugError` 带分类时附加 `kind`；未分类错误因此返回 **200**。

**正确的客户端 Contract 因此是三者合取**：

```
HTTP status  +  response body shape / error 字段  +  kind（若存在）
```

而**不是** `status == 200 → success`。

**这与 P2-C 已冻结的 `api()` 行为一致**（同时检查 `r.ok` 与 `body.error`），
因此**本次未发现 P2-C 回归，也未发现 Silent Wrong-Answer**。

### 对 Q2 结论范围的收窄

Q2 的 PASS 成立，但范围应表述为：

> **The tested classified `bad_request` cases produce HTTP 400 end-to-end.
> HTTP status alone is not a sufficient error discriminator for all current error responses.**

**不得**写成「errors always produce HTTP 400」。Q2 的两个错误案例**恰好都带 `kind`**，
因此未触及未分类路径；仅看 Q2 会误以为「错误 → 400」是普遍规律。

### `unclassified error → HTTP 200`：OPEN DESIGN QUESTION，不是缺陷

现有证据只能建立**这是当前实现的实际语义**，**不能**建立**这是错误的 API Contract**。
要判断后者需回答一个尚未授权的问题：未分类 worker error 是否本应映射为 4xx/5xx，
抑或 `200 + error body` 是有意设计。

该问题属 **Replay / transport / API semantics**，与 P9a 目标不同，且相关区域已冻结。
故记为 **OBSERVATION / OPEN DESIGN QUESTION**，**不开新 workstream**，
**不定性为 defect**。

## eid 可用性前置探测 — MET（prerequisite，不是 Q7 PASS）

只读探测，**未启动 IDE、未走 HTTP**。Q8 既有记录仅保存 `count=4` 与 `range=[1,12]`，
**未保存完整集合**，故按授权补一次探测。

```
valid_event_ids    = [1, 2, 11, 12]
distinct           = 4
range              = [1, 12]
draw_event_ids     = [11]
last_draw_event_id = 11
last_event_id      = 12
legal_but_not_draw = [1, 2, 12]
prerequisite       = MET
```

### 与错误文案范围的精确对照（第四次实证，本次首次给出精确数量）

```
真实合法:  1, 2, 11, 12
文案宣称:  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12
不存在:    3, 4, 5, 6, 7, 8, 9, 10          ← 8 个
```

**8 个 eid 在文案所宣称的区间内，但不在 action tree 中**，对其发起查询必然得到
`bad_request`。若客户端按错误文案校验区间，将放过这 8 个。

### 本 capture 的结构事实

`draw_event_ids = [11]` —— **仅一个 draw event**，且它正是默认 context（`last_draw_event_id = 11`）。
`12` 是合法但**非 draw** 的 event。

**对后续的既定含义**：

* **Q6（`max_draws`）**：只有 1 个 draw 时 `max_draws=1` 与 `max_draws=16` 很可能无可观察差异，
  即 **capture-degenerate**。即使日后比较出相同响应，也**不得直接判 PASS**——
  须先判定这是语义等价还是 capture 不足导致的退化。
* **Q7 剩余项**（合法 eid 是否可观测改变 context）：prerequisite 已 MET，`11` 与 `12` 是合适候选
  （覆盖 draw → 合法非-draw 边界）。但**失败不得预先定性为 defect**，可能是既有语义约束。

**本记录为可执行性 prerequisite，不是 Q7 结论。**

## Q5 `deep` 语义经 HTTP 边界保持 — PASS

隔离进程、真实 IDE、真实 diff 查询。**仅比较 HTTP status / body / 语义响应**；
未启动浏览器、未修改生产代码、未执行 Q6/Q7。

### 三项核心主张

| 主张 | 结果 | 证据 |
| --- | --- | --- |
| `deep=1` ≡ `deep=true` | **OK** | 两者均 200，body 均 **14139 bytes** |
| `deep=0` ≡ `deep=false` | **OK** | 两者均 200，body 均 **12780 bytes** |
| **`deep=1` ≠ `deep=0`（反向对照）** | **OK** | **14139 vs 12780，相差 1359 bytes** |

**反向对照是本次判定的关键**。若 `deep` 毫无效果，前两条等价性会**空洞成立**——
两个请求都成功而已。实测 `deep=1` 比 `deep=0` 多 1359 bytes，
说明 `include_shader_values` 确实生效，等价性因此**非平凡**。

这直接在线上证实 **P2-A / D1 的修复**：UI 发 `deep=1`、手写 URL 发 `deep=true`，
两者现在语义一致——**而 D1 的缺陷正是它们曾不一致**（服务端只读 `"1"`，`"true"` 落入 falsy 分支）。

### 非法值

| 值 | status |
| --- | --- |
| `yes` | **400** |
| `2` | **400** |
| `0x1` | **400** |
| `on` | **400** |

### 两项输入边界行为（原 spec 误列为非法值，已修正）

| 输入 | status | 实际语义 |
| --- | --- | --- |
| `deep=`（空） | 200 | `parse_qs` 默认丢弃空值 → `_bool_param` 视为**未提供** → 取默认 `false` |
| `deep=True `（尾随空白） | 200 | `_bool_param` 有 `.strip()` → 解析为 `true` |

**两者在实现契约下均非非法**，且**确定性地落到有文档的语义**，**不构成 Silent Wrong-Answer**。

**一项值得留痕的边界行为**：`deep=`（空参数）**静默等价于「未提供」**，即 shallow。
IDE **无法区分**「用户显式传了空」与「没传」。

这与 D1/D7 属同一族（输入形态未如实反映），但**严重度低得多**：它落到**有文档的默认值**，
而非替换成另一个**不同的值**（D7 的缺陷是 `100` → `(100,0)`，查询了错误位置）。
**不主张为缺陷，不新增 workstream，仅记录。**

### 一致性观察

5 个非法案例的 `kind` **均为 `null`**——走的是「`RDebugError` 无分类 → 400 但无 `kind`」路径，
与 Q4 观察到的 `bad_xy_trace`（400，keys `["error","endpoint"]`）同族。
**再次印证 status 不是唯一判别依据。** 不改变 Q5 判定。

## Q6 feasibility probe — DIFFERENCE_POSSIBLE（推翻了先前推断）

只判定「差异是否可能存在」，不判定 Q6。**未扩 corpus、未启新 capture 工作流。**

```
(320,240)  any_diff = TRUE
   max_draws=1   analyzedDraws=1  truncatedDraws=true    8364 bytes
   max_draws=2   analyzedDraws=2  truncatedDraws=false   8365 bytes
   max_draws=16  analyzedDraws=2  truncatedDraws=false   8365 bytes

(10,10) / (0,0) / (100,100)   any_diff = False（analyzedDraws 恒为 1）
```

### 被实测推翻的推断

先前依据 `draw_event_ids = [11]`（**仅 1 个**）推断「Q6 必然 degenerate」。**该推断错误。**

原因是**维度混淆**——两个量不是同一件事：

| 量 | 值 | 含义 |
| --- | --- | --- |
| `draw_event_ids` | `[11]` | **带 drawcall 的 event** |
| `totalWriteEvents` / `analyzedDraws` | **2** | **被分析的 modification 序列长度** |

`max_draws` 约束的是**后者**。`draw_event_ids=[11]` **不足以推断 `max_draws` 是否退化**。

> **方法学教训**：**不要用 capture 的 event-level draw 数量替代 query-level analysis cardinality。**

### 一处影响判定方式的观察

截断边界处响应仅相差 **1 byte**（8364 vs 8365）。截断确实发生
（`truncatedDraws` 由 `true` 变 `false`），但**字节长度是真实却极易忽略的信号**。
判定必须基于 `analyzedDraws` / `truncatedDraws` **字段**。

### 探测自身两处缺陷（方法学记录，不升格为产品缺陷）

1. 编辑残留一行**未带 base URL 的重复请求**，报 `MissingSchema`
2. readiness 循环无标志位，服务器未起时抛同类错误

两者都会把「探测坏了」伪装成「环境不可用」。修正后 `DIFFERENCE_POSSIBLE` 成立。

## Q6 `max_draws` 语义经 HTTP 边界保持 — PASS

主判定坐标 `(320,240)`（IDE 自身默认 A）。**5/5 主张成立。**

| max_draws | status | analyzedDraws | truncatedDraws | bytes |
| --- | --- | --- | --- | --- |
| **1** | 200 | **1** | **true** | 8364 |
| **2** | 200 | **2** | **false** | 8365 |
| **16** | 200 | **2** | **false** | 8365 |

| 主张 | 结果 |
| --- | --- |
| `max_draws=1` 截断（`truncatedDraws=true`, `analyzedDraws=1`） | **OK** |
| `max_draws=2` 不截断且分析 2 个 | **OK** |
| `max_draws=16` 不截断且分析 2 个（无天花板效应） | **OK** |
| `max_draws=2` 与 `16` 在所有 summary 字段上一致 | **OK** |
| **辅助反向对照**：无可截断内容的坐标保持稳定 | **OK**（3/3 stable） |

**反向对照的作用**：三个 `analyzedDraws` 恒为 1 的坐标在 `max_draws` 变化时**完全不变**。
这证明响应差异来自**数据本身**（存在可截断序列），而非参数被忽略——
若 `max_draws` 无效，四项主张可能空洞成立。

这直接在线上证实 **P2-A / D2**：截断经真实 HTTP 边界可见，且 `truncatedDraws` 被如实报告。

## Q7 `eid` 作用范围经 HTTP 边界保持 — PASS（全部子命题确证）

主对比 `11`（draw / 默认 context）vs `12`（合法但非 draw）。**你预设的 B 类（非 draw 语义约束）未发生**：
`12` 正常工作，且 `mods=2 / analyzed=2`，与 draw event `11` 的分析深度相同。

### Trace：`summary.contextEventId`

| eid | status | `contextEventId` | analyzedDraws | bytes |
| --- | --- | --- | --- | --- |
| 无 eid | 200 | **11** | 2 | 8365 |
| 1 | 200 | **1** | 1 | 3164 |
| 2 | 200 | **2** | 1 | 3164 |
| 11 | 200 | **11** | 2 | 8365 |
| 12 | 200 | **12** | 2 | 8365 |

四个合法 eid **逐一等于所请求的值**（无重写、无偏移）；**无 eid ≡ eid=11**（= `last_draw_event_id`）；
`1`/`2` 与 `11`/`12` 的 `analyzedDraws` 不同（1 vs 2），说明 context **真的改变了工作量**，不只是标签。

### Resource：顶层 `contextEventId`（读回位置已修正）

| eid | status | 顶层 `contextEventId` | bytes |
| --- | --- | --- | --- |
| 无 eid | 200 | **11** | 729 |
| 1 | 200 | **1** | 727 |
| 2 | 200 | **2** | 727 |
| 11 | 200 | **11** | 729 |
| 12 | 200 | **12** | 729 |

`all_legal_echo_their_own_context = 4/4`，`default_matches_last_draw = True`。

首次运行读 `summary` 得到全 `None`，是**探针取值位置错误**，与产品无关；
Q8b 的 key 集合本已提示该字段位于顶层。修正读回位置后 4/4 成立。

### 全部子命题

| 子命题 | 证据来源 |
| --- | --- |
| Diff/Explain 不受 eid 影响 | **Q2**：`diff?eid=abc` 与无 eid 逐字节相同（21090 B） |
| Trace 非法 eid → 400 | **Q2**：`eid=99999` |
| Resource 非法 eid → 400 | **Q2**：`eid=abc` |
| Trace context 随合法 eid 改变 | 本轮，5/5 |
| Resource context 随合法 eid 改变 | 本轮，4/4 + 默认 ≡ 11 |

→ **Q7 = PASS**

### 结构性观察（不是 defect）

```
/api/trace     ->  summary.contextEventId
/api/resource  ->  顶层 contextEventId
```

两个端点把该字段放在**不同层级**。目前**无跨端点共享 response-shape Contract**，
因此**不足以判定违反 Contract**，**不主张为 defect，不新开 workstream**。

**保留的工程风险说明**：客户端若假定所有 endpoint 都把 `contextEventId` 放在 `summary`，
Resource 会**静默得到 `undefined`**。这属于未来客户端实现的 **shape-consistency trap**，
不改变 Q7 判定。

字节差异（729 vs 727）仅作辅助观察，**不作为 context 证据**——判定依据为字段级取值。

## P9a HTTP / Semantic Boundary Workstream — COMPLETE / FROZEN

### 账本

| 项 | 状态 |
| --- | --- |
| **Q1a-Retrieval** | **PASS** |
| Q1c-Clean Shutdown | **NOT_ESTABLISHED** / capability boundary（未授权建立） |
| **Q2** | **PASS**（仅已分类 `bad_request`；status 单独不充分） |
| Q3 | **NOT_OBSERVABLE_IN_P9a** → DEFERRED_TO_P9b |
| Q4 | **NOT_ESTABLISHED**（无合适合法空结果案例） |
| **Q5** | **PASS**（含反向对照） |
| Q6 feasibility | **DIFFERENCE_POSSIBLE** |
| **Q6** | **PASS**（5/5） |
| **Q7** | **PASS**（全部子命题确证） |
| **Q8 / Q8b** | **PASS / PASS** |

**6 项 PASS，3 项非 PASS 保留原分类。** 不将「全部有结论」升级为「全部 PASS」。

### 冻结的两条判定原则

**1. event-level draw 数量 ≠ query-level analysis cardinality**

`draw_event_ids=[11]`（带 drawcall 的 event）**不能**推导 `max_draws` 是否退化。
`max_draws` 约束的是**被分析的 modification 序列**，该 capture 实测 `analyzedDraws=2`。
「单 draw event ⇒ Q6 退化」这一推断**已被实测推翻**。

**2. 字段级语义证据优先于 payload 大小**

Q6 截断边界处响应仅相差 **1 byte**（8364 vs 8365）。字节长度是真实却极易忽略的信号，
若沿用 Q5 的字节判据极可能误得「无差异」。判定必须基于 `analyzedDraws` / `truncatedDraws` **字段**。
同理，Q7 的 729 vs 727 bytes 仅作辅助，**不作为 context 证据**。

### 本阶段的三项非 PASS 各自的性质（不得混同）

| 项 | 性质 |
| --- | --- |
| Q1c | **能力边界**：`terminate()` 无法证明 `dispose()` 执行；exit 1 已归因为 `TerminateProcess` 固有产物，既非失败也非成功 |
| Q3 | **结构性不可观测**：`transport_error` / `malformed` 是浏览器端 `api()` 的分类，服务器无此概念 |
| Q4 | **证据不足**：本 capture 无自然合法空结果；**未制造特殊场景、未扩 corpus** |

### 本阶段的三处探测自身错误（方法学证据，非产品缺陷）

1. 把 `deep=`（空）与 `True `（尾随空白）spec 成非法值 → 虚增两条「非法值未被拒绝」
2. 残留未带 base URL 的重复请求 + readiness 无标志位 → 「capture 不可用」的假象
3. Resource 的 `contextEventId` 从 `summary` 读取 → 「Resource context 不变」的假象

三者的共同形态：**把「探测坏了」或「取错位置」读成「产品/环境有缺陷」**。
第 3 项经最小补测（仅改读回位置）即闭合，**推测未被当作观察**。

### 阶段边界

未修改任何生产代码；未启动浏览器；未扩充 capture；未推进 D3b / D4 / eid discovery / A8；
未建立 graceful-shutdown capability；未重开 Track A。P0–P3 冻结项全程未触碰。

### 后续（均未启动，须显式选择）

* **P9b** Browser Rendering —— 解决 Q3，需 Playwright
* **P10** Human Acceptance
* **Deferred workstreams** —— D3b / D4 / eid discovery / A8，各自需重新定义 scope
* **Q1c** —— 除非 graceful-shutdown capability 本身成为明确目标

**当前没有为「把账本全部变成 PASS」而启动任何一项的理由。**
