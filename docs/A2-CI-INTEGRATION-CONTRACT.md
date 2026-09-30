# A2 Phase 1：CI integration Contract（§4 自动化门禁）

日期：2026-09-29
授权范围：**仅回答 6 个 integration Contract 问题 + 记录证据**。
**未写任何 CI 配置、未接线、未改测试 harness。**

对应缺口：A2 = §4 五门**无自动执行者**
（`GAP / CONFIRMED WITH OBSERVED CONSEQUENCE`，observed consequence = A1）。

---

## 0. 本阶段的定位

`§4.1` 已冻结的是**裁决逻辑**（`ci.check` 不得零验证即 pass）。
**A2 是另一件事：§4 的五个门没有任何机制在提交时自动执行。**
两者不可混为一谈；本阶段处理后者，且**只做 Contract，不做实现**。

---

## 1. ⚠️ 新发现（A2-1）：测试 harness 可在「什么都没验证」时报成功

这是本阶段最重要的发现，且**与刚冻结的 `ci.check` 缺陷属同一类别**，
只是发生在**测试 harness 自身**而非 CI 裁决层。

### 实测（移除 `RDEBUG_RENDERDOC_PATH` / capture 环境变量）

```
$ python -m unittest discover -s tests/integration -t .
Ran 63 tests in 3.76s
FAILED (failures=1, errors=1, skipped=60)
exit code: 1
```

### 为什么这仍然是缺口

| 事实 | 含义 |
| --- | --- |
| **60 / 63 被 skip** | 真实 replay 路径**完全未被验证** |
| 仅 2 个测试真正执行 | 1 个 `ok` + 1 个 `ERROR` |
| exit 1 **来自那个偶然的 ERROR** | 而非任何**设计**上的「环境缺失即失败」 |
| `test_n3_worker_failure_is_not_mislabelled_a_bad_request` **无守卫** | 它需要真实 capture 却未被 `skipUnless` 覆盖 |

> **风险**：若把那个 ERROR「顺手修好」（一个完全合理的清理），
> 套件将报 **`OK` + 60 skipped** —— 即
> **基础设施未运行被报告为全部通过**，exit code 0。
>
> **当前是靠偶然逃生，不是靠设计。**

### 与已冻结项的关系

| 项 | 状态 |
| --- | --- |
| `ci.check` 零验证 pass | ✅ **已修复并冻结**（§4.1） |
| **测试 harness 零验证 pass** | ❌ **未修复，本阶段新识别** |

两者是同一原则的两个未设防面。§4.1 的结论「`pass` 必须蕴含至少执行一项检查」
**必须同样适用于 harness**，否则门禁本身可被环境缺失绕过。

---

## 2. 逐问回答

### Q1 —— 哪些命令属于放行门禁，哪些只是开发者检查？

按「是否可在无人工判断下机械判定」划分。**本划分是提案，需你确认。**

#### 候选放行门禁（deterministic、可机械判定）

| 命令 | 判定对象 | 需要 RenderDoc |
| --- | --- | --- |
| `unittest discover -s tests/unit` | Stable Core 纯逻辑 | ❌ |
| `unittest discover -s tests_transport` | transport 纯净性 | ❌ |
| `unittest discover -s tests/integration -t .` | 真实 replay 行为 | ✅ **需要** |
| `python scripts/audit_boundaries.py` | §2.1–2.9 机械边界 | ❌ |
| `python scripts/audit_fork_integrity.py` | §2.1.1 fork exception | ❌（只读 git） |
| `rdebug ci-check --baseline <b>` | 渲染回归 | ✅ **需要** |

#### 开发者检查（非门禁）

`bench.py` / `bench_transport.py` / `session_bench.py`（性能，D6 明确
**非门禁**）、`reasoning_bench.py`、`mcp_smoke.py` / `mcp_call.py` /
`ide_smoke.py`（冒烟）、`workload_run.py` / `workload_corpus.py`（工作负载）、
`d4_evidence_probe.py`（D4 已 DEFER）、`diff_closure.py`。

> 判据：**会因机器性能/环境差异而非缺陷失败的，一律不是门禁。**
> D6 的「measured / NOT A GATE」正是此原则的既有先例。

### Q2 —— CI 环境是否具备真实 RenderDoc / replay runtime？

**结论：分层，且当前「诚实性」只在 session 层成立。**

| 层 | 需要什么 | 当前行为 |
| --- | --- | --- |
| unit / transport / 两个 audit | 无（纯 Python） | ✅ 可在任何 runner |
| integration / `ci-check` | 构建好的 `renderdoc.pyd` + **真实 GPU + 对应驱动** | ⚠️ 见下 |

实测（`N3-05A1.rdc` = **Vulkan**、`N3-02` = D3D12）：

```
LocalReplaySupport = 1        本机可 replay
core.py:231  if not cap.LocalReplaySupport(): raise ReplayUnsupportedError
```

→ **session 层已把「replay 不可用」显式抛错，不静默**。这是有利事实。
→ 但 CI 要跑真实 capture 门禁，**必须有 GPU runner**；
纯 CPU runner 只能覆盖 unit / transport / 两个 audit。
**这是接线时的硬约束，不是本阶段可解决的。**

### Q3 —— `unknown` 在 CI 中的最终处理规则？

**✅ 已裁决（2026-09-29）：语义三态与门禁裁决分层。**

| 语义状态 | 含义 | CI 门禁含义 |
| --- | --- | --- |
| `pass` | 已执行内容验证，且全部通过 | **可通过** |
| `regression` | 已执行内容验证，发现回归 | **阻断** |
| `unknown` | 没有足够证据形成内容结论 | **不通过 / 需人工处理** |
| `infrastructure failure` | 门禁本身无法正常执行 | **阻断，且与 regression 分开报告** |

**因此无矛盾**：

> **§2.5 / §4.1 定义「语义结论是什么」；
> CI integration 定义「这个结论能否作为自动放行依据」。**

- `unknown` 仍是「无法证明」，**绝不升级为 `regression`**；
- 但**无法证明也不能自动放行**。
- `infrastructure failure` 既不是 `regression`，也不是 `unknown` 的伪装，
  而是**执行层失败**，默认 **fail-closed**。
- **绝不**把 infrastructure failure 转成 regression（授权边界明确禁止）。

> ⚠️ 该张力已解除。**实现见 §7（I1/I2 已交付），接线仍 NOT AUTHORIZED。**

### Q4 —— §4 的 5 个质量门各自需要什么最小执行证据？

| 门 | 最小执行证据 | 当前可自动判定？ |
| --- | --- | --- |
| 1 测试全绿 | **已执行测试数 > 0**，且 0 failure | ⚠️ 部分 —— 见 A2-1 |
| 2 边界审计 | 退出码 0 + `N/N checks passed` | ✅ |
| 3 语义等价 cold==warm | **无对应可执行检查**（D6 明确非门禁） | ❌ **规范有门、实现不存在** |
| 4 benchmark 存档 | 无自动判定路径 | ❌ 流程要求 |
| 5 fork 零 tracked mod | 退出码 0 + 声明与实际**双向一致** | ✅ **本次已交付**（F1–F4） |

> **门 3 是新暴露的缺口**：§4 第 3 条要求「任何性能/重构变更必须通过
> cold==warm 等价检查」，但**代码库中不存在这个检查**。
> 这与 A1/A2-1 同属「规范声明 vs 实际存在」的落差，**本阶段仅记录**。

### Q5 —— baseline / artifacts 如何进入 CI，且如何防止零验证 pass 复现？

| 项 | 现状 |
| --- | --- |
| baseline 入口 | `rdebug ci-record -o <f>` / `rdebug ci-check --baseline <f>`（CLI 已存在） |
| artifacts 位置 | **`../rdebug-validation`（仓库外）**，含 14 个 hash 覆盖的冻结物 |
| 零验证 pass 防护 | ✅ `ci.check` 侧已由 §4.1 冻结（`executed == 0 → unknown`） |
| **harness 侧零验证防护** | ❌ **不存在** —— 即 A2-1 |

**结论**：§4.1 的原则**必须推广到 harness**，即新增门禁条款：

> **MUST NOT**：门禁在**实际执行项数为 0** 时报 pass。
> 环境缺失、依赖不可用、capture 未提供 —— 一律**不得**退化为 skip + pass；
> 必须使门禁**失败**（或进入显式的「无法验证」终态）。

### Q6 —— 能否区分 regression / unknown / infrastructure failure？

**结论：当前【不能】，且存在一个具体潜在实例。**

| 类别 | 当前是否可区分 |
| --- | --- |
| `regression`（内容真的变了） | ✅ `ci.check` 返回 `regression` + failures |
| `unknown`（未验证） | ✅ `ci.check` 返回 `unknown`（§4.1 冻结） |
| **infrastructure failure**（环境没跑起来） | ❌ **不可区分** —— 见 A2-1 |

实测：环境缺失时，套件以 **skip** 表达，而 skip 在汇总里与「通过」并列，
仅靠**一个偶然的 ERROR** 使 exit code 非零。
**若该 ERROR 被修复，infrastructure failure 就会被报成 pass。**

> 这与 A2-1 是同一事实的两个视角：
> **A2-1 是它的实例，Q6 是它的类别名。**

---

## 3. 由此得出的 Contract 要点（**提案，未写入规范**）

| # | 条款 | 依据 |
| --- | --- | --- |
| I1 | 门禁 MUST 在**实际执行项数为 0** 时**不得**报 pass | A2-1 / Q5 / §4.1 类比 |
| I2 | 环境/依赖/capture 缺失 MUST 使门禁**失败**或进入显式「无法验证」终态，**不得**退化为 skip + pass | A2-1 |
| I3 | 门禁 MUST 能区分 **regression / unknown / infrastructure failure** 三类 | Q6 |
| I4 | 性能类基准 MUST NOT 作为放行门禁（机器差异 ≠ 缺陷） | Q1 / D6 先例 |
| I5 | 真实 capture 门禁 MUST 声明其**环境需求**（GPU + 驱动 + 构建产物），且不可用时 MUST 显式失败 | Q2 |
| I6 | §4 门 3（cold==warm）在**实现前** MUST NOT 被列为已满足 | Q4 |

**I3 与 §4.1 的关系**：§4.1 保证了「不把未验证当 pass」；
I3 进一步要求「未验证」与「内容失败」**可区分**，
否则 CI 无法决定阻断还是人工复核 —— 即 **Q3 的张力**。

---

## 4. 本阶段未做

未写 CI 配置；未接线；未改测试 harness；未新增/修改 `skipUnless` 守卫；
未修 A2-1；未改 `ci.py`；未动 §2.1/§2.9/§2.10/§2.11/§4.1；
未动 fork；未动冻结产物；未裁决 Q3。

## 5. 待裁决

| # | 待裁决 | 性质 |
| --- | --- | --- |
| 1 | **Q3：`unknown` 的 CI 处理**（阻断 / 人工复核）—— 选项 3 已明确不可接受 | **阻塞接线的语义问题** |
| 2 | 是否授权进入 **Phase 2：harness 侧 I1/I2 实现**（最小执行数断言 + 环境缺失即失败） | 与 CI 接线**分离**，可独立授权 |
| 3 | Q1 的门禁/开发者检查划分是否认可 | 划分提案 |
| 4 | §4 门 3（cold==warm）缺可执行检查 —— 是否立项 | 新暴露缺口 |

---

## 6. 授权与执行状态（2026-09-29 更新）

| 项 | 状态 |
| --- | --- |
| A2 Phase 1 | **COMPLETE** |
| A2-1 harness zero-validation | **CONFIRMED** |
| Q1 门禁/开发者检查划分 | **认可** |
| Q3 `unknown` 处理 | **已裁决**（四态分层，见 §2） |
| I1 / I2 | **AUTHORIZED → 已实现并验证**（见 §7） |
| I3 | **AUTHORIZED AS INTEGRATION CONTRACT**（本次未实现，属接线层） |
| I4 / I5 / I6 | **ACCEPTED AS CONTRACT CANDIDATES**（未写入规范） |
| Gate 3 executable check | **NOT IMPLEMENTED / PHASE 1 已授权**（未开工） |
| CI pipeline | **NOT AUTHORIZED** |
| CI release wiring | **NOT AUTHORIZED** |

## 7. Phase 2 交付：harness 侧 I1/I2

### 设计判断：修在门禁层，不动测试

`skipUnless` 守卫**本身不是缺陷** —— 本地无 GPU 时 skip 是合法的开发体验。
缺陷在于**门禁**把 skip 当 pass。因此新增**独立门禁产物**，与测试分离：
测试保留 skip，门禁要求环境齐备且最小执行数达标。

| 组件 | 位置 |
| --- | --- |
| 门禁声明 | `release-gates.json`（5 个 gate + 分类词表 + 每门 rationale） |
| 门禁执行器 | `scripts/release_gate.py`（I1/I2 强制） |
| 对照 | `tests/unit/test_release_gate.py`（**24 项**） |

### I1 —— 实际执行项为 0 或低于声明下限 → 不得 `pass`

- 全部 skip → `INFRASTRUCTURE_FAILURE`
- 低于声明下限 → `INFRASTRUCTURE_FAILURE`
- 输出不可解析 → `INFRASTRUCTURE_FAILURE`（**不猜**）

### I2 —— 缺环境/依赖/capture → 不得 skip+pass

- 前置检查**在运行之前**完成，缺环境时**根本不产生 skip 风暴**
- `env` / `module` / `capture` / `sibling_fork` 四类前置均可声明

### 核心对照：A2-1 那个场景

用 fake gate 精确复现 unittest 的输出形状：

```
Ran 63 tests in 3.8s

OK (skipped=60)
```

→ **exit 0、unittest 说 OK、63 项中 60 项从未执行**
→ 门禁裁决：**`INFRASTRUCTURE_FAILURE`**，非 `PASS`

### 四态分类（Q3 落地）

| 形状 | 裁决 |
| --- | --- |
| 全部执行且全过 | `PASS` |
| 有 failures/errors 且已执行 | `REGRESSION` |
| 部分 skip（已超下限） | `UNKNOWN`（不通过，需人工） |
| 前置缺失 / 零执行 / 不可解析 | `INFRASTRUCTURE_FAILURE`（阻断，**不与 regression 混报**） |

### I4 已有对照

`test_no_benchmark_is_a_release_gate`：断言门禁命令中不含
`bench` / `smoke` / `workload` / `d4` / `probe` / `reasoning`。
D6 的「measured / NOT A GATE」由此**机械化**，而非仅靠约定。

### 回退验证

```
I1/I2 强制失效（门禁只读 exit code）   8 FAIL
恢复                                    24 OK
```

仍选「强制力失效」而非「文件缺失」作为回退点，
以排除对照只是对文件存在性反应。

### 真实状态下的两侧裁决

```
环境齐备：  5 gate 全 PASS, exit 0
              unit 152 / transport 58 / integration 63 / 两个 audit
环境缺失：  integration → INFRASTRUCTURE_FAILURE
              missing: RDEBUG_RENDERDOC_PATH, RDEBUG_INTEGRATION_CAPTURE,
                       module:renderdoc, capture:RDEBUG_INTEGRATION_CAPTURE
              RESULT: BLOCKED, exit 1
```

## 8. 本阶段仍未做（残留风险，明确保留）

- **未接线**：`release_gate.py` **不被任何自动机制调用**。
  手动运行为主 —— 这与 A2 的原始缺口是**同一件事的缩小版，不是解决**。
- **I3 未实现**：三态 + infrastructure 的**报告分离**已在分类器中体现，
  但「CI 如何据此阻断或转人工」的接线策略属 I3，未做。
- **I5 / I6 未写入规范**，仅为候选。
- **Gate 3 未开工**。
- **未改** `ci.py`（§4.1 Contract 保持冻结不变）、Semantic API、§2.5 三态定义、
  测试的 `skipUnless` 守卫、fork、冻结产物。
