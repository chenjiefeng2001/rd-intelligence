# P0 Baseline Freeze 与 P1 Automated UX Readiness

> 阶段性质：**P0 = 冻结基线**；**P1 = 只做审计与测试，不改公共语义**。
> 本文件记录可复核事实，不含推测。

---

## P0 — Baseline Freeze

### 冻结范围（当前状态即基线）

| Workstream | 状态 |
| --- | --- |
| Replay architecture（worker isolation / recycle / recovery） | **FROZEN** |
| Evidence / Contract | **FROZEN** |
| CI 四态语义 / Gate 3 | **FROZEN** |
| Corpus Contract / N3-05A | **FROZEN** |
| Track A forensic case（`TEARDOWN-CASE.md`） | **FROZEN** |
| CLI 行为（JSON-first） | **STABLE** |
| MCP | **FROZEN / OUT OF SCOPE**（本阶段） |
| IDE UX | **ACTIVE** |

### 自动验证结果（本轮实测）

```
unit        536 passed / 3 skipped
ruff        All checks passed
worktree    clean
baseline    a26333d   drift 1/1
```

### 必须保留的记账（不得改写）

```
integration 自身        63/63 OK
integration 进程终止     INFRASTRUCTURE_FAILURE（exit 0xC0000005）
overall                 BLOCKED_INFRA
```

> **63/63 通过 ≠ integration PASS ≠ overall PASS。** 该区分已由 Track A 根因
> （`TEARDOWN-EVIDENCE-CASE.md`）解释，属冻结事实，不得在此处被合并表述。

**P0 完成条件：基线可复现记录 + 无未解释的工作树变更 → 达成。**

---

## P1 — UI → API → Contract → Evidence 链路审计

### 端点清单

| 端点 | handler | UI 是否调用 |
| --- | --- | --- |
| `/api/info` | `api_info` (L104) | ✅ L190 |
| `/api/ci` | `api_ci` (L109) | ✅ L170 |
| `/api/trace` | `api_trace` (L131) | ✅ L164 |
| `/api/diff` | `api_diff` (L137) | ✅ L154 |
| `/api/resource` | `api_resource` (L145) | ✅ L125 |
| `/api/explain` | `api_explain` (L198) | ⚠️ L157 调用，但按钮 **disabled** |
| `/api/stats` | `api_stats` (L223) | ❌ **UI 从不调用**（死端点） |

### 已确认成立的链路

| 环节 | 证据 |
| --- | --- |
| `Diff → /api/diff → diff_pixel` | 参数 `a`/`b` 双向传递，`_parse_xy` 解析 |
| `Resource → /api/resource → trace_resource` | 端到端存在 |
| `Trace → /api/trace → trace_pixel` | 端到端存在 |
| `Escaping` | `esc()` 对 `& < >` 转义，evidence 以文本注入安全 |
| **Trace 的 Evidence 结构** | docstring 明示「每条边携带 evidence，引用 eventId / resourceId / operation」 |

### 已确认缺陷（静态可判定，无需运行）

| # | 缺陷 | 位置 | 严重度 |
| --- | --- | --- | --- |
| **D1** | **`deep` 参数永不生效**：handler 只接受 `"1"`，UI 复选框发送 `"true"`/`"false"` ⇒ 勾选后**静默降级为浅层 diff**，无任何提示 | `app.py:141` vs `index.html:154` | **高** |
| **D2** | **`max_draws` 被静默截断为 4**：handler 默认 `["4"]`，UI 从不发送该参数 ⇒ trace 图被无声裁剪，用户以为看到了全部 | `app.py:132` | **高** |
| **D3** | **UI 无法指定 `eid`**：`api_trace` 无 `eid` 形参，`/api/trace?x=&y=` 也不传 ⇒ **event 维度在 UI 上不可达**（Phase 2 缺口，已确认） | `app.py:131` / `index.html:164` | **高** |
| **D4** | **无 capture 选择**：`api_*` 全部不接受 capture 参数，隐含使用启动时配置 ⇒ 多 capture 场景不可用（Phase 2 缺口，已确认） | `app.py` 全体 | **高** |
| **D5** | **HTTP 状态码未检查**：`api()` 直接 `return r.json()`，无 `r.ok` 判断 ⇒ 5xx 的非 JSON 响应变成解析异常，**结构化 error 与传输失败不可区分** | `index.html:85-88` | **中** |
| **D6** | **错误被转换为「无结果」**：`.catch(()=>null)` 吞掉 `/api/resource` 的失败并继续渲染 ⇒ 基础设施错误呈现为**缺失** | `index.html:125` | **中** |
| **D7** | **坐标解析静默兜底**：`split(",")[1] \|\| "0"` ⇒ 输入畸形（如缺 y）时 **y 静默变成 0**，而非报错 | `index.html:164` | **中** |
| **D8** | **resource id 静默强转**：`id.replace(/\D/g,"")` 剥掉非数字 ⇒ 输入资源名会被静默改写为数字 id | `index.html:125` | **中** |
| **D9** | **`Explain with AI` 永久 disabled** 但代码路径存在（L157 已调用）⇒ **禁用态无解释**，属明确的可用性反模式 | `index.html:64` | **中** |
| **D10** | **`/api/stats` 死端点**：handler 存在，UI 从不调用 | `app.py:223` | **低** |
| **D11** | **无 loading / 状态机**：Result/Evidence 为静态容器；重复点击与陈旧结果覆盖**未被防护**（Phase 3 缺口） | `index.html` 全局 | **中** |

### P1 结论

> **链路「静态存在」但「语义未通过」的部分远多于「已成立」的部分。**
>
> - **已成立**：4 条端到端路径 + escaping + Trace 的 evidence 结构意图
> - **已确认缺陷**：11 项，其中 **4 项为高严重度**（D1/D2/D3/D4），且**全部是静默失败**——
>   不报错、不提示、只是**给出错误或被裁剪的答案**
>
> **最严重的模式**：D1 与 D2 表明 UI 会**在用户以为成功的前提下给出不完整或错误的分析结果**。
> 这比崩溃更危险，因为**它污染结论而不产生任何信号**——与 Track A 中
> 「UNAVAILABLE ≠ EMPTY」的纪律直接冲突。

### 与既有治理结论的冲突（须记录）

| Track A / Evidence 原则 | IDE 现状 |
| --- | --- |
| `unavailable ≠ empty ≠ failure` | ❌ D6（错误→缺失）、D7（畸形输入→y=0） |
| 每个结论可追溯到 evidence | ⚠️ Trace 有 evidence 意图；Diff 的 `deep` 分支**不可达**（D1），故其 evidence 深度实际不可得 |
| 非法输入应是 `BAD_REQUEST` | ❌ D7 / D8 静默强转 |
| 四态语义投影到 UI | ❌ D11（无状态机） |

### 本阶段未做（明确）

- 未修改任何 UI / API / 公共语义
- 未运行 IDE、未发 HTTP 请求、未做浏览器级验证
- 未引入 `/api/stats` 调用、未改 `deep` 解析（D1 的修复属 **P2/P3**，本阶段仅记录）
- 未做人工可用性评估（属 **P10**）

**下一步应据本表的实际缺口决定 P2 的具体改动顺序，而非按预设清单推进。**
