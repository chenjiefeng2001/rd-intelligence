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

## 6. 需要裁决的开放项（M1 前必须定）

| # | 问题 | 候选 | 影响 |
| --- | --- | --- | --- |
| **D1** | A1 如何在运行时断言「请求进入 worker path」？ | (a) worker 侧返回 pid 供 transport 上报；(b) transport 侧断言本地无 `CaptureSession` 实例 | 无内省点则 A1 不可测 |
| **D2** | A2 需要 worker 暴露其 `_REPLAY_LIFECYCLE` 状态 | 在 `workers.py` 增加只读 `lifecycle` op | 无则 A2 只能靠间接推断 |
| **D3** | **`WorkerError` 是否继承 `RDebugError`？** | (a) 改为继承 → 现有 handler 无需改动，风险最低；(b) 保持 `RuntimeError` + 在 transport 显式捕获 | **最高风险项。** 决定 A5/A7 能否成立 |
| **D4** | health probe 能力回退如何处置？ | (a) 接受回退（记入已知限制）；(b) worker 增加周期性 value probe（**注意 §2.9:134 禁止在遥测出现真实触发证据前引入通用 health-check**）；(c) 用 recycle policy 覆盖 | (b) 与 §2.9 冲突，除非有新证据 |
| **D5** | telemetry 是重新发出 `session_*` 还是换基到 `worker_*`？ | (a) 兼容层继续发 `session_*`；(b) 换基 + 修订 `REAL_WORLD_VALIDATION.md` 的指标类 1/4 | 影响 §5.5 两类指标的证据链 |
| **D6** | perf gate 在 worker 路径上还是进程内 harness 上？ | 建议：两个都留，worker 路径单设一组阈值 | 影响 §5.6-8 |
| **D7** | CLI 是否也在范围内？ | 本文件按 M0 实测定为**不在范围内** | 若纳入，工作量显著增加 |

---

## 7. 回归矩阵

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
| `audit_boundaries.py` | 17/17 + 1 deviation | **17/17 + 0 deviation**，且 DEVIATION 转硬检查 | 见 §4 |

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

- ❌ 修改任何生产代码（`src/**`）
- ❌ 修改 `WorkerManager`
- ❌ 删除 `SessionManager`
- ❌ 修改 Semantic API v1 或任何 Contract
- ❌ 把 Gate A / Gate B 装进 `audit_boundaries.py`（属 M1）
- ❌ 重跑 N3 acceptance 以制造新结论
- ❌ 触碰 N3 封存物（14/14 哈希已于 2026-09-29 复核 MATCH）

M0 唯一产物是本文件 + §4 两道 Gate 的验证证据。

---

## 10. 方法论记录：本次 Gate 设计中「抓不到自己 bug」的两次实例

按项目纪律，新增机械检查必须先确认它对违规状态 FAIL。M0 设计 Gate B 时
**两次**未通过该验证：

1. **正则引号不匹配**：`ast.unparse` 把 `"sessions"` 规范化为 `'sessions'`，
   按源码字面量写的正则**永不匹配** → Gate B 在它本该 FAIL 的树上 PASS。
2. **不变量陈述错误**：把 Gate B 写成「计数器必须消失」，
   而正确表述是「必须存在拒绝路径」。**被负对照当场证伪**
   ——加了拒绝路径但保留计数器的正确实现被判 FAIL。

两次都由「负对照」而非「正对照」暴露。结论已固化为项目纪律：

> 新增机械检查必须同时具备：正对照（违规→FAIL）、负对照（正确→PASS）、
> 假阳性对照（无关提及→PASS）。缺任一不予接受。
