# rd-intelligence v1 设计规范（Design Spec）

**冻结点**：`bf1b3c0`（v1 production-observation freeze）
**状态**：Stable Core 与 Semantic API v1 冻结；本规范为长期约束文档，
任何违反 MUST 规则的变更都需要显式评审并更新本文件。

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
