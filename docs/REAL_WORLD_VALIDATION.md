# Real-world Validation Playbook（v1 后阶段）

**前提**：`c88f176` = v1 Design Freeze。从此刻起，"不开发"是默认正确的工程动作；
任何新工作必须由本文件定义的数据触发，并满足 `DESIGN_SPEC.md` §3 的触发条件。

## 四类观察指标（全部可由现有遥测回答）

### 1. 性能
事件：`session_open` / `query`（latencyMs）
关注：区分 Replay 初始化、PixelHistory、shader debug、语义分析、transport——
不要只看总耗时。已知基线：session_open ≈ 2s（唯一大头）；warm 查询 0.3–15ms；
debug_pixel ≈ 173ms（真实调试工作）。

### 2. 查询行为
事件：`query` / `result_shape` 序列（按 ts 排序即 trajectory）
关注：真实问题的解决路径是否集中在 `trace_pixel → trace_resource → diff_pixel`；
`debug_pixel` 的实际调用率。若 90% 问题止步于 provenance/diff，
则四查询模型接近正确的最小 API。

### 3. Unknown 分布
事件：`result_shape.unknownLayers`
关注：哪种证据最缺（如 shader_input_values 高频 unknown → 采样值比较才有价值）。
**这是 v1.1 功能决策的首要依据，优先级高于任何主观判断。**

### 4. Recovery / failure
事件：`session_recovery` / `session_probe_failed` / `session_open_failed` /
`session_evict` / `query_error`
关注：进入 CI 后可靠性优先于新功能；任何 recovery 率上升都先于一切扩展处理。

## 采集方式

```bash
# 任意 transport 前设置即可，未设置 = 完全不写
set RDEBUG_TELEMETRY=rd-telemetry.jsonl
rdebug-mcp …   /   rdebug-ide …   /   rdebug ci-check …
```

## 决策规则（引用 DESIGN_SPEC §3，违反即回退）

| 候选 | 触发证据 | 首选方案 |
| --- | --- | --- |
| 并发层 | warm p95 排队 / 并发 session 瓶颈 | 进程隔离（非 async） |
| `.rdc.idx` | 索引类查询 > 100ms | 先定位瓶颈 API |
| 采样值比较 | unknown 分布证明深层原因需求 | 保持 optional/deep |
| Git correlation | 真实 regression workflow 需求 | Stable Core 之外的 Reasoning Layer |
| 跨 capture matching | CI 硬需求 | 独立评审 |

## 试点检查单（Phase A）

- [ ] 真实游戏/引擎 capture（非 fixture）走通 ci-record → ci-check
- [ ] IDE 打开真实 regression 并完成一次因果定位
- [ ] MCP + LLM 对真实 regression 产出 grounded 解释
- [ ] telemetry JSONL 存档 ≥ 1 周 workload
- [ ] 四类指标各形成一页结论（数据 → 决策或"不动作"）
