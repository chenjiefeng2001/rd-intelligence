# D6 Performance Evidence — 迁移是否产生可测量的查询性能回归

日期：2026-09-29
状态：**D6 evidence = measured** ｜ **D6 performance gate = UNCHANGED / NOT A GATE**

本文件只回答一个问题：MCP/IDE → WorkerManager 的进程隔离迁移是否产生了
**可测量的**查询性能回归。

**本文件不是 gate。** 它不读任何 threshold、不比较任何 threshold，其输出
不得用于把既有 workload perf gate 变成 migration gate。
`trace_pixel_bg p95 < 250 ms` 仍是既有 workload gate，**未被触碰**。

---

## 1. 方法

| 项 | 取值 |
| --- | --- |
| 环境 | 同一台机器、同一 RenderDoc build、同一 acceptance 环境 |
| capture | `rdebug-validation/captures/a-d3d11-fixture.rdc`（W1/W2 程序的冻结 fixture，405,868 B） |
| pre-migration | `git worktree` 于 `f859ca5`（M1.3 接线之前的提交），**非 in-process 代理** |
| post-migration | `HEAD`（M1.3 + M1.4 完成后） |
| 采集工具 | `scripts/bench_transport.py` —— 只使用迁移前后**完全相同**的 transport 公开面 |
| 像素 | `--discover` 一次发现后**显式传参**（covered `(2,2)` / background `(1,1)`），两棵树查询字面相同的像素 |
| cold / warm | 每个测量点**独立进程**；cold 与 warm 从不混合 |
| 样本 | warm n=25 / 点；重复轮次用于约束噪声 |

**为什么必须是独立进程**：首版设计让两个测量点共用进程，结果 covered 先跑
承担了进程预热、background 继承它，导致同一 capture 上 cold 出现 3 倍差异
（776 ms vs 2536 ms）。该数据已作废。改为一点一进程后才可用。

**为什么 pre 必须是真树**：用 in-process 直连当 baseline 会把
「有 worker 往返」与「没有往返」混为一谈，等于把待测量的东西从实验里删掉。

---

## 2. 结果

### 2.1 Warm 查询（primary）

单位 ms。`pre` / `post` 各为 3 次独立运行。

**MCP / covered**

| 指标 | pre | post | pre 极差 | post 极差 | 中位数差 |
| --- | --- | --- | --- | --- | --- |
| p50 | 32.9 / 49.4 / 40.8 | 32.4 / 36.9 / 33.9 | 16.5 | 4.5 | **-7.0** |
| p95 | 39.5 / 62.3 / 51.0 | 35.8 / 44.9 / 51.0 | 22.8 | 15.2 | **-6.1** |
| max | 39.8 / 83.0 / 59.3 | 37.5 / 58.2 / 58.9 | 43.2 | 21.4 | **-1.0** |

**MCP / background**（单次独立运行）

| 指标 | pre | post | 中位数差 |
| --- | --- | --- | --- |
| p50 | 37.8 | 34.9 | -2.8 |
| p95 | 46.4 | 37.8 | -8.5 |
| max | 47.5 | 48.2 | +0.7 |

**IDE / covered**

| 指标 | pre | post | 中位数差 |
| --- | --- | --- | --- |
| p50 | 36.8 | 33.9 | -2.9 |
| p95 | 47.1 | 39.5 | -7.6 |
| max | 50.0 | 49.1 | -0.8 |

**IDE / background**

| 指标 | pre | post | 中位数差 |
| --- | --- | --- | --- |
| p50 | 45.6 | 32.2 | -13.4 |
| p95 | 55.8 | 38.6 | -17.2 |
| max | 58.7 | 42.1 | -16.7 |

> **判定：warm 查询无可测量回归。**
> 中位数差为 -1.0 ~ -13.4 ms，而同一配置的 run-to-run 极差为 4.5 ~ 43.2 ms。
> **差异小于噪声，本设计无法分辨。** 中位数略偏快，但**不足以断言「变快了」**。

### 2.2 Cold / establish

| 测量 | pre | post |
| --- | --- | --- |
| MCP establish | 1252 / 1440 / 1534 ms | 1368 / 1529 / 1590 ms |
| MCP first query | 1849 / 4004 / 2577 ms | 2943 / 6049 / 2979 ms |
| IDE establish | 190 / 224 ms | **2945 / 2576 ms** |
| IDE first query | **2444 / 2658 ms** | 45 / 48 ms |

> **可判定的是成本位置发生了迁移，不是成本大小。**
> IDE 的进程隔离启动成本从「首查询」搬进了 `configure()`：pre 首查询
> 2444–2658 ms 而 establish 仅 190–224 ms；post 反过来，establish
> 2576–2945 ms 而首查询仅 45–48 ms。两者相加的到首响应总时间同量级
> （2.6 s vs 3.0 s；2.9 s vs 2.6 s）——但 n=3 时极差达 2–3 s，
> **因此「迁移增加了多少一次性启动成本」在本样本量下不可判定**。

---

## 3. 归因边界

### 可以陈述

1. **Warm 查询未出现可测量回归。** 迁移新增了一次进程往返，但 warm 查询成本
   在本设计下未变到可分辨的程度。
2. **IDE 的一次性启动成本发生了位置迁移**（首查询 → `configure()`），
   这是结构性观察，在每次运行中都成立，与幅度的噪声无关。
3. **迁移移除了一个每请求成本。** pre-migration 源码
   `rdebug/session_cache.py:30,41` 在**每一次** `use()` 上调用
   `self._probe(session)`，默认实现是 `lambda s: s.root_actions()`——
   即每个请求都过一次 replay controller。post-migration 的 WorkerManager
   只做 `proc.poll()`。**这是代码事实，不是推断。**

### 不可陈述

1. **不能说「warm 变快了 7 ms」。** 差异小于 run-to-run 噪声。
2. **不能说「所有性能变化都由进程往返造成」。** 移除每请求 health probe
   的效应方向与「往返开销」**相反**，本设计无法把两者分离。
3. **不能对本 capture 的 p95 与 `trace_pixel_bg p95 < 250 ms` gate 作比较。**
   该 gate 跑在 `tests/workload/corpus/`（14-capture 语料，多档 draws）上，
   而本证据用的是单 draw 的 D3D11 fixture。**本测量对该 gate 的余量不构成
   任何结论。**

---

## 4. 与 D4 的关联（重要）

第 3 节第 3 点必须与 M0 §5.3 一并读：

`SessionManager` 的 `health_probe` 是**遗留路径中唯一的正确性机制**
（M0 实测：`WorkerManager` 只检测进程存活，worker 可以活着但持有被污染的
controller）。因此：

> **warm 路径上观察到的「不慢」，部分来自移除了每请求的 unhealthy 检测。
> 这是 D4 defer 的代价侧，不是免费的性能收益。**

D4 仍为 **DEFER**，本文件不改变该状态，也不建议因本数据而改变它。

---

## 5. 结论

```
D6 performance evidence  OPEN → measured
D6 performance gate      UNCHANGED / NOT A GATE
M1 migration             COMPLETE（不因本文件改变）
D4 health probe          DEFER
D5 telemetry basis       DEFER
D7 cross-machine         OPEN
```

**无新的 blocker。** 迁移的 warm 路径未出现可测量回归；一次性启动成本在
IDE 上表现为位置迁移，其大小在 n=3 下不可判定。

**未因本数据触发任何优化、threshold 修改或架构变更。** 按授权，本文件的
结论只能是「measured / not measured」。

---

## 6. 复现

```powershell
git worktree add <tmp> f859ca5          # pre-migration
$env:RDEBUG_RENDERDOC_PATH = "<renderdoc pymodules>"
$env:PYTHONPATH = "<tree>\src"; $env:RDEBUG_SRC = "<tree>\src"

# 1) 发现像素（只做一次）
python scripts/bench_transport.py --capture <a.rdc> --transport mcp --mode discover
# 2) 采集（每点独立进程，pre 与 post 各跑一遍）
python scripts/bench_transport.py --capture <a.rdc> --transport mcp --only covered `
    --covered 2,2 --background 1,1 --warm 25 --label pre --json pre.json
# transport 换 ide 亦同；PYTHONPATH 指回 post 树再跑一遍
```

已知的两处本轮方法错误（已作废其数据，保留记录）：

| 错误 | 后果 | 修正 |
| --- | --- | --- |
| 两个测量点共用进程 | covered 承担进程预热，background 继承，cold 出现 3 倍虚假差异 | 一点一进程（`--only`） |
| 重复轮次的 pre/post 写同一个文件名 | post 覆盖 pre，噪声估计失效 | 分 tag 命名（`v4-pre-*` / `v4-post-*`） |

两者都是**看起来在测量什么、实际测错了**的类型，与本项目此前记录的
「用错键的断言」同类。
