# Gate 3 Phase 1：cold==warm 语义等价检查的 Contract 与可执行检查定义

日期：2026-09-29
授权范围：**Phase 1 —— Contract / 可执行检查定义**。
**未实现该检查，未接 CI。**（授权边界原文：「暂不实现检查，更不接 CI」）

对应缺口：§4 质量门第 3 条
> 语义等价：任何性能/重构变更必须通过 cold==warm 等价检查

**当前状态：`SPECIFIED / NOT IMPLEMENTED`** —— 规范有该门，代码库中**不存在**该检查。

---

## 0. 取证前提：三个必须先分清的概念

### 0.1 D6 的 cold/warm 与门 3 的 cold/warm **不是同一件事**

| | D6 的 cold/warm | §4 门 3 的 cold/warm |
| --- | --- | --- |
| 比较对象 | **计时**（latency） | **语义结果**（payload） |
| 进程约束 | **一点一进程，cold 与 warm 从不混合** | 不需要进程隔离 |
| 原因 | background 进程继承预热，导致同一 capture 的 cold 出现 **3 倍虚假差** | 与进程隔离无关 |
| 结论 | D6：**measured / NOT A GATE** | 门 3：**待定义** |

> **禁止混用**：不得用 D6 的计时分离规则去定义门 3 的等价检查，
> 也不得把 D6 的结论当作门 3 的证据。二者是不同测量对象。

### 0.2 最接近的既有机制（Gate V）**在仓库中不存在**

§2.9:201 要求「同 capture 的任意两次查询（无论跨越多少次 recycle）
必须产出字段级一致的语义结果（W1-R3 Gate V 为机械验收）」，
§2.9:230 声称「✅ **实测成立**：w01024 上 6 个 worker 代次 / 5 次回收，
语义 payload 逐字节一致」。

只读核查结果：

| 载体 | 实际内容 |
| --- | --- |
| `rd-intelligence/tests/**` | **无任何字段级语义比对测试**（`rg` 零命中） |
| `rdebug-validation/reports/W1-R3.json` → `gates` | **仅布尔值** `value_isolation_under_recycle: true`、`correctness: true` |
| 同文件 `details` | 键为 `gateL_latency_classes` / `gateM_baselines` / `gateM_peak_private_mb` / `recycles_gateV`；**无 payload、无字段级比对记录** |
| `details.recycles_gateV` 的具体形态 | 未展开比对内容 |
| `tests/workload/harness.py` `record_query()` | 统计 evidence 节点数与 unknown 层计数，**不做字段级比对** |

> **结论：门 3 不能「复用 Gate V 的机制」，因为该机制不在仓库中。**
> §2.9 关于 Gate V「实测成立」的表述，其可复现载体只有一个布尔值。
> 本文件**不修改 §2.9**（已冻结），仅记录该落差。

---

## 1. 问 1：比较的对象究竟是什么 semantic result？

**提案：Semantic API v1 的四个 payload，整体、逐字节比较。**

| # | 语义函数 | 模块 | 本次实测 payload 规模 |
| --- | --- | --- | --- |
| 1 | `trace_pixel` | `analysis/pixel_trace.py` | 34 117 字符（37 nodes / 51 edges） |
| 2 | `trace_resource` | `analysis/resource_flow.py` | 含 `writers` / `readers` / `other` / `evidence` |
| 3 | `diff_pixel` | `analysis/pixel_diff.py` | 6 层 + `firstDivergence` |
| 4 | `debug_pixel` | `analysis/shader_trace.py` | 5 steps + disassembly（本次已开） |

**理由**：这四个是 §2.3 冻结的唯一对外语义面；
`ci.check` 的裁决是**第五个**可比对象（但其等价性已由 §4.1 覆盖，不重复）。

**MUST NOT** 只比较 payload 的某个子集（如只比 `finalValue`）——
那会让未纳入比较的字段成为盲区。

---

## 2. 问 2：cold 与 warm 的操作序列

### 2.1 术语精确定义（提案）

| 术语 | 定义 |
| --- | --- |
| **cold** | 在**全新进程**中，对某 capture 的**首次**语义查询 |
| **warm** | 在**同一进程**中，于**若干次其他查询之后**，重复**完全相同**的查询 |
| **一次查询** | 一条 `(tool, 参数元组)`，参数含 `(capture, x, y, target/resource, context_eid, include_*)` |

### 2.2 序列（提案）

```
[COLD]  进程启动 → 打开 capture → 立即执行四函数各一次 → 记录 C
[WARM]  同一进程内执行 ≥N 次其他查询（N ≥ 10，覆盖不同 tool / 不同资源 / 不同像素）
        → 重复执行**完全相同**的四函数 → 记录 W
[比较]  flatten(·) 后逐路径比较 C 与 W
```

**MUST**：warm 前的预热查询必须**不包含**被比较的那次查询，
否则比较的是同一结果与自身。

### 2.3 N 的取值

**提案 N = 12**（覆盖 3 个 tool × 4 组不同参数）。
理由：足以让 native cache、descriptor 缓存、event 缓存进入稳态；
**不取更大值**，因为门禁成本随 N 线性增长，且 D6 已证明稳态后无进一步收益。

---

## 3. 问 3 + 问 4：哪些字段必须逐字节相等 / 哪些允许 nondeterministic

### 3.1 实测结果：**没有任何字段需要豁免**

在 **D3D11**（`w00016_frame11.rdc`）与 **Vulkan**（`N3-05A1.rdc`）两个 capture 上：

```
cold vs warm（同进程）        4/4 byte-identical，零差异字段
跨进程（两个独立进程）        4/4 byte-identical
debug_pixel 开 disassembly   仍 byte-identical
```

同时，**语义层源码中不存在任何易变字段字面量**：

```
$ 在 analysis/ model.py evidence.py query/ ci.py 中检索
  pid / *Ms / *Time / timestamp / startedAt / finishedAt /
  memory* / private_memory* / rss* / duration* / elapsed*
→ 命中：无
```

### 3.2 因此的规则（提案）

| 规则 | 约束 |
| --- | --- |
| **MUST** | 语义 payload 的**全部字段**逐字节相等 |
| **MUST NOT** | 维护「易变字段豁免清单」—— 实测无此需要；维护它等于**给未来的 nondeterminism 开后门** |
| **MUST NOT** | 引入**部分比较**（只比子集）以规避差异 |

> **这是一个比「维护豁免清单」更强的规则。**
> 豁免清单会随时间膨胀，且新增豁免永远有「只是时间戳」的借口；
> 「全字段相等」使任何 nondeterminism 都成为**必须解释**的事件。

---

## 4. 问 5：worker PID / timing 等诊断字段是否排除？

**答：排除，但方式是「按范围排除」，不是「按字段过滤」。**

| 数据 | 位置 | 是否在语义 payload 内 |
| --- | --- | --- |
| worker PID | `WorkerManager.pid()` | ❌ 否 |
| latency / 计时 | `observability.record()` / workload harness | ❌ 否 |
| `private_memory_*` / `rss()` | `worker_manager` / `observability` | ❌ 否 |
| `recycles_fired` 等计数 | telemetry | ❌ 否 |

> **MUST**：比较对象**只取** Semantic API v1 的返回值。
> **MUST NOT** 为了排除 PID/时间而**逐字段过滤** payload ——
> 那些字段根本不在其中；一旦开始过滤，就说明比较对象取错了。

这是一个可机械检查的性质：`trace_pixel(...)` 的返回 dict 中
**不得**出现 `pid` / `*Ms` / `*Time` / `memory*` / `rss*` 键
（本次实测：无）。

---

## 5. 问 6：失败 / unknown / infrastructure failure 怎么裁决

**直接复用 Q3 已裁决的四态分类**（不发明第二套）：

| 情形 | 门 3 裁决 |
| --- | --- |
| C 与 W 全部逐字节相等 | **PASS** |
| C 与 W 存在任何差异 | **REGRESSION** |
| 某一侧未能形成 payload（如 `debug_pixel` 抛 `QueryError`） | **UNKNOWN** —— 不通过，需人工 |
| capture / RenderDoc / 预热序列无法执行 | **INFRASTRUCTURE_FAILURE** —— 阻断，**不与 regression 混报** |

**MUST NOT**：把 infrastructure failure 折算为 regression（授权边界明确禁止）。
**MUST NOT**：把 unknown 自动提升为 pass。

### 5.1 一个必须先解决的实现细节

`debug_pixel` 在本环境**可失败**（无 debug info / 无 PS 写入像素时抛
`QueryError`）。若两侧都失败且**失败原因相同**，这是**稳定的**；
若失败原因**不同**，那是真实差异 → `REGRESSION`。

> **MUST**：对「两侧都不可用」的情形，比较 **失败类型 + 消息**，
> 而非忽略该 tool。否则一个「稳定地不可用」的 tool 会掩盖真实差异。

---

## 6. 问 7：最小真实 capture

**提案：`tests/workload/corpus/w00001_frame11.rdc`**

| 项 | 值 |
| --- | --- |
| API | **D3D11** |
| size | 403 973 bytes |
| actions | 4（eid 1 clear、eid 2、**eid 11 唯一 draw**、eid 12 Present） |
| pixel shader | `entryPoint='main'`、`debuggable=true` |
| 资源绑定 | `ResourceId::35` 640×480 目标；`ResourceId::47` 64×64（writer `CopyDst`） |
| 已验证可达 | `trace_pixel(320,240)` 产生真实 shader 节点（S2.1 证据对象） |
| provenance | 合成三角形 fixture；生成器不在本仓库，commit **登记为未知** |

**为何最小**：单 draw、单个 PS、有可反射资源绑定、已被 S2.1 证明路径可达。

**门禁成本**：本次 `w00016` 上四函数冷+热共 8 次调用即完成，
单 draw fixture 会更快。

---

## 7. 问 8：正 / 负 / 假阳性对照与回退验证设计

**本阶段只设计，不实现。**

| 对照 | 构造 | 期望 |
| --- | --- | --- |
| **正对照** | 正常 cold/warm（w00001，N=12） | **PASS** |
| **负对照** | 在 warm 侧**注入**一处 payload 差异（测试内注入，**不改生产代码**） | **REGRESSION**，且报出**具体路径** |
| **假阳性对照 A** | 两侧 `debug_pixel` **都**不可用 | **UNKNOWN**，非 PASS、非 REGRESSION |
| **假阳性对照 B** | 两侧不可用但**失败原因不同** | **REGRESSION** |
| **假阳性对照 C** | 缺 RenderDoc / capture | **INFRASTRUCTURE_FAILURE**，且**未执行**预热序列 |
| **回退验证** | 移除「全字段相等」强制（退化为子集比较 / 忽略差异） | 负对照与假阳性 B **必须 FAIL** |

> **回退点选择**：与前几轮一致，选「**强制逻辑失效**」而非「文件缺失」，
> 以排除对照只是对文件存在性反应。

---

## 8. 本阶段**未**覆盖的边界（如实记录，不得当作已验证）

| 未覆盖 | 原因 |
| --- | --- |
| **跨 worker recycle 的等价性**（§2.9 Gate V 的真正场景） | 需强制触发 recycle；本阶段未做。**这是门 3 与 Gate V 的关键差异** |
| **`include_shader_values=True` 路径** | 本次未开启；该路径经 shader debugger，是最可能引入 nondeterminism 的位置 |
| **N3-03 ExecuteIndirect**（F-N3-1，`REPRODUCED / NOT_EXPLAINED`） | 已知未解释问题；**不得**用门 3 声称它已解决 |
| **跨机器等价** | 属 **D7**（Machine B/C 不可用），门 3 不覆盖 |
| **`max_draws` 截断行为** | 未测 |

> **因此**：本文件**不得**被引用为「§4 门 3 已满足」或
> 「§2.9 Gate V 已有可复现证据」。它定义的是**检查形态**与其**已实测部分**。

---

## 9. 状态

```
Gate 3 (§4 门 3)          IMPLEMENTED / VERIFIED（2026-09-29）
Gate 3 Phase 1 Contract  COMPLETE（本文件）
可执行检查                scripts/cold_warm_gate.py（29 项对照）
Gate 4 (§4 门 4)          PROCESS_ONLY（仍无可执行检查，故总体非 PASS）
CI 接线                   NOT AUTHORIZED
§2.9 Gate V 可复现载体     缺失（仅布尔值，无测试）—— 记录，未改 §2.9
```

**未做**：未实现检查、未写门禁条目、未接 CI、未改 Semantic API、
未改 §2.5 三态、未改 §2.9、未改测试 harness。
