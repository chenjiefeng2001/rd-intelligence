# CI integration Phase 1：orchestration Contract

日期：2026-09-29
授权范围：**仅 orchestration Contract**（7 问）。
**未写 pipeline 配置、未接线 release blocking、未实现 Gate 3。**

回答的问题只有一个：

> **「CI 应该怎样解释现有 gates？」**

而不是：

> **「CI 现在开始强制这些 gates。」**

---

## 0. 本阶段确立的 Contract 基础

| 基础 | 状态 |
| --- | --- |
| §4.1 verdict semantics | **FROZEN** |
| harness I1/I2 | **已授权 / 可验证**（`scripts/release_gate.py`） |
| regression / unknown / infrastructure 三分 | **已定义**（Q3 裁决） |
| §2.1 fork-integrity audit | **可执行**（22 项对照） |
| Gate 3 语义定义 | **DEFINED**（`docs/GATE3-COLD-WARM-CONTRACT.md`） |
| **Gate 3 可执行检查** | **NOT IMPLEMENTED** |

---

## 1. 问 1：五个 §4 Gate 的执行入口与当前状态

**执行矩阵**（`§4` 五门 ↔ 实际可执行物）：

| §4 门 | 执行入口 | 检查数 | 状态 |
| --- | --- | --- | --- |
| **1** 测试全绿 | `unittest discover -s tests/unit`<br>`-s tests_transport`<br>`-s tests/integration -t .` | **3** | **IMPLEMENTED** |
| **2** 边界审计 | `python scripts/audit_boundaries.py` | 1 | **IMPLEMENTED** |
| **3** cold==warm 等价 | **无** | 0 | ⚠️ **NOT_IMPLEMENTED**<br>（语义已定义，证据已采，未实现） |
| **4** benchmark 存档 | **无可执行检查** | 0 | ⚠️ **PROCESS_ONLY**<br>（规范为流程要求，无自动判定路径） |
| **5** fork 零 tracked mod | `python scripts/audit_fork_integrity.py` | 1 | **IMPLEMENTED** |

合计：**5 个可执行检查**（对应 §4 门 1/2/5），**2 个无可执行物**（门 3、门 4）。

### 1.1 ⚠️ 必须点明的治理后果

> **只要门 3 与门 4 无可执行物，总体 CI 状态就不可能是 `PASS`。**

这不是缺陷，而是正确结果：
`§4` 声明了五个门，其中两个**没有实现**；
声称「CI 全绿」等于**把两个未实现的门当作已通过** ——
那正是 §4.1 与 I1 要禁止的「没验证当成通过」。

**MUST**：未实现/仅流程的门**必须**进入总体裁决，贡献 `UNKNOWN`。
**MUST NOT** 为使其变绿而：实现临时 check、加虚拟 check、
拿 D6 benchmark 充当门 3、或降低门 3 的 Contract。

---

## 2. 问 2：四态 → 总体 CI 状态

**当前实现是二值的**（`RESULT: PASS` / `RESULT: BLOCKED`，exit 0/1），
不产出四态总体裁决。**提案：总体也用四态，且退出码可区分。**

### 2.1 映射规则（提案，按优先级自上而下）

| 优先级 | 条件 | 总体状态 | exit |
| --- | --- | --- | --- |
| 1 | 任一 gate = `REGRESSION` | **`FAIL_REGRESSION`** | **2** |
| 2 | 无 regression，但任一 = `INFRASTRUCTURE_FAILURE` | **`BLOCKED_INFRA`** | **3** |
| 3 | 无上二者，但任一 = `UNKNOWN` 或 `NOT_IMPLEMENTED` | **`NEEDS_REVIEW`** | **4** |
| 4 | 全部 `PASS`，且 §4 五门**全部** `IMPLEMENTED` | **`PASS`** | **0** |

**MUST**：退出码**按状态区分**（0/2/3/4），使外层无需解析文本即可分支。
当前二值实现（恒 1）**丢失了 regression 与 infra 的区别**，
这与 I3「三者必须可区分」冲突 —— 属本阶段发现的缺口。

**MUST NOT**：`NEEDS_REVIEW` 与 `PASS` 共用退出码。
**MUST NOT**：`BLOCKED_INFRA` 与 `FAIL_REGRESSION` 共用退出码。

### 2.2 依此规则的**当前实际结果**

门 3 = `NOT_IMPLEMENTED` → 落入优先级 3 →

```
总体 = NEEDS_REVIEW (exit 4)
原因 = §4 门 3 (NOT_IMPLEMENTED), §4 门 4 (PROCESS_ONLY)
```

> **即：现在把 release_gate 接上，CI 也不会是绿的。**
> 这是正确的诚实结果，不是待修的 bug。

---

## 3. 问 3：未实现的 Gate 3 如何显示

**MUST** 以独立状态呈现，**MUST NOT** 折叠为 `PASS`：

| 字段 | 值 |
| --- | --- |
| `gate_id` | `cold_warm_equivalence` |
| `state` | **`NOT_IMPLEMENTED`** |
| `contributes` | **`UNKNOWN`** |
| `required_execution` | `true`（它是 §4 声明的门） |
| `executed` | `0` |
| `spec_ref` | `docs/GATE3-COLD-WARM-CONTRACT.md` |
| `note` | 语义已定义、证据已采、**检查未实现**；五项覆盖缺口见该文件 §8 |

**MUST NOT** 把 `NOT_IMPLEMENTED` 归入 `PROCESS_ONLY`：
门 4 是「规范要求人工流程」，门 3 是「规范要求自动检查但尚未写」——
两者缺失原因不同，报告必须能区分。

**MUST NOT** 在门 3 处输出任何形式的 `PASS`、`SKIPPED (optional)` 或静默省略。

---

## 4. 问 4：execution accounting 的四种情形

| 情形 | 会计字段 | 裁决 | 是否内容结论 |
| --- | --- | --- | --- |
| **skipped**（测试内 skip） | `skipped>0` | `UNKNOWN` | ❌ 无（被跳过部分） |
| **未执行**（0 executed） | `executed==0` | `INFRASTRUCTURE_FAILURE` | ❌ 无 |
| **环境缺失** | `missing_prerequisites[]` 非空 | `INFRASTRUCTURE_FAILURE`（**运行前**判定） | ❌ 无 |
| **测试 discovery 异常** | `discovery_anomaly=true` | **`INFRASTRUCTURE_FAILURE`** | ❌ 无 |

### 4.1 ⚠️ 新发现：discovery 异常当前被误判为 `REGRESSION`

实测（一个正常模块 + 一个 `import nonexistent` 的模块）：

```
Ran 2 tests in 0.000s
FAILED (errors=1)
ERROR: test_broken          ← traceback 含 unittest.loader / _FailedTest
```

按已交付的 `release_gate.py`：total=2、errors=1、skipped=0 → executed=2 →
**判为 `REGRESSION`**。

> **这是错的。** 测试模块 import 失败是**测试基础设施问题**，
> 不是渲染内容回归。判成 `REGRESSION` 会：
> ① 违反 I3「infrastructure failure 必须与 regression 可区分」；
> ② 误导排查方向（去找一个不存在的渲染回归）。

### 4.2 可机械区分的判别式（已验证）

| 输出中的信号 | 含义 |
| --- | --- |
| `unittest.loader` / `_FailedTest` 出现在 error traceback | **discovery 异常** → `INFRASTRUCTURE_FAILURE` |
| `FAIL: <真实测试名>` | 内容失败 → `REGRESSION` |
| `ERROR: <真实测试名>` 且**无** loader 信号 | 测试体内异常 → `REGRESSION` |
| `Ran 0 tests` + `NO TESTS RAN` | 完全未执行 → `INFRASTRUCTURE_FAILURE`（已被 I1 覆盖） |

**MUST**：分类器读取 **error/FAIL 的身份**，不只读计数。
**MUST NOT** 仅凭 `errors>=1` 判为 `REGRESSION`。

> **归属**：这是对**已交付** `release_gate.py` 的缺陷发现。
> **本阶段不修**（Phase 2 范围）；记录于此，供 Phase 2 纳入。

---

## 5. 问 5：release-blocking vs diagnostic

| 类别 | 成员 | 裁决权 |
| --- | --- | --- |
| **release-blocking** | §4 门 1（unit / transport / integration）<br>§4 门 2（boundary audit）<br>§4 门 5（fork integrity） | 可阻断 |
| **不可 blocking（但必须可见）** | §4 门 3（`NOT_IMPLEMENTED`）<br>§4 门 4（`PROCESS_ONLY`） | 不可阻断 —— **无可执行物**；但贡献 `UNKNOWN` 使总体无法 `PASS` |
| **diagnostic（不在 gate 集合）** | `bench.py` / `bench_transport.py` / `session_bench.py`<br>`mcp_smoke.py` / `mcp_call.py` / `ide_smoke.py`<br>`workload_run.py` / `workload_corpus.py`<br>`d4_evidence_probe.py` / `reasoning_bench.py` / `diff_closure.py` | 不参与裁决 |

**判据**（与 Q1 认可项一致）：**会因机器差异而非缺陷失败的，一律不是门禁。**
D6 的「measured / NOT A GATE」由此机械化（已有对照
`test_no_benchmark_is_a_release_gate`）。

**MUST NOT** 把 diagnostic 项纳入总体裁决。
**MUST NOT** 因某个 diagnostic 失败而使总体非 `PASS`。

---

## 6. 问 6：报告必须能证明每个要求执行的 gate **实际执行过**

### 6.1 每个 gate 的必备会计字段（提案）

| 字段 | 含义 |
| --- | --- |
| `gate_id` / `spec_gate` | 检查 id / 对应 §4 门号 |
| `state` | `IMPLEMENTED` / `NOT_IMPLEMENTED` / `PROCESS_ONLY` |
| `required_execution` | 是否要求实际执行 |
| `attempted` | 是否被尝试运行 |
| `executed` | **实际执行的检查数** |
| `skipped` / `failures` / `errors` | 计数 |
| `discovery_anomaly` | discovery 异常标记（§4.1） |
| `missing_prerequisites` | 缺失前置清单 |
| `exit_code` / `duration_s` | 过程证据 |
| `outcome` | 四态之一 |
| `evidence_ref` | 可复查的产物路径 |

### 6.2 MUST 成立的不变式

```
∀ gate: required_execution = true
     → executed > 0            否则 run 不得为 PASS
     → attempted = true        否则不得为 PASS
```

**MUST**：报告为**机器可读**（JSON），文本仅作人读摘要。
**MUST NOT** 只输出人类可读文本作为唯一证据 ——
那正是 A2-1 的形态（「exit 0」不等于「验证过」）。

**MUST NOT**：任何 gate 的 `executed` 缺失或不可解析时**默认按 0 处理**，
不得「解析失败即视为通过」。

---

## 7. 问 7：fork-integrity audit 如何被消费（不复制逻辑）

| 规则 | 约束 |
| --- | --- |
| **MUST** | orchestration 以**子进程调用** `python scripts/audit_fork_integrity.py`，消费其**退出码** |
| **MUST NOT** | 在 orchestration 内**重新实现** F1–F4 任何一条 |
| **MUST NOT** | 复制 `_classify_hunk` / `_verify_provenance` 等实现 |

**理由**：
① `audit_fork_integrity.py` 已有 **22 项自身对照**，
复制会立刻产生第二份无对照的逻辑；
② F3 曾在**真实数据**上抓出我自己的过度声明 ——
那类判别力来自它与冻结产物的直接耦合，复制即失效；
③ 复制会漂移，且 §2.1.1 条件 3 的「作用面按结构判定」极易在副本中被简化。

**当前状态**：已交付的 `release_gate.py` **已是子进程调用**
（`command: ["python", "scripts/audit_fork_integrity.py"]`），
**无需改动** —— 本条是对现状的固化，不是新工作。

---

## 8. 本阶段发现的两个缺口（**均未修**）

| # | 缺口 | 归属 |
| --- | --- | --- |
| G1 | 总体裁决为**二值**（exit 恒 1），丢失 regression 与 infra 的区分 | Phase 2（§2.1） |
| G2 | **discovery 异常被判为 `REGRESSION`** | Phase 2（§4.1 / §4.2） |

**两者都不在本次授权内**，仅记录。

---

## 9. 本阶段未做

未写 `.github/workflows` / Jenkins / Azure 或任何 pipeline 配置；
未接线 release blocking；未实现 Gate 3；未把门 3 转成 `PASS`；
未为门 3 添加临时或虚拟 check；未把 D6 benchmark 当门 3；
未降低门 3 的 Contract；未改 `ci.py`（§4.1 冻结不变）；
未改 `audit_fork_integrity.py`；未改测试 harness。

**Gate 3 状态保持：`DEFINED / EVIDENCE COLLECTED / NOT IMPLEMENTED`**
（五项覆盖缺口继续冻结在 `docs/GATE3-COLD-WARM-CONTRACT.md` §8，
尤其 **cross-worker recycle** 与 **`include_shader_values=True`**）。
