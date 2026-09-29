# M0 — SessionManager → WorkerManager 迁移：范围与验收设计

状态：**DESIGN ONLY / FROZEN FOR REVIEW**。本文件不授权任何代码修改。
日期：2026-09-29
基线：`rd-intelligence @ 7d53f73`（工作树干净，审计 17/17 + 1 deviation）

---

## 1. Objective

把 MCP / IDE 的每个 capture 请求从进程内 SessionManager 迁移到独立 worker 进程：

```text
现状                                     目标
─────────────────────────────           ─────────────────────────────
MCP / IDE                                MCP / IDE
    ↓                                        ↓
SessionManager                           WorkerManager
    ↓                                        ↓
CaptureSession ×N（同一进程）             dedicated worker process ×N
    ↓                                        ↓
1 个 replay runtime                      1 个 replay runtime
  + N 个 ReplayController 并存              + 1 个 ReplayController
                                          （互不影响）
```

**这不是架构洁癖。** `core.py:31` 的 `_REPLAY_LIFECYCLE` 是**进程级全局**，
`InitialiseReplay()` 每进程只调用一次（`core.py:174-177`），而每个 `CaptureSession`
各自持有 `_cap` / `_ctrl`。因此 N 个 session 共享 1 个 runtime 却并存 N 个 controller。

M0 实测（D3D11 workload 语料，非 N3 封存 capture，只读结构观察）：

```
BEFORE any session : {'initialised': False, 'sessions': 0}
opened w00016_frame11.rdc  -> live sessions=1  initialised=True
opened w00064_frame11.rdc  -> live sessions=2  initialised=True

shared renderdoc module id : {2850552775360}
distinct ReplayController   : 2
distinct ICapture           : 2

=> 2 个 live ReplayController 与 1 个 replay runtime 共存于 1 个进程
```

这正是 `DESIGN_SPEC.md:126-127` 记录的 W1-R1 F-1/F-2 形态
（静默值污染 / 原生挂起 / 0xC0000005）。

### 1.1 暴露面并不对称（M0 新发现，修正了原判断）

| Transport | capture 数量 | 现状风险 | 依据 |
| --- | --- | --- | --- |
| **MCP** | **每次调用自带 `capture` 参数** | **主要暴露面**——多 capture 并存是**正常使用形态** | `server.py:82,111,136,169` 各自传自己的 `capture`；`SessionManager(max_sessions=4)` 默认 4 |
| IDE | 单一 `_STATE["capture"]` | **潜伏**，非活跃 | `app.py:43` 恒用同一个 capture → 1 个 controller。`configure()` 二次调用才会并存（见 §5.2） |
| CLI | 每次调用 1 个 | **无风险** | `cli.py:21-26` 绕过 SessionManager，直接 `CaptureSession`，进程内 1 个 |

**结论：MCP 优先，IDE 次之，CLI 不在范围内。** 原裁决把 MCP/IDE 并列，
实际 MCP 才是 F-1/F-2 的复现位置。

---

## 2. 迁移必须保持的东西（Contract 不变）

这些是**硬约束**。任何一条被破坏即 migration FAIL，与测试是否全绿无关。

| # | 不变量 | 依据 | 破坏形态（来自本轮 20 项缺陷的教训） |
| --- | --- | --- | --- |
| C1 | **语义失败不得伪装成语义结果** | §2.5 | F12：`[]` vs `[]` → `same`。迁移后所有 payload 来自反序列化，空值语义必须保持 |
| C2 | **transport failure 必须返回 response body** | §2.6 | F19：`KeyError` 逃出 handler → 连接被丢弃、无 body |
| C3 | **worker death 必须可检测** | §2.9 | 必须能从 transport 观测到死亡，不能静默换进程 |
| C4 | **recovery 必须是 detect → bounded retry respawn → verify** | §2.9 | 不得引入无限重试；不得跳过 verify |
| C5 | **recycle 仍按现有 policy**（q250 / Δ128MB / 1800s） | §2.9 | 不得为迁移放宽或绕过 |
| C6 | **`private_memory_bytes/delta` 仍是唯一内存门禁** | §2.9 | F15 的教训：不得引入 RSS 回退 |
| C7 | **W1-R4 / W2 已有行为不得被悄悄改变** | 冻结验收 | 语义结果、门禁判定、事件口径 |
| C8 | **四个 Semantic API v1 工具的签名与 JSON 形状不变** | Semantic API v1 冻结 | 客户端与 LLM 依赖 |

---

## 3. 迁移验收项（8 项，逐项给出可测方法）

**验收项不是 checklist，而是 gate 的输入。** 每项必须给出可复现的判定命令或产物。

| # | 验收项 | 判定方法 | 当前可测？ |
| --- | --- | --- | --- |
| A1 | MCP 请求确实进入新 worker path | 运行时断言：transport 进程内无 `CaptureSession` 实例；请求产生独立子进程 pid 且随 capture 稳定 | ❌ **需 M1 加运行时断言点**（见 §6-D1） |
| A2 | 每个 capture 获得独立 replay runtime | 两个不同 capture 的 worker pid 不同，**且各自进程内 `_REPLAY_LIFECYCLE["sessions"] == 1`** | ❌ **需 M1 加 worker 内省 op**（见 §6-D2） |
| A3 | SessionManager 不再拥有 replay runtime | 静态 Gate A（§4.1）+ `session_cache.py` 无生产调用方 | ✅ **可立即测**（已验证 FAIL） |
| A4 | worker death 后按既定 recovery contract 工作 | 杀 worker → 下一查询经 `detect→bounded retry→verify` 自愈；断言 `recycle_events` 含 `worker_died` 且结果语义正确 | ✅ 已有 `test_worker_manager.py:352` 同类覆盖 |
| A5 | semantic error / transport error 保持 failure 语义 | 已知失败输入矩阵：坏 resource / 坏坐标 / 缺参数 / 坏 capture / 不可调试 shader，逐项断言返回形状与异常类型 | ⚠️ **部分不可测**，见 §6-D3（最大风险项） |
| A6 | shutdown/reload 不留 registry ghost state | 重复 dispose/重配后 `captures() == []`、无存活 pid、`unkillable() == []` | ✅ 可测（`unkillable()` 已存在） |
| A7 | IDE bad-parameter path 仍返回 JSON | 现有 3 个测试（`test_ide_app.py:48-67`）必须在迁移后仍 PASS | ⚠️ **依赖 D3** |
| A8 | 迁移前后 semantic result 一致 | 同一 capture 同一查询，迁移前后 payload **逐字节相等**（`phase4d` 的 cold==warm 等价检查扩展到跨迁移） | ✅ 可测（`scripts/session_bench.py:93-96` 已有该模式） |

**A2 与 A3 可立即判定；A1、A2、A5 需 M1 先补内省能力。** 不得以「测不了」
为由跳过——见 §7。

---

## 4. Migration Gate

**明确定义：migration PASS ≠ 测试全绿。** Gate 由五层构成，缺一不可：

```text
┌─ G1 architecture invariant ── 进程边界真的建立了吗
├─ G2 runtime behavior ───────── 隔离真的生效了吗
├─ G3 failure semantics ──────── 失败仍然像失败吗
├─ G4 semantic equivalence ───── 结果真的没变吗
└─ G5 recovery ───────────────── 崩溃后真的自愈吗
```

「测试全绿」只属于 G4 的一个子集。**F12 的教训**：15 项审计全绿的情况下，
一个能把错误结果送进 CI baseline 的缺陷通过了全部检查。

### 4.1 G1 机械架构检查（Gate A）

> 规则：production transport dispatch path 不得 import 或实例化遗留的
> 进程内 `SessionManager`。

实现：AST 扫描 transport 包（`rdebug_mcp` / `rdebug_ide` / `rdebug`），
匹配 `SessionManager(...)` 调用与 `rdebug.session_cache` import。

**已按项目纪律完成验证**（观测证据）：

| 对照 | 期望 | 实测 | 结论 |
| --- | --- | --- | --- |
| **当前树** | FAIL | **4 处违规**：`rdebug_ide/app.py:19` import、`:39` 构造；`rdebug_mcp/server.py:17` import、`:34` 构造 | ✅ **FAIL，符合预期** |
| 负对照：已迁移形态（`WorkerManager`） | PASS | 0 | ✅ |
| 正对照：遗留形态 | FAIL | 2 | ✅ |
| 假阳性对照：仅注释中提及 `SessionManager` | PASS | 0 | ✅ 无误报 |

### 4.2 G1 机械架构检查（Gate B，更深的那个）

> 规则：**一个进程内最多只能有一个 live ReplayController。**
> `CaptureSession.__init__` 必须在 runtime 已存活时**拒绝**创建第二个。

Gate A 只检查「不再使用 SessionManager」。Gate B 检查**不变量本身**——
任何未来调用者（不经 manager）打开第二个 session 也会被抓到。
这才是 `DESIGN_SPEC §2.9` 第一条 MUST 的直接机械表达。

实现：`CaptureSession.__init__` 的 AST 中必须存在一个条件分支，
其条件引用 `_REPLAY_LIFECYCLE` 的 `sessions` 计数，且分支体含 `raise`。

> 注：计数器本身不需要移除。检查的是**拒绝路径**是否存在，
> 不是「计数是否消失」。本次设计中第一版把不变量写成后者，
> 被负对照当场证伪（见 §8）。

**验证结果**：

| 对照 | 期望 | 实测 | 结论 |
| --- | --- | --- | --- |
| **当前树** | FAIL | 1 处违规：`__init__` 无「runtime 已存活则拒绝」的分支 | ✅ **FAIL，符合预期** |
| 负对照：加入拒绝路径 | PASS | 0 | ✅ |

**M0 未把这两条 Gate 装进 `audit_boundaries.py`**（那属于 M1）。
当前 `audit_boundaries.py` 的 `DEVIATION` 机制保持不变，
但 M1 落地时应把 DEVIATION 转为硬检查。

---

## 5. 迁移特有风险（M0 排查结论）

### 5.1 异常类型断裂 —— 最高风险

`WorkerError(RuntimeError)` **不是** `RDebugError`。而每个 transport 的错误处理
都只捕获 `RDebugError`：

| Handler | 位置 | 捕获 | 漏掉 `WorkerError` 的后果 |
| --- | --- | --- | --- |
| MCP | `server.py:54` | `RDebugError` | 逃给 FastMCP → 未处理的 tool error |
| IDE | `app.py:199` | `RDebugError` | 逃出 `route()` → **连接被丢弃、无 body**（F19 同款失败） |
| CLI | `cli.py:196` | `RDebugError` | 未捕获 traceback |

且存在**两条不同的错误通道**，哪条触发会改变可观测行为：

1. **结构化查询错误会变成 payload 而非异常**：`workers.py:214-216` 捕获
   `RDebugError` 并以 `ok:true` 返回 `{"error":...}`。于是 MCP 的
   `except RDebugError` 不再触发 → **`query_error` 遥测事件静默消失**
   （`REAL_WORLD_VALIDATION.md:27` 依赖它）。
2. **启动期错误类型全丢**：`CaptureOpenError`（`core.py:214/219/229`）发生在
   `workers.py:147` 的 ready frame 之前，只能以 `WorkerError` + `stderr_tail`
   文本返回。`test_session_manager.py:86` 的 `assertRaises(CaptureOpenError)`
   **按原样无法修复**。

**F-3 边界**：worker 内 `KeyError` 返回后是 `WorkerError`，
不再触发 IDE 的 `(KeyError, IndexError, ValueError, TypeError)` 分支 → A7 受威胁。

### 5.2 IDE ghost state

`configure()`（`app.py:39`）重新绑定 `_manager` 而**不 dispose 旧的**；
`SessionManager` 无 `__del__`，故其 `_sessions` 被 GC 时**不执行 `_quiet_close`**。

生产影响：潜伏——`main()` 只在 `app.py:255` 调用 `configure()` 一次。
测试影响：活跃——`test_ide_app.py` 在同一进程调用 13 次。

后果链：
1. live ReplayController + OpenCaptureFile 句柄从不 `Shutdown()`
2. `_REPLAY_LIFECYCLE["sessions"]` **永久虚高**（只有 `core.py:258` 的 `close()` 会减）
3. 因此 `shutdown_replay()`（要求 `sessions == 0`）**永久不可达**——
   而它在本仓库**从未被调用过**
4. 新 session 因 `initialised=True` 跳过 `InitialiseReplay()`——
   避免了 F-N3-4 双初始化，但**正好落入 §2.9 禁止的多 controller 并存**

即：**进程被静默降级，而非立即崩溃。对一个正确性工具，这是最坏的失败形态。**

M1 须把 `configure()` 的重配与 dispose 配对。

### 5.3 能力回退：health probe 无对应物

`SessionManager` 的 `health_probe`（`session_cache.py:30,40-48`）是**遗留路径中
唯一的正确性机制**：session 的原生状态坏了就被探测到并替换。

`WorkerManager` **没有 health probe**——其检测只有 `w.alive()`（进程存活）。
**worker 可以活着但持有被污染的 controller。**

而 `DESIGN_SPEC.md:139` 冻结的恢复模型是
「detect（dead/**unhealthy** 或策略触发）」——**"unhealthy" 在迁移后无实现。**

这是一次**真实的能力回退**，M0 不掩盖它。三条候选处置见 §6-D4。

### 5.4 顺带收益：WLF-1 workaround 变成死代码

`session_cache.py:50-55` 的「先 evict 后 open」是为绕过
0xC0000005 而加的 WLF-1 变通。进程边界使交错 `Shutdown()` 不再可能，
该 workaround 自然作废。`tests/workload/scenarios.py:107-115` 的
`scenario_lru_cycles` 同理失效——**这是支持迁移的最强证据之一**。

### 5.5 telemetry 契约

`WorkerManager` 目前**零遥测**——只有内存里的 `recycle_events`。

| 事件 | 状态 | 处置 |
| --- | --- | --- |
| `session_open` / `session_reuse` / `session_evict` | **载荷级**：5 处测试断言 + 4 类文档化指标 | 必须在 worker 路径重新发出，或显式换基（§6-D5） |
| `session_recovery` / `session_probe_failed` / `session_open_failed` | 已文档化但**归档中零发生** | 最便宜的可版本化对象 |
| `worker_*` | **不存在** | 需新增命名空间 |

若全部 `session_*` 静默消失，`REAL_WORLD_VALIDATION.md:9`（性能指标类 1）与
`:26-27`（恢复指标类 4）会**同时失效**——而后者正是本次迁移的论证依据。

### 5.6 其他已识别变化

| # | 变化 | 依据 |
| --- | --- | --- |
| 1 | 调用形状从 `with _open(c) as s: analysis(s,…)` 变为 `mgr.query(...)` | `worker_manager.py:463` |
| 2 | `workers.py:34-72` 的 dispatch 是**手工镜像**，参数名与 MCP 签名不同（如 `max_writers` vs `max_writers_per_resource`）。**任何 MCP 参数改名会静默破坏 dispatch** | 需在 M1 收敛为共享规格 |
| 3 | worker 的 foreign-capture 守卫 `workers.py:204-209` 依赖 args 里的 `capture`，但 `WorkerManager.query()` **不注入** `capture` → 守卫**空转通过**。§2.9 不变量只由 registry key 保证 | M1 须让 transport 显式转发 `capture` |
| 4 | 出现 600s 超时 → 硬杀 worker + 非 transient 错误，**单次调用中断**（下次调用自愈） | `worker_manager.py:254-261` |
| 5 | IDE `ThreadingHTTPServer` 下的 `_manager._sessions` 竞态**被修复**（`_Worker.request` 持锁串行化）——行为改善但会改变时序 | `session_cache.py:5-7` 已知不线程安全 |
| 6 | `pipeline(event_id=None)` 返回 `_current_eid`（`core.py:620-622`），其值将**取决于该 worker 此前服务过多少查询**，且 recycle 后重置 | 真实边缘情形 |
| 7 | `/api/stats` 读 `_manager.stats()`，无对应物 | `app.py:172`，公共 endpoint |
| 8 | perf gate `trace_pixel_bg p95 < 250ms` vs 基线 100–180ms——**唯一有风险的阈值**，仅 1.5× 余量 | `workload_run.py:67-69` |
| 9 | `scripts/diff_closure.py:13-27` 把方法 monkeypatch 到活 session 上——跨进程**结构性不可能** | 需改为 worker 侧计数 |

---

## 6. 裁决记录（2026-09-29，负责人裁决）

| 项 | 裁决 | 理由 |
| --- | --- | --- |
| **D1** 内省点 | **接受，限诊断/验证，不进 Contract** | 可定位 controller/runtime 生命周期，但不得把实现细节升级为协议不变量 |
| **D2** 内省点 | **接受，同上** | 作为迁移验证的辅助证据；不得成为生产正确性的必要条件 |
| **D3** `WorkerError` 层级 | **接受，优先处理** | 现有错误语义的直接断裂。改为 `RDebugError` 子类是**最小、局部**的修复 |
| **D4** 通用 health-check | **拒绝作为 M1 迁移项** | §2.9 明文禁止在无 telemetry 证据时重新引入；不能为补迁移后的理论能力而违反冻结设计 |
| **D5** telemetry 换基 | **暂缓** | 迁移首先解决 runtime isolation；无证据表明现有 telemetry 阻碍 M1 验收时，不应同时改变观测基线 |
| **D6** perf gate | **暂缓，不加入 M1 blocker** | 当前问题是 correctness/isolation；除非迁移本身产生明确性能回归证据 |
| **D7** 范围 | **收窄为 MCP；IDE 保留验证项；CLI 移出** | 暴露面已实测分开：MCP 是正常 multi-capture 形态；IDE 是潜伏 ghost 风险；CLI 已是单 capture/进程 |

### 6.1 D3 的裁决附加要求

裁决明确要求 D3 不能只验证 `WorkerError → RDebugError`，还须验证
**错误语义没有在边界处再次被吞掉**：

```text
worker failure → WorkerError → RDebugError-compatible
               → transport handler → JSON response body
               → query_error telemetry
```

至少覆盖两条现有失败模式：**IDE**（worker error → 有 body，不丢连接）与
**MCP**（worker error → JSON error payload，同时 `query_error` 可观测）。
已在 `tests_transport/test_error_boundary.py` 实现（15 tests），
并含**负对照**，防止 D3 被以「加宽 handler」的方式假修复：
若两个 transport 都改成 `except Exception`，上述测试**全部仍会通过**，
因此另有 4 项测试断言无关异常**必须继续逃逸**（转成 400 只会把 bug 藏起来）。

### 6.2 health probe 的定位

**迁移后没有 `unhealthy` 检测，不等于迁移失败。**

当前冻结的恢复模型是 `detect(dead / policy-triggered) → bounded retry respawn → verify`。
M0 已证实现存「live but internally contaminated controller」，
因此这是一条**已知能力边界**；但在 telemetry 证明它需要生产级通用检测之前，
不能因为迁移暴露了这个边界就反过来把 health-check 引入架构。

**M1 的目标是消除已证实的 shared-runtime isolation violation，
不是顺手解决所有潜在的 unhealthy-runtime detection 问题。**

### 6.3 M1 正式顺序

```text
M1.0  D3 修复 + 回归闭环              ← 已完成（本轮）
  ↓
M1.1  GATE B：≤1 live ReplayController
  ↓
M1.2  GATE A：transport 不得 import/construct SessionManager
  ↓
M1.3  MCP 接入 WorkerManager
  ↓
M1.4  IDE 接入 WorkerManager
  ↓
M1.5  migration acceptance matrix
```

**M1.1 / M1.2 必须再次执行三对照纪律**（见 §10）。
且 **GATE B 必须检查实际不变量**（「一个进程内不存在第二个 live
ReplayController」），不得检查某个计数器是否存在/消失——
后者是当前实现的影子检查。

### 6.4 关键设计判断：两道 Gate 在 M1.1/M1.2 只能是 DEVIATION

**这是对裁决顺序的一处必要偏离，需要确认。**

若在 M1.1/M1.2 就把 Gate A / Gate B 设为**硬失败**：

- Gate B 硬失败 = `CaptureSession.__init__` 拒绝第二个 controller
  → **MCP 立刻坏掉**（`max_sessions=4` 是它的正常使用形态）
  → `tests/workload` 的 isolation 场景与
    `test_different_captures_isolated` 同时失败
- Gate A 硬失败 = 审计转红（当前树确实违规）

因此 M1.1/M1.2 的正确姿态是：

| 组件 | M1.1/M1.2 形态 | M1.3 起 |
| --- | --- | --- |
| Gate A（审计） | DEVIATION，带精确证据行号 | 硬检查 |
| Gate B（审计） | DEVIATION，**并明确标注是 PROXY** | 硬检查 |
| **§2.9 不变量本身** | `tests/integration/test_runtime_isolation.py` 的 **expectedFailure** | 同一断言自动转绿 |

关键点：**不变量的真实验证是运行时的那个 expectedFailure 测试，
不是审计里的静态 proxy。** 审计只能证明「执行手段存在」，
证明不了「性质成立」——所以 Gate B 在审计里被显式标注为 PROXY。

`expectedFailure` 而非 `skip`：违规是真实的且必须保持可见。
M1.3 落地后该测试会开始通过，unittest 随即报 `unexpectedSuccess`
**使套件失败**，直到装饰器被移除——这正是意图：
违规无法被遗忘，修复也无法被悄悄放过。

---

### 6.5 M1 执行记录

| 阶段 | 状态 | 关键产出 |
| --- | --- | --- |
| M1.0 D3 | **完成** | `WorkerError` 改为 `RDebugError` 子类；15 tests 钉住完整链路（9 个经回退验证会 FAIL） |
| M1.1 GATE B | **完成** | 运行时不变量测试；`expectedFailure` 迁移锁 |
| M1.2 GATE A | **完成** | AST 化；三对照验证 |
| M1.3 MCP 接线 | **完成 / ACCEPTED** | 两个 capture → 两个 worker PID |
| M1.4 IDE 接线 | **完成** | ownership/dispose 配对；GATE A 转硬检查 |
| M1.5 acceptance matrix | 未开始 | — |

### 6.6 D1/D2 落地形态：可证与不可证的分界

M1.4 完成后实测（真实 RenderDoc，`w01024` / `w00064`）：

| 判定 | 证据 | 结论 |
| --- | --- | --- |
| **A1** | 两个 capture → `worker_pid` 7432 / 51904，`worker_instance_id` 不同 | **process isolation 已证实** |
| | MCP transport 本进程 `live_controllers == 0` | |
| | 每个 worker `initialise_epoch == 1` | F-N3-4 双初始化条件不存在 |
| **A2** | `runtime.identity` = `unobservable`；`controller.identity` = `unobservable` | **runtime isolation 不可判定** |

**RenderDoc 不暴露 replay runtime 或 ReplayController 的任何公开身份**
（模块无 `ObjectIdentity`/`ObjectId`，`ReplayController` 无 identity 类成员）。
因此按 D2 裁决「无法可靠取得则降级记录为不可观测，不得用代理值冒充」：

- **不得**用 PID 冒充 runtime identity。PID 不同是真实的 **process 隔离**，
  但把它写成 runtime 级观察就是夸大。
- `opaque_local_token` 命名为「不透明本地 token」即为此：它**不是**
  RenderDoc 级身份，且**跨进程不可比**；两个不同的 `id()` 不是身份断言。

**M1.5 必须继续维持这个措辞。**「两个独立 replay runtime」只能作为
**架构假设**陈述，不能写成直接观测事实。

### 6.7 M1.4 的一处必要偏离：迁移锁的最终形态

裁决要求「M1.4 完成后主动移除 `expectedFailure` 装饰器」。执行时发现：
按字面移除后测试**立即失败**——这是正确的。

`SessionManager` 作为类仍然存在且可被任何人 import，仍然允许单进程内
多个 live `ReplayController`。这与「没有 transport 使用它」是**两个不同的事实**，
而迁移在两者之下都已完成（GATE A 已是硬检查）。

因此把两者拆开：

| 事实 | 承载方式 |
| --- | --- |
| 没有 transport 使用 `SessionManager` | GATE A **硬检查**（重引入 import 即审计转红） |
| `SessionManager` 类本身允许多 controller | `test_session_manager_permits_multiple_controllers_hazard_pin` **正向断言**该风险 |

保留 `expectedFailure` 反而是**错误的终态**：它会持续暗示「还有修复待办」，
而这个类现在正确的状态就是「保持不用 + 风险被记录在案」。

### 6.8 M1.4 顺带修掉的两个审计假阳性

均为「惩罚把学到的东西写下来」的类型，与 §10 记录的第三次实例同类：

| 检查 | 原实现 | 后果 | 处置 |
| --- | --- | --- | --- |
| `2.6 transports free of RenderDoc API` | 子串扫描 `ReplayController` 等 | 在 `rdebug_ide/app.py` 的 docstring 里写「isolates a ReplayController per process」即触发 | 改为 AST（属性访问 / 裸名 / 调用 / 真实 import），8 项对照验证 |
| `2.9 GATE A` | 同为 AST，但作为 deviation 存在 | 迁移完成后即成为「永远不会失败」的检查 | M1.4 完成后**转硬检查**，重引入 import 实测转红 |



M1 完成后必须全绿。**「重命名即通过」不算通过**——属性保留、机制变更
的测试必须重写为新机制下的等价断言。

| 组 | 现状 | M1 预期 | 备注 |
| --- | --- | --- | --- |
| `tests/unit/*` | 112 PASS | 不变 | 与 transport 无关，不应动 |
| `tests_transport/test_transport.py` | 7 PASS | 4 个 tool 测试不变（payload 断言），`setUp/tearDown` 的 session 注入机制改 | `TransportInvariants` 3 项天然满足 |
| `tests_transport/test_session_manager.py` | 8 PASS | **全部重写或删除**。`health_probe` / LRU / `recoveries` 无对应物 → 删除或重定义 | 含 A4 的等价覆盖 |
| `tests_transport/test_observability.py` | 8 PASS | 4 个 break（session_* 事件名）→ 依赖 D5 | |
| `tests_transport/test_ide_app.py` | 11 PASS | 1 个 break（`test_session_reused_across_calls` → 改为 pid/recycle 断言）；**A7 的 3 个测试必须仍 PASS** | ghost state 复现器 |
| `tests/workload/*` | 10 PASS | **结构性耦合**。`harness.py:131-143` `full_plan` 闭包持有单个 session，跨进程无法表达 | `lru_cycles` / `mcp_contract` 需重做 |
| `tests/unit/test_worker_manager.py` | 34 PASS | 扩展：加 transport 接线层测试 | 已是不依赖 RenderDoc 的主力 |
| `scripts/session_bench.py` | 可用 | 重写 import（`:13` 从 transport import SessionManager） | A8 的执行者 |
| `scripts/mcp_smoke.py` / `ide_smoke.py` | 可用 | 迁移前后**字节级对照** | 端到端 canary |
| `audit_boundaries.py` | 17/17 + 2 deviations | **18/18 + 1 deviation**（GATE A 转硬检查；GATE B 仍为 deviation，见 §6.4） | 见 §4 |

---

## 7. 回归矩阵

---

## 8. Rollback 条件

出现以下任一情况，M1 应回滚而非绕过：

| # | 触发条件 | 理由 |
| --- | --- | --- |
| R1 | A8 语义等价失败，且根因是跨进程边界不可消除 | 违反 C8，语义 API v1 是冻结公共面 |
| R2 | 引入 health-check 以救回 §5.3，而无真实触发证据 | 直接违反 `DESIGN_SPEC.md:139` |
| R3 | 为让测试通过而放宽 memory gate 或引入 RSS 回退 | 违反 C6，是 F15 同款缺陷 |
| R4 | `trace_pixel_bg` p95 超 gate 且无法通过调优/换基解决 | 说明进程边界成本超出该工具的交互预算 |
| R5 | 迁移后需要改 Semantic API v1 签名或 JSON 形状才能完成 | 违反 C8，说明边界假设错误 |
| R6 | `unkillable()` 非空或存在无法回收的 ghost worker | 进程泄漏是比进程内泄漏更难处置的问题 |
| R7 | 任何一条 Gate A/B 需要**放宽**才能通过 | 正是本轮两次「检查抓不到自己的 bug」的教训 |

---

## 9. 本阶段（M0）明确不做

M0 已冻结，M1.0–M1.4 已按裁决执行完毕。以下 M0 的「不做」清单中，
**M0 本身仍然不做**的部分：

- ❌ 把 Gate A / Gate B 装进 `audit_boundaries.py`（属 M1 —— **已于 M1.1/M1.2 完成**）
- ❌ 重跑 N3 acceptance 以制造新结论
- ❌ 触碰 N3 封存物（14/14 哈希已于 2026-09-29 复核 MATCH）

以下**至今仍然不做**（M1 范围内亦未触碰）：

- ❌ 通用 health check（D4 拒绝作为 M1 项；§2.9:139 在无 telemetry 证据前禁止）
- ❌ telemetry 换基到 `worker_*`（D5 暂缓）
- ❌ performance gate 变更（D6 暂缓，不作为 M1 blocker）
- ❌ CLI 迁移（D7 移出范围）
- ❌ Semantic API v1 签名或 JSON 形状变更（C8）

M0 唯一产物是本文件 + §4 两道 Gate 的验证证据。

### 9.1 M1 执行中发现的、与本文件预测不符之处

| 项 | 本文件原预测 | 实际 |
| --- | --- | --- |
| `WorkerManager.query` 的 `capture` 转发 | 记为「迁移陷阱」，建议 M1 让 transport 显式转发 | 改为 `query()` 内部注入。理由：守卫本就强制存在，让每个 transport 各自记得转发是把强制约束变成约定 |
| `expectedFailure` 终态 | 记为「M1.4 移除装饰器即转硬断言」 | 移除后立即失败。`SessionManager` 类本身仍是隐患，正确终态是**正向断言该风险**（§6.7） |
| `api_ci` | 未预见 | `ci.check` 需要 session，worker 无对应 op。新增 `ci_check` **运行时 op**（不进 `_dispatch()`，故四工具面不变） |
| `configure` 时机 | 未预见 | 改为**急切建立**，使失败的 configure 可在启动时检出；这使 I2 的「失败不留半初始化对象」成为可测事实 |

---

## 10. 方法论记录：机械检查的三对照纪律

按项目纪律，新增机械检查必须先确认它对违规状态 FAIL。M0 设计 Gate B 时
**两次**未通过该验证：

1. **正则引号不匹配**：`ast.unparse` 把 `"sessions"` 规范化为 `'sessions'`，
   按源码字面量写的正则**永不匹配** → Gate B 在它本该 FAIL 的树上 PASS。
2. **不变量陈述错误**：把 Gate B 写成「计数器必须消失」，
   而正确表述是「必须存在拒绝路径」。**被负对照当场证伪**
   ——加了拒绝路径但保留计数器的正确实现被判 FAIL。

两次都由**负对照**而非正对照暴露。M1.0 修 D3 时又出现第三次，
方向相反：

3. **审计 2.2 的假阳性**：`2.2 Stable Core has no transport dependency`
   原是子串扫描 `rdebug_mcp` / `rdebug_ide`，无法区分 import 与
   **在注释里引用该文件**。于是把 D3 的修复依据写进 `worker_manager.py`
   的 docstring（`rdebug_mcp/server.py:54`、`rdebug_ide/app.py:199`）
   就让审计变红。已改为 AST 导入分析，并用 7 项对照验证。

> 一个会惩罚「把学到的东西写下来」的检查，最终一定会被绕过。

### 固化为纪律

新增或修改任何机械检查，必须同时具备三类对照并留下观测结果：

| 对照 | 目的 | 缺了会怎样 |
| --- | --- | --- |
| **正对照**：违规状态 | 必须 FAIL | 检查抓不到目标 bug |
| **负对照**：正确状态 | 必须 PASS | 检查无法被满足，会被绕过 |
| **假阳性对照**：语义相似但不违规 | 必须 PASS | 检查惩罚正确的代码/文档 |

已完成的对照验证：

| 检查 | 正对照 | 负对照 | 假阳性对照 |
| --- | --- | --- | --- |
| `2.2` transport 依赖 | 2 例真实 import → FAIL | 4 例（docstring / 注释 / 字面量 / 自包 / 相对导入）→ PASS | ✅ 7/7 |
| `2.9 GATE A` | 2 例（构造 / import） | 1 例已迁移形态 → PASS | 2 例（docstring / 注释）→ PASS |
| `2.9 GATE B` | 3 例（仅计数 / raise 非计数条件 / 无 `__init__`） | 1 例（计数+拒绝）→ PASS | — |
| `2.5` 空值冒充 | 回退 `core.py` → 报 `core.py:673 -> []` | — | 注释说明者豁免 |
| `2.6` transport 响应体 | 回退 IDE 修复 → 报 `app.py:route (RDebugError)` | — | — |
| `2.9` baseline 采集 | 回退修复 → 2 tests FAIL | — | — |

**M1.1 / M1.2 落地时必须再次执行本表。**
