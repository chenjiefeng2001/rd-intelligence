# Phase 5c（重定义）：Production Observation

日期：2026-08-24 · 实现：`rdebug/observability.py`（opt-in JSONL 遥测）
开启方式：设置环境变量 `RDEBUG_TELEMETRY=<file.jsonl>`（未设置则零开销、零写入）

## 范围纪律

- **不做并发**：无数据表明它是瓶颈；P5c 只回答"真实使用中哪里慢/占资源/失败"；
- Stable Core 零改动：遥测只在 transport 层（SessionManager + MCP/IDE 查询包装）；
- 记录永不抛错（best-effort），查询失败也记录（`query_error`）。

## 事件模型

| 事件 | 字段 |
| --- | --- |
| session_open / session_reuse / session_recovery / session_evict / session_probe_failed / session_open_failed | capture, latencyMs |
| query | transport(mcp/ide), tool/endpoint, latencyMs, error |

## 真实 replay 采样（IDE server，完整查询序列）

```jsonl
{"event": "session_open",  "capture": "…triangle_frame11.rdc", "latencyMs": 2093.94}
{"event": "query", "transport": "ide", "endpoint": "/api/diff",     "latencyMs": 2116.1}
{"event": "session_reuse", "capture": "…triangle_frame11.rdc"}
{"event": "query", "transport": "ide", "endpoint": "/api/trace",    "latencyMs": 9.13}
{"event": "session_reuse", "capture": "…triangle_frame11.rdc"}
{"event": "query", "transport": "ide", "endpoint": "/api/resource", "latencyMs": 1.8}
{"event": "session_reuse", "capture": "…triangle_frame11.rdc"}
{"event": "query", "transport": "ide", "endpoint": "/api/explain",  "latencyMs": 12.55}
```

读法与 4d 基准一致：**唯一大头是首次 replay 初始化（~2.1s），复用后查询全部 <13ms**；
无 error / recovery / eviction。这份数据再次确认：并发层暂无必要。

## 测试

`tests_transport/test_observability.py`（6 个）：默认关闭零写入、record/timed、
写失败不抛错、open/reuse/evict/recovery 事件、查询事件。全套件：transport 28/28、核心 74/74。

> **2026-09-29 核对**：上列为本报告撰写时的历史计数。commit `9134cab`
>（telemetry `result_shape` 观测）为其后新增 3 个 `result_shape` 测试，
> 当前 `tests_transport/` 实为 **31 tests**（`test_observability.py` 8 个）。
> 同时注意 `tests_transport/` 无 `__init__.py` 且不在 `pyproject.toml` 的
> `testpaths = ["tests"]` 内，默认 pytest 不会运行它。

## 决策规则（写死，防止架构漂移）

```text
telemetry 数据
  ↓ 只有当真实数据显示并发成为瓶颈
process isolation > clever concurrency
  ↓ 否则
维持现状（LRU + 单连接串行）
```

Git / shader source / build metadata 关联：**永远在 Stable Core 之外**的 Reasoning Layer，
不得进入 Semantic API。
