# Phase 5d：Workload Test v1 首轮报告

日期：2026-08-24 · 套件：`tests/workload/`（10 tests）· Runner：`scripts/workload_run.py`
原始数据：`tests/workload/reports/workload-report.json` + `telemetry.jsonl`
**GATE: FAIL（发现 2 个真实可靠性缺陷——这正是 workload 测试的目的）**

## Corpus

14 captures（fixture 自产）：S×7（4–34 events）/ M×4（515–2050 events）/ L×2（10002、20002 events）。
XL（>100k）需真实游戏 capture，harness 已支持（放入 corpus 目录即自动发现）。

## 查询量（本轮）

trace_pixel 830 · trace_resource 513 · diff_pixel 560 · debug_pixel 247 · sweep 3 ≈ **2153 queries**

## 通过项（Correctness 全绿）

| 项 | 结果 |
| --- | --- |
| Deterministic replay（S+M，×10 全同） | PASS |
| Cold == Warm（20 warm runs 逐键等价） | PASS |
| Evidence integrity（含篡改检出） | PASS |
| Three-state 稳定（40 cases 无翻转） | PASS |
| Debugging sessions（25 条完整 trajectory） | PASS |
| Stress（2000 随机混合查询，0 崩溃 0 污染） | PASS |
| Isolation / Error-injection / MCP-contract（子进程隔离） | PASS |

## 发现的缺陷（GATE FAIL 的原因）

### WLF-1：LRU 驱逐路径原生 AV（高优先级）

- 现象：`SessionManager(max_sessions=2)` + 4 captures × 12 cycles（驱逐+reopen 交错）
  → 子进程 **0xC0000005 ACCESS VIOLATION**（两次全量运行 + 单独复现，高概率/近确定性；
  stdout 空 = 崩溃点在早期 native 调用）。
- 不复现路径：无驱逐顺序 open/close ×48、单 capture 循环 ×12、max=6 温和驱逐 + 长寿命
  manager、隔离场景交错 ×7——**驱逐 dispose 与其他存活 session 交错**是关键变量。
- 影响：长会话多捕获场景（IDE 长开 + 换 capture）可能触发 IDE/MCP 进程崩溃。
- 短期规避：CI/Agent 使用"单 capture per process"或 `max_sessions ≥ 工作集`（避免驱逐）。
- 根因方向：上游 RenderDoc native（controller/cap Shutdown 交错）；需最小 repro 上报
  或在 transport 层做规避（延迟/串行 dispose）——按规范需单独评审，不擅自改。

### WLF-2：偶发原生挂起（低优先级）

isolation 场景一次运行挂起 >15 分钟（无输出），直接复现秒级通过——偶发 native
死锁/挂起。`run_isolated` 的 600s 超时兜底已覆盖。

## 性能画像（本轮，含 L tier）

| 查询 | p50 | p95 | p99 | 备注 |
| --- | ---: | ---: | ---: | --- |
| trace_pixel | 18.3ms | 156.8ms | **5208ms** | p99 由 L tier 高重叠像素（10k/20k mods）主导 |
| trace_pixel_bg | 103.8ms | 178.1ms | 397.0ms | n=40 含 L tier 冷启动 |
| trace_resource | 5.4ms | 9.3ms | 67.4ms | 健康 |
| diff_pixel | 148.7ms | 199.1ms | **5704.0ms** | 同 trace_pixel |
| debug_pixel | 301.1ms | 4874.2ms | 5871.7ms | 含 L tier covered history 成本 |

**延迟 ↔ pixel modifications 强相关**再次确认。Unknown 分布：
`shader 568 / shader_input_values 568 / resource_provenance 558 / fragment 10`
——unknown 集中于 shader 相关层（结构性：一侧无 PS），与 4c 结论一致。

## 结论与下一步

1. **语义层可靠性优秀**：2153 次真实 replay 查询，0 错误结果、0 污染、0 三态翻转。
2. **WLF-1 是 v1 唯一阻塞级缺陷**：修复路径二选一（上游上报最小 repro / transport 规避），
   修复后重跑 workload gate。
3. 规避措施已验证可用：单 capture per process 模式下 2000+ 查询零崩溃。
4. L tier 纳入后 p99 数据为"是否需要 per-pixel 采样策略"提供了量化依据（暂不动）。
