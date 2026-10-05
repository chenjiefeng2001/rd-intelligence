# API Reference

英文版见 [`API-REFERENCE.en.md`](API-REFERENCE.en.md)。两版由 `tests/unit/test_api_reference_parity.py` 保持一致：端点、参数、状态码与证据标记任一漂移即失败。

代码真值来源：`src/rdebug_ide/app.py`、`src/rdebug_mcp/server.py`、`src/rdebug/cli.py`。
**本文档只描述已存在的接口，不新增、不修改任何契约。**

## 证据等级约定

本文档对每条陈述标注证据等级，避免把「设计意图」写成「已验证」：

| 标记 | 含义 |
| --- | --- |
| **[CODE]** | 直接读自实现 |
| **[P9a]** | 经真实 IDE HTTP 往返实测（`docs/CURRENT-EVIDENCE-FREEZE.md`） |
| **[UNIT]** | 有单元/契约测试覆盖 |
| **[NOT ESTABLISHED]** | 尚未建立，不得当作已成立 |

> **整体限定**：`browser-level UI propagation = NOT_ESTABLISHED`。
> 下列 HTTP 语义均已在**真实 HTTP 边界**观测，但**从未在真实浏览器中渲染验证**。

---

## 1. 三层接口面

| 层 | 入口 | 消费者 | 状态 |
| --- | --- | --- | --- |
| **Semantic API v1** | `rdebug.analysis.*` | 全部上层 | **FROZEN** |
| **MCP transport** | `rdebug-mcp`（4 tools） | 外部 LLM / Agent | **FROZEN** |
| **IDE HTTP** | `rdebug-ide`（7 endpoints） | 人 / 脚本 | 见下 |

**[CODE]** 三者的分层由 `scripts/audit_boundaries.py` 强制：
Rule 2.1 禁止 Stable Core 依赖 transport；**Rule 2.2 禁止 `openai` / `anthropic` / `httpx` / `import requests` 出现在 `rdebug`、`rdebug_mcp`、`rdebug_ide` 任何位置**。

> **含义**：本工具面**不持有模型、不调用模型**。LLM 始终是**外部 agent**，通过 MCP tool call 取数据。
> `Generate AI Prompt` 只**生成 prompt 文本**，不执行 AI（见 §2.6）。

---

## 2. IDE HTTP API

`rdebug-ide <capture> [--port N] [--baseline B] [--rd-path P]`，仅监听 `127.0.0.1`。
**[CODE]** 所有 `/api/*` 响应为 `application/json; charset=utf-8`；`/` 与 `/index.html` 为 `text/html; charset=utf-8`。

### 2.1 端点总览

| 端点 | 参数 | 转发到 | 状态 |
| --- | --- | --- | --- |
| `/api/info` | — | — | 稳定 |
| `/api/trace` | `x`, `y`, `max_draws`, `eid` | `trace_pixel` | 稳定 |
| `/api/diff` | `a`, `b`, `deep` | `diff_pixel` | 稳定 |
| `/api/resource` | `id`, `eid` | `trace_resource` | 稳定 |
| `/api/explain` | `a`, `b`, `deep` | `diff_pixel` | 稳定 |
| `/api/ci` | — | `ci_check` | 稳定 |
| `/api/stats` | — | — | **资源所有权视图，非请求指标** |

### 2.2 `/api/info`

**[CODE]** 返回 `{"capture": <str|None>, "ci": <bool>, "ready": <bool>}`。
`ready` 为 false 时所有查询以 `RDebugError("IDE capture is not configured; call configure()")` 失败。**[P9a]**

### 2.3 `/api/trace`

| 参数 | 必需 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `x`, `y` | 是 | int | — | 像素坐标 |
| `max_draws` | 否 | int ≥ 1 | **16**（库默认 `MAX_DRAWS_DEFAULT`） | 分析范围 |
| `eid` | 否 | int 或空 | 空 = 默认事件 | 事件上下文 |

**[CODE]** 响应顶层键：`edges`、`nodes`、`resourceFlows`、`summary`。
`summary` 含 `contextEventId`、`analyzedDraws`、`truncatedDraws`、`modificationCount`、
`totalWriteEvents`、`writeEventCount`、`finalValue`、`target`、`readsEnumerable`、`evidence`。**[P9a]**

**[P9a]** `contextEventId` 位于 **`summary` 内**。

### 2.4 `/api/diff`

| 参数 | 必需 | 类型 | 说明 |
| --- | --- | --- | --- |
| `a`, `b` | 是 | `"x,y"` | 两个像素 |
| `deep` | 否 | `1`/`0`/`true`/`false` | 等价类，默认 false |

**[CODE]** `deep` 只接受这四个值，其余一律 `400`。**[P9a]** `deep=1` ≡ `deep=true`（body 逐字节相同）；
`deep=1` ≠ `deep=0`（相差 1359 bytes），证明该参数**确有效果**。

**[CODE]** **本端点不接受 `eid`。** `diff_pixel` 无 `context_eid` 参数，内部恒用
`session.last_draw_event_id()`。**[P9a]** `diff?eid=abc` 与不带 eid 的响应**逐字节相同**
——即 eid 被忽略而非报错。

### 2.5 `/api/resource`

| 参数 | 必需 | 类型 | 说明 |
| --- | --- | --- | --- |
| `id` | 是 | `ResourceId::<digits>` | 资源标识 |
| `eid` | 否 | int 或空 | 事件上下文 |

**[CODE]** 响应顶层键：`contextEventId`、`resource`、`readers`、`writers`、`other`、`evidence`、`summary`。**[P9a]**

> **[P9a] 形状不一致（结构性观察，非缺陷）**
> `/api/trace` 把 `contextEventId` 放在 `summary` 内；`/api/resource` 放在**顶层**。
> 客户端若统一从 `summary` 读取，Resource 侧会**静默得到 `undefined`**。
> 目前**无跨端点共享 response-shape Contract**，故不定性为缺陷；
> 但实现客户端时须知悉此陷阱。

### 2.6 `/api/explain`

**[CODE]** 参数同 `/api/diff`（`a`, `b`, `deep`），内部同样调用 `diff_pixel`。
返回 `{"prompt": <str>, "evidenceIds": [...]}`。

> **本端点不调用任何模型。** `prompt` 由 `explain_prompt()` 纯字符串拼装，
> 内含 `You are explaining a GPU pixel diff. Use ONLY the facts below.` 等**面向模型的指令**。
> 模型由使用者侧的 agent 提供。**[CODE]**
> 因底层是 `diff_pixel`，**本端点同样不接受 `eid`**。**[P9a]**

### 2.7 `/api/ci`

**[CODE]** 未配置 `--baseline` 时返回 `{"enabled": false}`。
配置后返回 `{"enabled": true, "status": "pass"|..., "captureHashMatch": <bool>, "failures": [...]}`。

### 2.8 `/api/stats`

**[CODE]** 返回：

```json
{"sessions": {"count": 1, "paths": ["A.rdc"], "recycles": 0, "unkillable": []},
 "telemetry": false}
```

全部字段来自 **WorkerManager registry**，表达**资源所有权与回收**。
**[UNIT]** `tests_transport/test_ide_app.py::test_stats_reports_the_owner_and_recycles`
固定了「一个 owner，而非每请求一个」的语义。

> **本端点不提供调用次数、延迟或错误分类。** 请求指标仅存在于 **opt-in JSONL 遥测**
> （`RDEBUG_TELEMETRY` 环境变量指向文件时才记录，append-only，**无查询/聚合 API**）。
> IDE 前端**当前不调用本端点**。**未提供请求指标视图 —— NOT IMPLEMENTED。**

### 2.9 错误与状态码语义

**[CODE]** `route()` 的映射，逐条照录实现：

| 条件 | 状态 | body |
| --- | --- | --- |
| 端点未知 | **404** | `{"error", "path"}` |
| worker 返回**已分类**错误（有 `error` 且有 `kind`） | **400** | `{"error", "kind", "tool"?}` |
| 抛出 `RDebuggerError` | **400** | `{"error"}` + `"kind"`（若有） |
| 抛出 `KeyError`/`IndexError`/`ValueError`/`TypeError` | **400** | `{"error": "invalid request parameters: …", "endpoint"}` |
| **worker 返回未分类错误**（有 `error`，**无 `kind`**） | **200** Note: | `{"error", "tool"}` |
| 其余 | **200** | 结果 payload |

> Note: **[P9a] 关键：HTTP status 不是充分的错误判别依据。**
> **未分类**的 worker 错误返回 **200 + error body**。**[P9a]** 实测：
> `/api/resource?id=<不存在的 id>` → **200** + `unknown resource id …`。
>
> **正确客户端契约是三者合取**：`status` + `body` 形状/`error` 字段 + `kind`（若存在）。
> 冻结的 `index.html` 中 `api()` 同时检查 `r.ok` 与 `body.error`，与此一致，**未发现回归**。
>
> 该差异记为**开放设计问题**，**不定性为缺陷**（需先决定未分类错误是否本应映射 4xx/5xx）。

### 2.10 事件上下文（eid）适用范围

**[CODE] + [P9a]**

| 端点 | 受 `eid` 影响 | 证据 |
| --- | --- | --- |
| `/api/trace` | **是** | `eid=11`→`ctx=11`，`eid=12`→`ctx=12`，`eid=1`→`ctx=1` |
| `/api/resource` | **是** | 同上，顶层 `contextEventId` |
| `/api/diff` | **否** | 底层无 `context_eid` 参数 |
| `/api/explain` | **否** | 底层是 `diff_pixel` |

**缺省行为** **[P9a]**：不带 `eid` 时 `contextEventId` = `last_draw_event_id`。

**格式校验** **[CODE]**：`_eid_param` 只判**格式**（`^-?\d+$`，空 = 不提供），
格式错误 → `QueryError(kind="bad_request")` → **400**。
**合法性**由 action-tree membership 判定 —— **[P9a]** 非法 eid → **400** + `not an event in this capture`。

> **[P9a] 重要：合法事件集合是稀疏的，不能从错误消息的范围文字推导。**
> 某 capture 实测 `valid_event_ids = [1, 2, 11, 12]`，而错误消息写 `events 1..12`。
> **`3–10` 共 8 个 eid 在宣称区间内但不存在**，对其查询必然得到 `bad_request`。
> 前端**不得**据错误文案校验区间。

---

## 3. MCP Transport

`rdebug-mcp` **[CODE]** 暴露**恰好 4 个工具**（由 `TransportInvariants` 固定）。
`workers.py` 注释明确该表面即「LLM 所看到的」。

| 工具 | 参数 |
| --- | --- |
| `trace_pixel` | `capture, x, y, target, eid, mip, slice, sample, max_draws, expand_reads, max_writers` |
| `trace_resource` | `capture, resource, eid, include_other` |
| `debug_pixel` | `capture, x, y, target, eid, primitive, sample, view, max_steps, include_disassembly` |
| `diff_pixel` | `capture, a_x, a_y, b_x, b_y, max_draws, include_shader_values, expand_reads` |

**共同点** **[CODE]**：三者接受 `eid`；**`diff_pixel` 不接受** —— 与 HTTP 侧一致。

**`max_draws` / `max_writers` 的语义** **[CODE]**（工具 docstring 原文）：
> clamped to the server-side ceilings; a caller asking for more is capped rather than refused,
> so the limit is a guarantee about cost and not a new failure mode for existing callers.

即**超限被截断而非拒绝** —— 与 §2.3 的 `truncatedDraws` 是同一诚实性原则。

**IDE 与 MCP 的差异** **[CODE]**：`ci_check` 是 Stable Core 但**不在** MCP 工具面内
（`workers.py` L37-52 记录了把它做成 op 会导致 `unknown tool` 的历史）。

---

## 4. CLI

**[CODE]** 15 个子命令。每个子命令另有 `--rd-path`（`RDEBUG_RENDERDOC_PATH` 的 CLI 形式）。

| 子命令 | `--eid` | 自身主要参数 |
| --- | --- | --- |
| `info` | — | — |
| `events` | — | `--limit` `--name` `--min-eid` `--max-eid` |
| `draws` | — | `--limit` `--name` `--min-eid` `--max-eid` |
| `resources` | — | `--limit` `--name` |
| `textures` | — | `--limit` |
| `buffers` | — | `--limit` |
| `usage` | — | `--resource!` |
| `pipeline` | **必填** | `--eid!` |
| `pixel-history` | 可选 | `--x!` `--y!` `--target!` `--mip` `--slice` `--sample` `--eid` |
| `trace-pixel` | 可选 | `--x!` `--y!` `--max-draws` `--max-writers` `--target` `--mip` `--slice` `--sample` `--eid` `--no-expand-reads` |
| `trace-resource` | 可选 | `--resource!` `--include-other` `--eid` |
| `debug-pixel` | 可选 | `--x!` `--y!` `--target` `--primitive` `--sample` `--view` `--max-steps` `--no-disassembly` `--eid` |
| `diff-pixel` | **无** | `--a!` `--b!` `--include-shader-values` `--max-draws` `--no-expand-reads` |
| `ci-record` | — | `--spec!` `-o!` |
| `ci-check` | — | `--baseline!` `--tolerance` `--ignore-capture-hash` |

（`!` = required）

**`--eid` 的可用范围** **[CODE]**：
`pipeline`（**必填**）、`pixel-history`、`trace-pixel`、`trace-resource`、`debug-pixel`。
**`diff-pixel` 不接受 `--eid`** —— 与 §2.4 一致，因 `diff_pixel` 无该参数。
`usage` 亦**不接受** `--eid`（其作用域是资源而非事件）。

## 5. 已知接口陷阱汇总

以下均为**已实测记录**，供实现客户端时规避：

| # | 陷阱 | 依据 |
| --- | --- | --- |
| 1 | HTTP 200 可能携带 error body（未分类错误） | [P9a] |
| 2 | `contextEventId` 在 trace 的 `summary` 内、在 resource 的**顶层** | [P9a] |
| 3 | `eid` 只影响 trace / resource，diff / explain 静默忽略 | [P9a] |
| 4 | 错误消息的 `events 1..12` **不是**合法 eid 集合（可能稀疏） | [P9a] |
| 5 | `max_draws` 截断时响应可能**仅差 1 byte**，须读 `truncatedDraws` 字段而非比较长度 | [P9a] |
| 6 | MCP 的 `max_draws`/`max_writers` **超限截断而非报错** | [CODE] |
| 7 | `deep=`（空值）被 `parse_qs` 丢弃，等价于未提供 → 默认 false | [P9a] |
| 8 | `/api/stats` **不是**请求指标端点 | [CODE][UNIT] |

---

## 6. 未建立事项

| 项 | 状态 |
| --- | --- |
| Browser-level UI propagation | **NOT ESTABLISHED** |
| 失败横幅的**视觉**可见性（`.banner`/`.banner-warn` **无 CSS 规则**） | **NOT ESTABLISHED**（DOM 写入已 VERIFIED） |
| 干净关闭 / `dispose()` 执行 | **NOT ESTABLISHED**（探测手段限制） |
| IDE 请求指标视图 | **NOT IMPLEMENTED**（A workstream 已 CLOSED，scope boundary） |
| 工具侧模型调用 | **NOT AUTHORIZED**（违反 Rule 2.2 / DESIGN_SPEC MUST-NOT） |
| 跨端点统一 response-shape Contract | **不存在** —— 故 §2.5 的差异未被定性为缺陷 |

---

## 7. 相关文档

| 主题 | 文档 |
| --- | --- |
| 设计规范（MUST / MUST-NOT） | `docs/DESIGN_SPEC.md` |
| 事件上下文契约 | `docs/F12-CONTEXT-EID-CONTRACT.md` |
| MCP 治理 | `docs/MCP-CONTRACT-GOVERNANCE.md` |
| HTTP 边界实测证据 | `docs/CURRENT-EVIDENCE-FREEZE.md` |
| 能力与边界 | `docs/CAPABILITIES-AND-BOUNDARIES-2026-10.md` |
| UI 就绪度审计（11 项缺陷） | `docs/P0-P1-UX-READINESS.md` |
