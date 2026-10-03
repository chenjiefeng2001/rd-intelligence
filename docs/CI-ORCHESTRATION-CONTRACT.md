---
document_role: contract
freshness_policy: mixed
document_living_preamble: true
document_default_policy: historical
document_living_sections:
  - "0. 本阶段确立的 Contract 基础"
  - "1. 问 1：五个 §4 Gate 的执行入口与当前状态"
  - "2. 问 2：四态 → 总体 CI 状态"
  - "3. 问 3：无可执行物的门如何显示"
  - "4. 问 4：execution accounting 的四种情形"
  - "5. 问 5：release-blocking vs diagnostic"
  - "6. 问 6：报告必须能证明每个要求执行的 gate **实际执行过**"
  - "7. 问 7：fork-integrity audit 如何被消费（不复制逻辑）"
  - "真实状态"
document_mixed_note: >-
  本文档同时承担规范契约与阶段历史记录。上述 section 为 living
  区域；其余 section（§8/§9/§10 及其子节）按
  document_default_policy 为 historical。开篇摘要按
  document_living_preamble: true 属于 living，其中 L5 的三处错误
  断言因此已进入待修正范围，本阶段不动文案。
  注：§4 声明为 living 后，其子节「4.1 · 新发现：discovery
  异常当前被误判」一并落入 living（该缺口已修，标题过时）。
---
# CI integration Phase 1：orchestration Contract

日期：2026-09-29（Contract）；状态刷新 2026-10-02。
授权范围：**仅 orchestration Contract**（7 问）。

**当前状态（2026-10-02 实测）**：pipeline 配置已写并接线
（`scripts/ci_pipeline.py` + `ci-pipeline.json`，门数、exit 映射与 readiness 组合均已落地）；
**§4 门 3 已实现**（`scripts/cold_warm_gate.py`，blocking，实测 `PASS`）；
**release blocking 仍未启用且未获授权**（`release_blocking_enabled: false`）——
这是**裁决状态**，不是「未接线」。

回答的问题只有一个：

> **「CI 应该怎样解释现有 gates？」**

而不是：

> **「CI 现在开始强制这些 gates。」**

> 当前编排层已对全部七个门产出裁决并据此退出
> （现为 `BLOCKED_INFRA / exit 3`），但**尚未对 release 形成阻断**——
> 后者仍需单独授权，且受 integration 门未干净退出的问题阻塞。

---

## 0. 本阶段确立的 Contract 基础

| 基础 | 状态 |
| --- | --- |
| §4.1 verdict semantics | **FROZEN** |
| harness I1/I2 | **已授权 / 可验证**（`scripts/release_gate.py`） |
| regression / unknown / infrastructure 三分 | **已定义**（Q3 裁决） |
| §2.1 fork-integrity audit | **可执行**（18 项对照 + 1 条已记录 deviation） |
| Gate 3 语义定义 | **DEFINED**（`docs/GATE3-COLD-WARM-CONTRACT.md`）<br>语义定义之外**已实现**并接入编排层（coverage 为 bounded） |
| **Gate 3 可执行检查** | **NOT IMPLEMENTED** |

---

## 1. 问 1：五个 §4 Gate 的执行入口与当前状态

**执行矩阵**（`§4` 五门 ↔ 实际可执行物）：

| §4 门 | 执行入口 | 检查数 | 状态 |
| --- | --- | --- | --- |
| **1** 测试全绿 | `unittest discover -s tests/unit`<br>`-s tests_transport`<br>`-s tests/integration -t .` | **3** | **IMPLEMENTED** |
| **2** 边界审计 | `python scripts/audit_boundaries.py` | 1 | **IMPLEMENTED** |
| **3** cold==warm 等价 | `python scripts/cold_warm_gate.py <capture> --json .gate3_verdict.json` | 3 | **IMPLEMENTED**<br>（`debug_pixel` / `diff_pixel` / `diff_pixel_shader_values`）<br>⚠️ **bounded coverage** —— 不等于完整证明 |
| **4** benchmark 存档 | **无可执行检查** | 0 | ⚠️ **PROCESS_ONLY**<br>（规范为流程要求，无自动判定路径） |
| **5** fork 零 tracked mod | `python scripts/audit_fork_integrity.py` | 1 | **IMPLEMENTED** |

合计：**6 个可执行检查**（对应 §4 门 1/2/3/5，其中门 1 含 3 个执行入口），**1 个无可执行物**（门 4）。

### 1.1 ⚠️ 必须点明的治理后果

> **只要门 4 无可执行物，总体 CI 状态就不可能是 `PASS`。**

这不是缺陷，而是正确结果：
`§4` 声明了五个门，其中门 4 **没有实现**（流程要求，无自动判定路径）；
声称「CI 全绿」等于**把未实现的门当作已通过** ——
那正是 §4.1 与 I1 要禁止的「没验证当成通过」。

> 门 3 曾长期处于 `NOT_IMPLEMENTED`，现已实现并接入 `cold_warm_gate.py`。
> 但其覆盖是 **bounded**，因此 §1 的状态列标注为 `IMPLEMENTED`
> **不等于**「门 3 已被完整证明」，也不等于 release safe。

**MUST**：未实现/仅流程的门**必须**进入总体裁决，贡献 `UNKNOWN`。
实现细节上，总体裁决对**全部已声明门**的 `outcome` 取值，
**不因某门标了 `blocking: false` 而将其排除** —— 门 4 正是如此：
它不阻断单门执行，但其 `UNKNOWN` 仍把总体压到 `NEEDS_REVIEW`。
**MUST NOT** 为使其变绿而：实现临时 check、加虚拟 check、
拿 D6 benchmark 充当门 3、或降低门 3 的 Contract。

---

## 2. 问 2：四态 → 总体 CI 状态

**当前实现已产出四态总体裁决**，四态退出码互不相同：
`PASS` / `FAIL_REGRESSION` / `BLOCKED_INFRA` / `NEEDS_REVIEW`。

**exit 映射的唯一可执行来源是 `scripts/release_gate.py` 的 `EXIT_CODES`。**
本节陈述四态**存在**与**判别顺序**；下方 §2.1 表格中的数字是**契约表述**，
不属于独立来源 —— 若在别处再写一份映射，就会出现要避免的双事实：
`代码: BLOCKED_INFRA → 3` 与 `文档: blocked → 1` 并存。
§2.1 与 §10 各有一份契约表述的映射表；**当前无自动控制校验这两份表与
`release_gate.py` 的 `EXIT_CODES` 三者一致** —— 已记为待办。

### 2.1 映射规则（按优先级自上而下）

| 优先级 | 条件 | 总体状态 | exit |
| --- | --- | --- | --- |
| 1 | 任一 gate = `REGRESSION` | **`FAIL_REGRESSION`** | **2** |
| 2 | 无 regression，但任一 = `INFRASTRUCTURE_FAILURE` | **`BLOCKED_INFRA`** | **3** |
| 3 | 无上二者，但任一 = `UNKNOWN` 或 `NOT_IMPLEMENTED` | **`NEEDS_REVIEW`** | **4** |
| 4 | 全部 `PASS`，且 §4 五门**全部** `IMPLEMENTED` | **`PASS`** | **0** |

**MUST**：退出码**按状态区分**，使外层无需解析文本即可分支。

本条针对的是**本阶段修复之前**的实现：当时总体裁决为二值且恒返回 1，
丢失了 regression 与 infra 的区别，与 I3「三者必须可区分」冲突。
该缺口已修（见 §10 G1）。下方表格中的数字是**契约表述**，
其唯一可执行来源是 `scripts/release_gate.py` 的 `EXIT_CODES`。

**MUST NOT**：`NEEDS_REVIEW` 与 `PASS` 共用退出码。
**MUST NOT**：`BLOCKED_INFRA` 与 `FAIL_REGRESSION` 共用退出码。

### 2.2 依此规则的**当前实际结果**

`integration` = `INFRASTRUCTURE_FAILURE` → 落入优先级 2 →

```
总体 = BLOCKED_INFRA (exit 3)
原因 = integration（63 项测试报 OK，但进程 exit 3221225477 / 0xC0000005）
```

门 4 仍为 `PROCESS_ONLY` → `UNKNOWN`；若 integration 干净退出，
它将使总体落入优先级 3 的 `NEEDS_REVIEW (exit 4)`。
`UNKNOWN` 不会掩盖 `INFRASTRUCTURE_FAILURE` —— 优先级顺序正在此处生效。

> **即：release_gate 已接线，CI 仍不是绿的，但原因已经变了。**
> 早前此处的原因是门 3 / 门 4 没有可执行物；门 3 现已实现。
> 当前非 `PASS` 的原因是 integration 进程未干净退出，
> 这是正确的诚实结果，不是待修的 style 问题 ——
> 真正待修的是该进程退出本身（teardown 归因仍 `NOT_ESTABLISHED`）。

---

## 3. 问 3：无可执行物的门如何显示

**MUST** 以独立状态呈现，**MUST NOT** 折叠为 `PASS`。
现行例为 **§4 门 4（`benchmark_archive`）** —— 门 3 已实现，不再适用：

| 字段 | 值（门 4 实测） |
| --- | --- |
| `gate_id` | `benchmark_archive` |
| `state` | **`PROCESS_ONLY`** |
| `contributes` / `outcome` | **`UNKNOWN`** |
| `required_execution` | `false`（规范为流程要求，非自动判定路径） |
| `attempted` | `false` |
| `executed` | `0` |
| `blocking` | `false` |
| `note` | 规范要求 session 与 latency 数据归档；无自动判定路径 |

**MUST NOT** 把 `NOT_IMPLEMENTED` 归入 `PROCESS_ONLY`：
门 4 是「规范要求人工流程」，而 `NOT_IMPLEMENTED` 是
「规范要求自动检查但尚未写」—— 两者缺失原因不同，报告必须能区分。

**MUST NOT** 在无可执行物的门处输出任何形式的 `PASS`、
`SKIPPED (optional)` 或静默省略。

> **MUST NOT** 折叠 `blocking: false` 的门对总体裁决的影响：
> 门 4 虽 `blocking: false`，其 `UNKNOWN` 仍使总体无法 `PASS`
> （`release_gate.py` 的 `outcomes` 取全部已声明门，不按 `blocking` 过滤）。

---

## 4. 问 4：execution accounting 的四种情形

| 情形 | 会计字段 | 裁决 | 是否内容结论 |
| --- | --- | --- | --- |
| **skipped**（测试内 skip） | `skipped>0` | `UNKNOWN` | ❌ 无（被跳过部分） |
| **未执行**（0 executed） | `executed==0` | `INFRASTRUCTURE_FAILURE` | ❌ 无 |
| **环境缺失** | `missing_prerequisites[]` 非空 | `INFRASTRUCTURE_FAILURE`（**运行前**判定） | ❌ 无 |
| **测试 discovery 异常** | `discovery_anomaly=true` | **`INFRASTRUCTURE_FAILURE`** | ❌ 无 |

### 4.1 缺陷发现：discovery 异常会被误判为 `REGRESSION`（**已修**）

> 标题原为「新发现：discovery 异常**当前**被误判」。该缺口已由 Phase 2 的 G2
> 修复，因此「当前」不再成立；下文的实测与其判定过程作为**发现时的记录**保留。

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

> **归属**：这是对**已交付** `release_gate.py` 的缺陷发现，
> 记录于本阶段并**已由 Phase 2 的 G2 修复** —— 分类器现读取 error/FAIL 的身份，
> 不再只凭计数。上文 §4.1 的实测与「判为 `REGRESSION`」的结论描述的是修复**之前**的行为。

---

## 5. 问 5：release-blocking vs diagnostic

| 类别 | 成员 | 裁决权 |
| --- | --- | --- |
| **release-blocking** | §4 门 1（unit / transport / integration）<br>§4 门 2（boundary audit）<br>§4 门 3（cold==warm 等价）<br>§4 门 5（fork integrity） | 可阻断 |
| **不可 blocking（但必须可见）** | §4 门 4（`PROCESS_ONLY`） | 不可阻断 —— **无可执行物**；但贡献 `UNKNOWN` 使总体无法 `PASS` |
| **diagnostic（不在 gate 集合）** | `bench.py` / `bench_transport.py` / `session_bench.py`<br>`mcp_smoke.py` / `mcp_call.py` / `ide_smoke.py`<br>`workload_run.py` / `workload_corpus.py`<br>`d4_evidence_probe.py` / `reasoning_bench.py` / `diff_closure.py` | 不参与裁决 |

**判据**（与 Q1 认可项一致）：**会因机器差异而非缺陷失败的，一律不是门禁。**
D6 的「measured / NOT A GATE」由此机械化（已有对照
`test_no_benchmark_is_a_release_gate`）。

**MUST NOT** 把 diagnostic 项纳入总体裁决。
**MUST NOT** 因某个 diagnostic 失败而使总体非 `PASS`。

---

## 6. 问 6：报告必须能证明每个要求执行的 gate **实际执行过**

### 6.1 每个 gate 的必备会计字段（**已实现**）

字段名以实现为准；本表是契约表述与实际字段的**映射**，不是第二份字段清单。
两个方向的偏差都由 `test_declared_accounting_fields_exist_in_the_report` 约束。

| 契约要求 | 实际字段 | 状态 |
| --- | --- | --- |
| `gate_id` | `gate` | 重命名 |
| `state` | `state` | 一致 |
| `required_execution` | `required_execution` | 一致 |
| `attempted` | `attempted` | 一致 |
| `executed` | `executed` | 一致 |
| `exit_code` | `exit_code` / `process_exit_code` / `execution_clean` | 实现给出三项，均为派生值 |
| `outcome` | `outcome` | 一致 |
| `skipped` / `failures` / `errors` | `tests_executed` / `tests_failed` / `tests_errors` | 更精确的命名 |
| `discovery_anomaly` | `discovery_anomaly`（布尔）与 `discovery_anomalies`（身份列表） | **本轮补齐** |
| `missing_prerequisites` | `missing_prerequisites` | **本轮补齐** |
| —（契约未声明，实现已有） | `blocking` / `command` / `detail` / `spec_ref` / `spec_gate` / `test_result` / `lint` | 已登记 |

**为什么有些字段是「实现回到契约」而不是反过来。**
`missing_prerequisites` 与 `discovery_anomaly` 此前**只以散文存在于 `detail`**。
§6.2 的不变式只依赖 `executed` / `attempted` / `required_execution` / `state`，
因此它们不承载任何 PASS/FAIL 不变式；但它们承载**诊断**：报告要能区分
「因环境缺失而未运行」与「运行了且失败」。散文不是同一事实的弱形式，
散文是一个机器读不到的事实。故这两个字段由实现补齐。

**为什么其余方向是契约跟随实现。** `gate_id` → `gate` 是纯改名，实现侧的名字
被全部报告与控制引用；`skipped/failures/errors` → `tests_*` 是同一意图的更精确
命名。让文档去匹配实现，而不是反过来改名去匹配一份已冻结的提案。

**两项契约要求已撤销（裁决，非补实现）**：

* `evidence_ref` —— 实现从未产生该字段，§6.2 不依赖它，且它未承载任何
  当前裁决所需的事实。长期保留一个实现永不兑现的 mandatory declaration
  只会制造 schema drift，故**从 mandatory report contract 中移除**。
* `duration_s` —— 同上。特别说明：**不**为「字段已声明」而补一个未被语义
  使用的计时器 —— 那会把非必要 telemetry 变成新的事实来源。

这是**契约收窄**，不是实现缺失。两项的移除各有独立控制
（`test_evidence_ref_is_not_a_contract_requirement` 与
`test_duration_s_is_not_a_contract_requirement`），以免一个删除动作
掩盖另一个字段；且移除必须被记录，而非静默删去。

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

### 6.1 unit gate 的环境 prerequisite（U1 裁决）

`unit` 是 required 且 blocking 的门。它在**两类**环境条件下得不到内容结论，
二者都**不是** semantic failure：

| 环境条件 | 机制 | 实测结果 |
| --- | --- | --- |
| RenderDoc 模块不可导入 | `tests/unit/test_cold_warm_gate.py` 的三项 `skipTest("renderdoc module not importable")` | 有环境：`executed=478` → `PASS`；无环境：`executed=475`、3 skipped → **`UNKNOWN`** |
| capture 不存在 | 同文件 `skipTest("capture not present")` | 计入 skipped，效果同上 |

`UNKNOWN` 的 detail 为 `N of M tests skipped; no content conclusion for the
skipped part`。

**MUST NOT** 把「环境不可用」读成 semantic PASS 或 FAIL；**MUST NOT** 把它与
`integration` 门 onexit 阶段的 `0xC0000005`（teardown 缺陷）混为同一故障 ——
后者是独立工作流。

### 6.2 unit verdict 不变量（回归钉子）

以下三条是**不变量**，由 `tests/unit/test_unit_gate_verdict_invariants.py` 以
**真实 unittest 运行**（非 mock）钉住：

1. **`executed == 0` 绝不判 `PASS`** —— 该检查先于任何可达 `PASS` 的分支。
2. **`executed < min_executed` 判 `INFRASTRUCTURE_FAILURE`**（`unit` 声明 floor
   为 100），fail-closed。
3. **`skipped > 0` 判 `UNKNOWN` 而非 `PASS`**，且 `UNKNOWN ∈ BLOCKING`。

由此：**required 门在环境缺失、或整个 suite 被跳过时，都不可能被读成通过。**
这是既有设计行为，**不是** defect。

**已知可解释性边界**：总体 precedence 为
`REGRESSION > INFRASTRUCTURE_FAILURE > UNKNOWN`，故当 `integration` 同时为
`INFRASTRUCTURE_FAILURE` 时，`unit` 的 `UNKNOWN` 在 `overall` 中被掩盖，仅保留在门禁行。
该组合**已实测**；「`unit = UNKNOWN` 且 `integration = PASS` → `exit 4`」
**仅为归约推导，未测量**，不得写成真实运行结果。

本节裁决为 **U1：维持现状 + 文档化**。不改 accounting 表达、不改四状态、不把
`UNKNOWN` 从 `overall` 中提出、不改 skip 条件、不新增 gate。

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

| # | 缺口 | 归属 | 状态 |
| --- | --- | --- | --- |
| G1 | 总体裁决为**二值**（exit 恒 1），丢失 regression 与 infra 的区分 | Phase 2 | ✅ **已修**（见 §10） |
| G2 | **discovery 异常被判为 `REGRESSION`** | Phase 2 | ✅ **已修**（见 §10） |

**两者在 Phase 1 均未修，仅记录；Phase 2 已修（见 §10）。**

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


---

## 10. Phase 2：G1 + G2 已修（编排层，未接线）

### G1 —— 四态总体裁决，退出码一一对应

| 条件 | 总体状态 | exit |
| --- | --- | --- |
| 任一 `REGRESSION` | `FAIL_REGRESSION` | **2** |
| 无 regression，任一 `INFRASTRUCTURE_FAILURE` | `BLOCKED_INFRA` | **3** |
| 无上二者，任一 `UNKNOWN` / `NOT_IMPLEMENTED` | `NEEDS_REVIEW` | **4** |
| 全 `PASS` 且 §4 五门全 `IMPLEMENTED` | `PASS` | **0** |

`PASS` 另有两道保险：`required_execution` 且未实现的门不得为 PASS；
`required_execution` 且 `executed == 0` 的门也不得为 PASS。

### G2 —— discovery 异常不再冒充 regression

判别式**按 test id 全文**，不按输出文本搜索：

```
ERROR: test_broken (unittest.loader._FailedTest.test_broken)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

`RESULT_HEADER` 捕获 `^(ERROR|FAIL): (.+)$` 的**完整 id**；
含 `unittest.loader._FailedTest` 者 → `INFRASTRUCTURE_FAILURE`；
否则（`FAIL: test_mod.C.test_a`、`ERROR: test_mod.C.test_a`）
→ `REGRESSION`。

> Phase 1 探测时用 `(\S+)` 抽取，**在空格处截断**，恰好漏掉这个决定性
> token。修正为捕获完整 id 后，判别式既精确又**不会误吞真实失败**。

**分类顺序**：`executed==0`（I1）→ 低于下限（I1）→ discovery 异常（G2）
→ failures/errors（内容侧）。discovery 异常**必须优先于**错误计数，
因为一个 import 失败会抬高 `errors`，若先看计数就会被判为内容回归。

### 声明文件升版 `/1 → /2`

新增 `spec_gate` / `state` / `required_execution` / `blocking` / `exit_codes`。
**§4 门 3 声明为 `NOT_IMPLEMENTED`、门 4 声明为 `PROCESS_ONLY`**，
两者 `command: null`、`contributes: UNKNOWN` —— 编排层因此**看得见**
它们没有可执行物。

**控制** `test_unimplemented_gates_have_no_command` 断言未实现的门
**不得携带任何 command**。这把「不得加临时或虚拟 check、
不得用 D6 替代门 3」从**审查纪律**变成**结构约束**。

### 对照：24 → **43**

| 组 | 项 |
| --- | --- |
| G2 | discovery→INFRA、discovery 被记录、**真实 FAIL 仍 REGRESSION**、**真实测试体内 ERROR 仍 REGRESSION**、两者混合→INFRA、判别式窄（普通 module path 不匹配） |
| G1 | regression 优先、infra 优先于 unknown、unknown→NEEDS_REVIEW、全 PASS 且全实现→PASS、未实现的门阻止 PASS、未实现的门报 UNKNOWN 而非 PASS、已运行但 `executed=0` 阻止 PASS、**退出码一一对应**、**真实 spec 今天=NEEDS_REVIEW 且点名门 3/4**、报告机器可读 |
| spec | 未实现的门无 command、门 3/4 已声明、退出码互不相同 |

### 回退验证

```
G1（二值）+ G2（discovery 强制）同时失效   8 FAIL
恢复                                        43 OK
```

### 真实状态

事实源：`ci_pipeline_report.json`（本轮实测）。
本节会随实现推进而过期；其陈旧度由 `docs/CURRENT-EVIDENCE-FREEZE.md` 的
`baseline_drift` 与状态层控制共同约束。

```
unit                    IMPLEMENTED / PASS                        402 executed
transport               IMPLEMENTED / PASS                         58 executed
integration             IMPLEMENTED / INFRASTRUCTURE_FAILURE        63 executed
                        （63 项测试报 OK，但进程 exit 3221225477 / 0xC0000005）
boundary_audit          IMPLEMENTED / PASS                         exit 0
cold_warm_equivalence   IMPLEMENTED / PASS（bounded coverage）
fork_integrity          IMPLEMENTED / PASS                         exit 0
benchmark_archive       PROCESS_ONLY / UNKNOWN / 不 blocking         0 executed
------------------------------------------------------------------
RESULT: BLOCKED_INFRA (exit 3, conclusion failure)
release blocking enabled: False        accounting_consistent: True
```

> **总体非 PASS 的原因已经变了。** 早前此处记为 `NEEDS_REVIEW (exit 4)`，
> 理由是门 3 / 门 4 无可执行物。门 3 现已实现并 `PASS`，门 4 仍为
> `PROCESS_ONLY`。当前非 `PASS` 的原因是 **integration 门进程未干净退出**，
> 按四态映射归为 `BLOCKED_INFRA (3)`，**不是** `NEEDS_REVIEW`。
>
> 该门 63 项测试**报告 OK**，与进程 exit `3221225477` 是两个独立事实，
> 二者同时成立并都如实记录。这正是执行记账分离的用途：
> **不得因测试全绿而把该门改写为 `PASS`。**
>
> 四态判别仍然成立：退出码互不相同（`PASS` 0、`FAIL_REGRESSION` 2、
> `BLOCKED_INFRA` 3、`NEEDS_REVIEW` 4），regression / infrastructure /
> unknown 不再压成同一个 exit。

### Phase 2 未做

未写 pipeline、未接线 release blocking、未实现门 3、未实现 benchmark 门、
未改 `ci.py`、未改 `audit_fork_integrity.py`、未改测试 harness、
未新增虚拟或最小 fake check、未用 D6 替代门 3、未改门 3 Contract、
未追 nested-action capture。
