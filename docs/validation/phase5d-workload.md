# Phase 5d：Workload Test v1 首轮报告

日期：2026-08-24 · 套件：`tests/workload/`（10 tests）· Runner：`scripts/workload_run.py`
原始数据：`tests/workload/reports/workload-report.json` + `telemetry.jsonl`
**Round 1 GATE: FAIL（发现 2 个真实可靠性缺陷——这正是 workload 测试的目的）**
**Round 2（2026-08-25）GATE: PASS** —— 见文末《Round 2：WLF-1 处置与 gate 重定义》。

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

## Round 2：WLF-1 处置与 gate 重定义（2026-08-25）

### WLF-1 修复（transport 层规避，Stable Core 语义不变）

`SessionManager` 改为**先驱逐、后打开**：在创建替换 session **之前**驱逐 LRU 受害者
（`_evict(keep=key, room=1)` 前置），废弃原"打开后驱逐"路径。根因观察：在新 replay
controller 已存在后 dispose 旧 controller，首次调用新 controller 时原生崩溃
（0xC0000005）；close-then-open 顺序从未复现。

验证：
- 独立复现场景 `lru_cycles`（max=2 × 4 captures × 12 cycles，修复前近确定性崩溃）
  连续 3 次运行 exit=0；
- 完整套件内 `reliability[lru_cycles] exit=0`；全量重跑可靠性五项全零
  （0 crash / 0 unhandled / 0 failedRecovery / 0 corruption / 0 contamination）。

WLF-2（偶发原生挂起）：本轮两轮全量均未复现；600s 子进程超时兜底持续覆盖，维持观察。

### Runner 缺陷修复：空跑假阳性 PASS

Round 1 之后的一次重跑产生了 queries/latency/correctness 全空但 `gate: PASS` 的报告：
`workload_run.py` 构造的 env dict 从未应用——测试同进程执行读取的是 `os.environ`，
未预设 `RDEBUG_RENDERDOC_PATH` 时全部套件被跳过，空转成 PASS。修复：

- 环境变量直接写入 `os.environ`（隔离子进程经继承获得）；
- gate 增加**非空转守卫**：`queries>0 ∧ correctness>0 ∧ testsRun>0`，
  否则一律 FAIL。

### perf 判据重定义（owner 决策：分族群设门禁）

原判据"所有非 debug 工具 p95<100ms"混合了两个负载族群，结构性不可通过：
廉价查询族（bg 像素 / resource，毫秒级）与 covered 像素深回放族（秒级，
成本由 pixel modifications 主导）。ff18fee 当轮即以 trace_pixel p95=156.8ms 违反；
2026-08-25 的 S/M-only 复测（无 L tier）仍 p95=358ms，证明与 L tier 无关。

新判据只守护**warm 回归哨兵族**（与 REAL_WORLD_VALIDATION 的 warm 基线语义一致）：

| 族 | 判据 | 本轮实测 |
| --- | --- | --- |
| trace_resource p95 | < 100ms | 44.62ms ✓ |
| trace_pixel_bg p95 | < 250ms | 125.13ms ✓ |
| 深回放族（trace_pixel covered / diff_pixel / debug_pixel） | 仅报告观察，不设门禁 | 见下表 |

深回放族延迟 ↔ modifications 强相关维持 Round 1 结论；是否需要 per-pixel 采样策略
继续留待 Phase B 数据驱动决策。

### Round 2 性能画像

| 查询 | p50 | p95 | p99 | n |
| --- | ---: | ---: | ---: | ---: |
| trace_pixel | 54.6ms | 1335.5ms | 4710.6ms | 830 |
| trace_pixel_bg | 82.0ms | 125.1ms | 462.0ms | 40 |
| trace_resource | 7.5ms | 44.6ms | 95.4ms | 513 |
| diff_pixel | 280.5ms | 1947.3ms | 5224.0ms | 560 |
| debug_pixel | 557.6ms | 4411.8ms | 6339.8ms | 247 |

Unknown 分布与 Round 1 完全一致（shader 568 / shader_input_values 568 /
resource_provenance 558 / fragment 10），与 Phase 4c 结论吻合。

### Round 2 GATE

**PASS**（10 tests OK · 2193 queries · correctness 11/11 · 可靠性五项全零 ·
非空转守卫通过 · 分族群 perf 判据通过）。
