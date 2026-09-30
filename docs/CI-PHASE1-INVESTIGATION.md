# Phase 1 调查：CI 验证自动化（`DESIGN_SPEC.md` §4）

日期：2026-09-29
授权范围：**Phase 1 Contract / evidence question**。
**未修改任何生产代码，未新增任何 CI 配置。**

## 0. 为什么先问 Contract 而不是先写 CI 配置

`context_eid` 与 shader reflection 两项的共同教训：
**行为先于规范，就会产生「无法判断对错」的状态。**
CI 更应如此 —— 因为 CI 本身就是**用来发现别人这种错误的**机制。
若 CI 自身的 pass 裁决可以被零验证地产生，
那么它发现回归的可信度就先塌了一角。

因此本阶段只回答：**CI gate 的 pass 裁决意味着什么，它是否被定义过。**

## 1. 规范对 CI 的要求

`DESIGN_SPEC.md` §4「质量门」共 5 条：

| # | 门 | 当前自动化状态 |
| --- | --- | --- |
| 1 | 核心测试（`tests/`）+ transport 测试（`tests_transport/`）全绿；transport 失败不得导致核心失败 | 可自动化，**未接 CI** |
| 2 | `scripts/audit_boundaries.py` 全部 PASS | 可自动化，**未接 CI** |
| 3 | 语义等价：性能/重构变更须通过 cold==warm 等价检查 | **规范定义了门，未见对应可执行检查** |
| 4 | benchmark 回归需附 `docs/validation/` 存档 | **流程要求，无自动强制** |
| 5 | RenderDoc fork 零 tracked modification | 可自动化，**未接 CI** |

`§6` 定义 `audit_boundaries.py` 为机械合规审计（非零退出码表示违规）。

**仓库现状**：`rd-intelligence` 内**零 CI 配置**
（无 `.github/`、无任何 `*.yml/*.yaml`、无 pipeline 文件）。
`src/rdebug/ci.py` 是 CI 的**语义 API**（`record` / `check`），
**不是 CI 配置**。

> **发现 0（形态）**：规范定义了 5 个质量门与一个机械审计，
> 但**没有任何机制在提交时强制执行它们**。
> 这与本轮调查开始时对 CI 的既有描述（「验证自动化不足」）一致，
> 属**已知形态**，不是新缺陷。

## 2. 但 CI gate 自身的 pass 裁决存在 Contract 缺口

`ci.check()` 返回一个**裁决**：

```python
"status": "pass" if not failures else "regression"
```

即 **pass = 「没有记录到失败」**，而**不是**「执行了足够的验证」。
`ci.check` **没有最小检查数规则**。

### 2.1 实测（真实 capture，无注入）

capture：`tests/workload/corpus/w00001_frame11.rdc`（D3D11，单 draw）

| 输入 | status | passedChecks | failures |
| --- | --- | --- | --- |
| `{}`（完全空） | `regression` | 0 | 1 |
| `{"captureSha256": <正确>}` | **`pass`** | **0** | **0** |
| `{"captureSha256": <正确>, "pixels": {}, "pairs": {}}` | **`pass`** | **0** | **0** |
| `{}` + `ignore_capture_hash=True` | **`pass`** | **0** | **0** |
| 真实 `record()` 产出（2 pixels）自检 | `pass` | 4 | 0 |
| 同一 baseline **截断**（`pixels` 丢失） | **`pass`** | **0** | **0** |
| **正对照**：篡改 `fragmentEventId` | `regression` | 2 | 2 |

### 2.2 两个关键判断

**① 「零检查也 pass」是真实可观测行为，不是推断。**
用**同一个真实 capture**，把 baseline 的 `pixels` 去掉（模拟 merge 冲突、
部分 schema 迁移、上传截断等**普通事故**），gate 即返回
`status: "pass"`、`passedChecks: 0` —— **它只核对了 capture 文件哈希，
没有核对任何渲染结果**。

**② 唯一的阻止因素是 capture-hash 检查，而它被设计为可跳过。**
完全空的 `{}` 之所以 fail，**只是偶然** —— 因为
`baseline.get("captureSha256")` 是 `None` 导致哈希不匹配。
一旦 `ignore_capture_hash=True`，连**完全空**的 baseline 都报 `pass`。

> 因此现状不是「哈希检查顺带保护了它」，而是
> **「除了一个可跳过的哈希检查，没有任何保护」**。

**③ 正对照同样重要。** 篡改 `fragmentEventId` 后 gate **确实**报了
`regression`（2 failures）。所以 gate 在**有检查可跑时是有效的** ——
问题不是「gate 坏了」，而是 **「零验证的 pass 是可表示的」**。

## 3. 这与本项目已处理的风险类别同源

`tests/unit/test_unknown_discipline.py` 的开篇立论：

> *Regression tests: a failure to look must never be reported as agreement.*
> … turning a **failed** enumeration into an empty list, which then
> compared equal to another empty list and produced a fabricated "same".

该文件所治理的正是「**没查到 → 被当成一致**」。
diff 层已按此修复（`descriptorsError` → `unknown`）；
我本轮为 reflection 建立的 §2.11 也是同一条纪律。

> **发现 1：CI gate 是同一风险类别中唯一尚未设防的一环。**
> `ci.check` 把「**没有可比对的项**」压成 `pass`，
> 而 §2.5 / §2.11 的纪律要求这种情况是显式的不可用状态。

### 3.1 项目自身已承认该意图，但不是规则

`tests/unit/test_ci_gate.py:99`：

```python
self.assertGreater(report["passedChecks"], 0)
```

→ **「一份有意义的报告至少要有一项检查」这一意图已被写入测试**，
但它只作用于 happy path 的 roundtrip 用例，
**不是 `ci.check` 内部的约束**，因此对退化 baseline 无效。

## 4. 分类矩阵（Phase 2）

| 情况 | 当前输出 | 是否正确 |
| --- | --- | --- |
| baseline 完整且一致 | `pass`，`passedChecks > 0` | ✅ **正确**（实测 4 checks） |
| baseline 完整且有真实回归 | `regression` + failures + evidence | ✅ **正确**（实测 2 failures） |
| **baseline 截断/退化（键丢失）** | **`pass`，0 checks** | ❌ **不正确**（零验证被报为成功） |
| **baseline 键存在但为空** | **`pass`，0 checks** | ❌ **不正确**（同上） |
| 完全空 baseline | `regression` | ⚠️ 结果"对"，但**理由偶然**（哈希不匹配），非最小检查规则 |
| `ignore_capture_hash=True` + 空 baseline | **`pass`，0 checks** | ❌ **不正确**（保护被设计为可跳过） |

## 5. 现实影响（须诚实界定）

- **今天的实际影响有限**：`ci.check` **尚未被任何 CI 自动化消费**
  （零 CI 配置），且无生产方依赖它做放行决策。
- **但风险是真实的**：一旦把它接入自动化 gate（§4 本就要求），
  一个退化的 baseline 会让 gate **静默变绿**。
- 且这种退化**不需要恶意**：merge 冲突、schema 迁移丢键、
  artifact 上传截断都会产生它。

**因此这不是「当前正在发生的错误」，而是「接线前的最后一道缺口」。**
接线（写 CI 配置）若先于本项收口，就会把一个可静默 pass 的裁决接到放行路径上。

## 6. 结论

| 环节 | 状态 |
| --- | --- |
| §4 五个门是否被规定 | ✅ 是（§4） |
| 是否有机制强制执行 | ❌ **无**（零 CI 配置）—— 已知形态 |
| pass 裁决的 Contract | ❌ **未定义**（「pass」意味着什么未成文） |
| 「零验证的 pass」是否可观测 | ✅ **已确认**（真实 capture，无注入） |
| gate 在有检查时是否有效 | ✅ **已确认**（正对照 2 failures） |

**未进入修复。** 与前两项一致：
先定义 Contract（pass 裁决的语义 + 最小检查数规则），
再实现，且实现阶段须做「缺陷回退 → 三类对照 → 恢复」的机械验证。

候选 Contract 要点（**待裁决，本阶段不写入规范**）：

```
pass  必须蕴含：至少执行了一项检查，且全部通过。
0 项检查 → 不得是 pass；应为显式不可用/需人工确认的状态。
理由：与 §2.5 / §2.11 同一纪律 —— 没验证 ≠ 验证通过。
```

## 7. 状态

```
CI Phase 1 Contract 调查     COMPLETE
CI 实现 / 接线                NOT AUTHORIZED
context_eid                   FROZEN（FIXED / VERIFIED）
shader reflection            FROZEN（Contract DEFINED / defect NOT ESTABLISHED）
```

**未做**：未写 CI 配置、未修改 `ci.py`、未改测试期待值、
未重开 F-N3-1、未开启 N3-05B / D5 / D7。
