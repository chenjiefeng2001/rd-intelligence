# rd-intelligence v1 设计规范（Design Spec）

**冻结点**：`bf1b3c0`（v1 production-observation freeze）
**状态**：Stable Core 与 Semantic API v1 冻结；本规范为长期约束文档，
任何违反 MUST 规则的变更都需要显式评审并更新本文件。

> ⚠️ **2026-09-29 核对**：§2.9「Runtime Isolation Amendment」是冻结点 `bf1b3c0`
> **之后追加的规范性条款，目前尚未提交**（工作树为 ` M docs/DESIGN_SPEC.md`）。
> 冻结点声明不覆盖 §2.9；§2.9 的实现状态见该节末尾的对照表——本节规范
> **当前未被完整实现**。

---

## 1. 定位

> **RenderDoc-compatible GPU Debug Semantic Backend**

以 RenderDoc 为 Replay Engine、以 Evidence 为可信度基础、以局部 GPU 因果流与
First Divergence 为核心语义、可通过 MCP / CLI / IDE / CI 消费的调试后端。

**不是**：RenderDoc 的 AI 插件、RenderDoc GUI 2.0、万能 debug()、AI Agent 框架。

---

## 2. 分层边界规范

### 2.1 RenderDoc 层（外部，fork）

| 规则 | 约束 |
| --- | --- |
| MUST | 仅作为 Replay Engine 使用（capture / replay / pixel history / shader debug） |
| MUST NOT | 任何 tracked modification（fork 永远保持零 diff） |
| MUST NOT | 在其内部加入 AI / 语义图 / MCP / 索引 |

合规验证：`git -C <fork> status --porcelain` 必须为空。

### 2.2 Stable Core（`rdebug` 包，不含 transports）

| 规则 | 约束 |
| --- | --- |
| MUST | 确定性：同输入必同输出（含 evidence id） |
| MUST | Evidence-backed：每条结论边/层状态可回链 eventId/resourceId/operation |
| MUST NOT | 依赖任何 LLM SDK / HTTP 客户端 / transport 包（mcp、rdebug_mcp、rdebug_ide） |
| MUST NOT | `renderdoc` 模块导入出现在 `rdebug/adapter/` 之外 |
| MUST NOT | `rdebug/analysis|query|model|evidence|ci` 导入 observability |

内部结构：

```
rdebug/
├── adapter/        # 唯一允许接触 renderdoc 模块的层（含 locator）
├── query/          # 纯查询逻辑（事件扁平化/过滤/语义谓词）
├── analysis/       # 域分析（pixel/resource/shader/diff），只消费 adapter 域类型
├── model.py        # ResourceRef / PixelHistoryResult / DiffResult（不透明引用原则）
├── evidence.py     # Evidence Contract（唯一证据构造入口）
├── ci.py           # 确定性 CI 门禁（判定者，非解释者）
├── session_cache.py# 共享 transport 基础设施（非语义）
└── observability.py# opt-in 遥测（非语义）
```

### 2.3 Semantic API v1（冻结）

```python
trace_pixel(session, x, y, ...) -> graph dict
trace_resource(session, resource: ResourceRef|str, ...) -> flow dict
debug_pixel(session, x, y, ...) -> trace dict
diff_pixel(session, point_a, point_b, ...) -> DiffResult
```

演进规则：**只做加法**（新增可选参数/新增层/新增 evidence 字段）。
任何破坏性变更 = v2，需要新规范文件。历史先例（合法加法演进）：
`fragment_candidate` 谓词、diff 层 evidence 补全。

### 2.4 Evidence Contract

所有分析结论必须携带 `rdebug.evidence.make` 产出的证据：

```
{ id(内容哈希), capture, eventId, resourceId, subresource,
  location, operation, source, data? }
```

- `id` 由除 `data` 外字段决定，稳定可引用；
- **事实 → 稳定 evidence id → 原始查询** 是唯一可信路径；
- 禁止引入 confidence / AI-generated 等字段。

### 2.5 三态语义

`same` / `different` / `unknown`：

- `unknown` = 当前分析深度无法证明；**≠ same，≠ different**；
- 任何层不得把 unknown 升级为确定结论；
- diff 整体判定规则：有 different → different；锚点层（pixel_value）same →
  same；否则 unknown。

### 2.6 Transport 层（`rdebug_mcp` / `rdebug_ide` / CLI / CI）

| 规则 | 约束 |
| --- | --- |
| MUST | 仅消费 Stable Core（Semantic API v1 四函数 + ci + evidence/model/jsonutil/session_cache） |
| MUST NOT | 出现 RenderDoc API 标识（ReplayController/PixelHistory/GetUsage/DebugPixel/...） |
| MUST NOT | 包含编排/分析逻辑（多步流程若具确定语义，应提升为新的 Semantic API，而不是塞进 transport） |
| MUST NOT | 创建第二套 domain model |
| MUST | 结果（含 evidence）原样透传；运行期错误以 JSON 返回，不中断会话 |

### 2.7 LLM 层（外部）

| 规则 | 约束 |
| --- | --- |
| MUST | 仅作为解释器/推理器（解释 evidence、排序假设、规划下一步查询） |
| MUST NOT | 成为真相来源；不得虚构 evidence；不得获得 RenderDoc 原始 API 权限 |
| MUST | 尊重三态：不得把 unknown 解释为 same/different |
| MUST | 通过 MCP 只见四个语义 tool；grounded prompt 必须包含 "Use ONLY the facts" 纪律 |

### 2.8 Observability

| 规则 | 约束 |
| --- | --- |
| MUST | opt-in（`RDEBUG_TELEMETRY` 未设置 = 零写入零上传） |
| MUST | best-effort：记录失败绝不影响查询行为 |
| MUST NOT | 改变任何语义结果 |
| MUST NOT | 被 Stable Core 语义层（analysis/adapter/model/evidence/query/ci）导入 |

### 2.9 Runtime Isolation Amendment（2026-08-25，W1-R1→W1-R3 证据链冻结）

RenderDoc 进程内 replay runtime **不是**可复用服务对象：多 controller
共存会产生静默值污染 / 原生挂起 / 0xC0000005（W1-R1 F-1/F-2），且其原生
缓存随深回放查询单调累积、永不逐出（F-3/F-3a，~230–500KB/query）。
由此冻结以下架构事实（违反任何一条需显式评审并更新本节）：

| 规则 | 约束 |
| --- | --- |
| MUST | **一个 worker 进程同时只能拥有一个 replay runtime**；多 capture 并存只允许以进程为边界（WorkerManager 模型），禁止回到进程内 SessionManager 多 session 共存路径 |
| MUST | **Semantic 结果不得依赖 worker 生命周期**：回收/重建对调用方透明，同 capture 的任意两次查询（无论跨越多少次 recycle）必须产出字段级一致的语义结果（W1-R3 Gate V 为机械验收） |
| MUST | **Native resource lifetime 必须由 worker recycle 管理**：不尝试进程内清理/逐出原生缓存；寿命上限策略必须可配置（`RecyclePolicy`），预设值是工程默认而非架构常量——不同 capture（demo/AAA/compute）增长曲线不同，允许 per-workload 覆盖 |
| MUST | 内存门禁与归属判定使用 **private bytes**（Windows commit charge），禁止使用 RSS 作为阈值——working set 受 OS trimming/compression/standby list 影响不可作为占用证据（实测基线漂移可达 -35MB） |
| MUST | 命名统一：所有内存类指标/阈值/字段一律使用 `private_memory_bytes` / `private_memory_delta` 语义命名（如 `max_private_memory_delta_mb`）；禁止新增 "RSS threshold"、"memory usage" 类歧义命名 |
| MUST | RSS/working set 仅允许作为**诊断观测字段**存在，且必须显式标注为 `working_set_observation`（或同义明确标注），不得作为任何门禁、阈值、策略输入——诊断字段与门禁字段的身份必须在命名或文档中可区分 |
| MUST | 恢复模型保持最小闭环：**detect（dead/unhealthy 或策略触发）→ bounded retry respawn → verify（下一查询成功 + 值探针）**。在 telemetry 出现真实触发证据前，不得引入通用 health-check 系统、心跳、预测性驱逐等复杂机制 |

内部结构增补（Stable Core 定义不变，新增 transport/runtime 基础设施层，
位于 `rdebug` 包内但不属于 Stable Core 语义面）：

```
rdebug/
├── adapter/          # Stable Core：唯一接触 renderdoc 模块的层
├── ...               # （query/analysis/model/evidence/ci 不变）
├── session_cache.py  # 遗留：单进程多 session（仅旧 transport 兼容；
│                     #  按 §2.9 第一条 MUST，新代码禁止使用）
├── workers.py        # runtime isolation：worker 进程入口（一进程一 runtime）
└── worker_manager.py # runtime isolation：capture → worker 注册表 + RecyclePolicy
```

Transports（MCP/IDE/CLI/CI）应逐步切换到 WorkerManager；切换完成前，
MCP server 现存行为按 W1-R1 发现视为**受已知缺陷约束的过渡形态**
（缓解：Agent/IDE 切换 capture 即重建 transport，或直接迁移 WorkerManager）。

#### 2.9 实现状态（2026-09-29 核对并修复）——本节规范现已**基本实现**

| 规则 | 实现状态 |
| --- | --- |
| MUST 一进程一 runtime；禁止进程内多 session 共存 | ❌ **未接线**：`rdebug_mcp/server.py:34` 与 `rdebug_ide/app.py:39` 仍实例化遗留 `SessionManager`（登记为 `audit_boundaries.py` DEVIATION） |
| MUST 语义结果不依赖 worker 生命周期 | ✅ **实测成立**：w01024 上 6 个 worker 代次 / 5 次回收，语义 payload 逐字节一致 |
| MUST native lifetime 由 worker recycle 管理 | ✅ **已修复并实测触发**：基线初始化原在 `return` 之后（死代码）导致 `mem_baseline` 恒 `None`、该触发器永不生效；现于 `_spawn()` 成功路径采集，实测 `reason: "max_private_memory_delta"` |
| MUST 门禁用 private bytes，禁 RSS | ✅ `mem_current()` 优先 `private_bytes()`；psutil 缺失时基线保持 `None` 并上报 `memory_metric: "unavailable"`，**不回退 RSS**；`psutil` 已补入 `dependencies` |
| MUST 命名统一为 `private_memory_*` | ✅ `private_memory_baseline_bytes` / `private_memory_baseline_mb`；原 `rss_baseline` / `mem_baseline_mb` 已改 |
| MUST RSS 仅作诊断且显式标注 | ✅ `rss()` / `rss_bytes()` 标注 `working_set_observation`；边界审计检查无 RSS 命名的上报字段 |
| MUST 恢复最小闭环 | ✅ detect → bounded retry respawn → verify；判定改用结构化 `WorkerError.transient`，不再对错误串做子串匹配 |

本节此前是**唯一未被机械审计的规范性章节**。现 `scripts/audit_boundaries.py`
已补 7 项 §2.9 检查（合计 15/15 通过 + 1 项登记偏差）。行为层覆盖见
`tests/unit/test_worker_manager.py`（34 tests，stub worker，不依赖 RenderDoc），
含针对上述死代码缺陷的回归测试。

跨机器验证基准（Phase 3A）：semantic consistency 以
`rdebug-validation/baselines/cross-machine-fingerprints.json`（**仓库外路径**，
不在本仓库内）的内容哈希为准——要求 trace/diff/evidence 在不同
CPU/GPU/驱动上**哈希一致**；timing 只比较形状（cold/warm 分类分布），
禁止绝对值断言。

⚠️ **D7 状态**：`rdebug-validation/docs/PHASE3A-CHECKLIST.md:3-6` 将 Machine B/C
标记为 `unavailable`。因此上述跨机器哈希一致性基准**尚未在任何第二台机器上
验证过**，不构成已成立的保证；现阶段不得据此作出跨机器声明。

### 2.10 `context_eid` 事件选择语义（2026-09-29，裁决 A）

本节补齐 Semantic API v1 此前**完全缺失**的一条契约。此前 `DESIGN_SPEC`
从未定义 `context_eid`；§2.3 的 `eventId` 只讲**证据回链**（输出来处），
与**输入事件的选取**无关。缺失导致不存在的 event id 被静默接受，
返回形状正常但不指向 capture 中任何真实 event 的语义结果
（F12 家族，见 `docs/F12-CONTEXT-EID-CONTRACT.md`；
冻结点见 `docs/FREEZE-EID-2026-09-29.md`）。

| 规则 | 约束 |
| --- | --- |
| MUST | `context_eid=None` 保持既有缺省行为（由调用方所在层解析为默认 context，通常是 `last_event_id()`），**语义不变** |
| MUST | `context_eid=<eid>` 必须是**当前 capture 的 action tree 中实际存在的 event ID** |
| MUST | 合法性按**成员关系**判定：取 `action_rows()`（= `flatten_actions(root_actions())`）的 `eventId` 集合。**禁止**按数值区间判定（`0 <= eid <= last_event_id()`），**禁止**退化为 draw-only 集合 |
| MUST | 判定必须发生在 `SetFrameEvent` **之前**；未通过判定不得调用它 |
| MUST | 非法 `context_eid` 走明确的**参数错误**路径，**不得产生任何 semantic result** |
| MUST NOT | **不存在 fallback event。** 不得在非法输入后回退到某个 event 再声称那就是实际 context |
| MUST | 合法请求的 `contextEventId` 表示**经校验的**请求 context |
| MUST NOT | 非法请求不得让 payload 冒充成功结果；`contextEventId` 不得作为「已生效」的证据出现在失败响应中 |
| MUST | 非法 `context_eid` 之后，runtime 与 worker 必须保持可用，后续合法查询结果与基线一致 |
| MUST NOT | 参数错误不得被归类为 worker death / unhealthy / replay failure，以免污染 §2.9 的恢复遥测 |

**为什么只能选 A（严格成员判定）**：RenderDoc 的 `ReplayController` 只暴露
`SetFrameEvent` 与 `GetFrameInfo`（capture 级 `FrameDescription`），
**没有 current-event 读回**。因此「回退后的实际 context」不可观测——
任何回退标签都是无法证实的断言，恰好是本条要修的同一形态。

**为什么不能用区间判定**：实测 event ID **不是连续区间**
（`w20000_frame11.rdc`：20003 unique id，`contiguous=False`）。在某 capture 上
`[0,12]` 区间内有 9 个不存在的 id，区间检查会全部错误接受并继续产出错误结果。

**为什么不能是 draw-only**：嵌套 action（如 dispatch / indirect）不是 draw，
却是合法 event。`flatten_actions()` 递归进入 `action.children`，
因此成员集合天然覆盖它们；用 draw 集合会误杀合法输入。

**本节的验证要求**：A 严格成员契约 + 真实 capture 回归 + 正/负/假阳性三对照
+ 非法输入后的恢复检查。其中假阳性对照（合法嵌套非-draw event 必须被接受）
是三者中最易做错的一条。

---

## 3. 数据驱动决策规则（防止架构漂移）

以下方向**在触发条件满足前一律冻结**：

| 方向 | 触发条件 | 满足后的首选方案 |
| --- | --- | --- |
| 并发/调度 | telemetry 显示 warm p95 排队、并发 session 成为瓶颈 | **进程隔离** > Python async（因 InitialiseReplay 不可重入） |
| capture 索引 | 真实大 capture 上索引类查询 > 100ms | 先定位瓶颈 API；旁路 `*.rdc.idx` |
| 跨 capture matching | 出现必须跨构建比对的硬需求 | 独立评审（entity resolution 复杂度已知） |
| 采样值比较 | 用户真实需要纹理内容级 diff | 保持 optional/deep（cheap→expensive evidence 分层不变） |
| Git/shader source 关联 | 回答"哪次代码变更引入"的需求落地 | Stable Core **之外**的 Reasoning Layer（GPU facts + code facts + build facts） |

---

## 4. 质量门

1. 核心测试（`tests/`）与 transport 测试（`tests_transport/`）全绿；
   transport 失败不得导致核心失败；
2. `scripts/audit_boundaries.py` 全部 PASS（机械边界审计）；
3. 语义等价：任何性能/重构变更必须通过 cold==warm 等价检查；
4. benchmark 回归：session/latency 数据变更需附 `docs/validation/` 存档；
5. RenderDoc fork 零 tracked modification。

---

## 5. Real-world Validation（v1 后阶段）

```
A. 真实项目试点（游戏/引擎 capture 走完 ci-record → ci-check → IDE → MCP/LLM）
B. 数据驱动优化（只解决 telemetry 证明存在的问题：p95/p99、memory、recovery、eviction）
C. v1.1 决策（仅由 A/B 的真实需求触发；跨 capture matching 继续冻结）
```

未来方向（Stable Core 之外的 Reasoning Layer）：

```
GPU Evidence + Shader source + Git diff + CI metadata
    ↓ 确定性 candidate causes
    ↓ LLM ranking / explanation
"哪次代码变更引入了这个 GPU regression"
```

---

## 6. 机械合规审计

`python scripts/audit_boundaries.py` 自动执行本规范中可机械化的规则
（导入隔离 / transport 纯净性 / Stable Core 无 LLM/transport 依赖 / telemetry
默认关闭等），输出 PASS/FAIL 表，非零退出码表示违规。
