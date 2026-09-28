# Phase 4d：Transport Session Reuse

日期：2026-08-24 · 工具：`scripts/session_bench.py`
实现：`rdebug_mcp.server.SessionManager`（transport 层，语义层零改动）

## 设计与硬不变量

- 生命周期绑定 MCP server 进程（单 client 连接），**非全局 singleton**：
  按捕获绝对路径隔离、LRU 驱逐（默认 4）、复用前健康探测、失效即
  dispose→reopen（`recoveries` 计数），server 不崩；
- 三不变量验证：① 语义等价（cold==warm，逐 JSON 键）② 失效可恢复
  ③ 捕获隔离（A/B 独立、dispose(A) 后 B 可用）——均由
  `tests_transport/test_session_manager.py` 锁定（8 个新测试，15/15 全绿）。

## Cold / Warm 基准（完整 4-tool trajectory，真实 replay）

| step | cold (每次重开) | warm 首轮 | **warm 稳态** |
| --- | ---: | ---: | ---: |
| trace_pixel | 2057.6 ms | 1528.4 ms* | **5.4 ms** |
| trace_resource | 1642.8 ms | 0.3 ms | **0.4 ms** |
| diff_pixel | 1584.8 ms | 14.0 ms | **5.7 ms** |
| debug_pixel | 1708.3 ms | 180.1 ms | **173.0 ms** |
| **total** | **6993.5 ms** | 1722.8 ms | **184.5 ms** |

\* 首轮 warm 含 session 打开。

- 稳态 trajectory 总耗时 **184.5ms vs cold 6993.5ms（≈38×）**；
- 单调用达到 <100ms 目标（debug_pixel 的 173ms 是真实 shader 调试工作，非 transport 开销）；
- **语义等价 4/4**：cold 与 warm 输出 JSON 逐键一致（nodes/edges/evidence/unknown 全同）；
- `recoveries=0`，会话全程稳定。

## 对 AI 可见语义的影响

零。4b 的 trajectory（trace→resource→diff→debug）在 session reuse 下重跑，
工具输出与 cold 模式逐字节等价——性能优化未改变 AI 可见语义。

## 后续（未开工）

1. 采样到的纹理内容比较（shader_input_values 深化）
2. IDE / CI 集成试点（此时延迟已可支撑交互式使用）
3. 多捕获并发访问策略（当前 stdio 单连接串行，已满足；并发需另行设计）

> **2026-09-29 核对（历史状态已过时）**：第 2 项已由 **Phase 5a/5b** 完成。
> 第 1 项仍未开工（已在 `DESIGN_SPEC.md:169` 冻结）。
> 第 3 项已由 `DESIGN_SPEC.md` **§2.9** 重新裁决为 WorkerManager 进程隔离模型
> （而非进程内并发），其实现状态见 §2.9 末尾对照表——**当前未接线**。
