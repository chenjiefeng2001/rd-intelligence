# M1.5 Acceptance Report — SessionManager → WorkerManager 迁移

日期：2026-09-29
基线：`rd-intelligence @ 2a1f1e8`
范围：D7 界定的 **MCP + IDE**；CLI 明确移出
证据：`tests/integration/test_m15_acceptance.py`（19 tests，真实 RenderDoc）、
`tests/integration/test_ide_ci_workflow.py`（4 tests）、
`scripts/audit_boundaries.py`（18/18 + 1 deviation）

---

## 1. 结论

> **Process isolation is proven:** each capture is serviced by a distinct
> worker process; the transport process owns zero live ReplayControllers;
> each worker performs one replay initialization.

> **Runtime-level identity is unobservable through the current RenderDoc
> API.** Independent runtime per process is therefore an architectural
> consequence/assumption of process isolation, not a directly observed
> identity result.

§2.9 的本次 migration 判定为 **COMPLETE**（冻结验收范围内），依据见 §4。

---

## 2. 措辞边界（不得升级）

**可以写：**
> Process isolation is proven: each capture is serviced by a distinct worker
> process; the transport process owns zero live ReplayControllers; each
> worker performs one replay initialization.

**不可以写：**
> 两个 capture 使用两个**可观测的**独立 replay runtime。

**可以写：**
> Runtime-level identity is unobservable through the current RenderDoc API.
> Independent runtime per process is therefore an architectural
> consequence/assumption of process isolation, not a directly observed
> identity result.

**依据（M0 已实测，本轮 M1.5 复验）**：

| 检查 | 结果 |
| --- | --- |
| `renderdoc` 模块有 `ObjectIdentity` / `ObjectId` | **无** |
| `ReplayController` 有 identity 类成员 | **无** |
| `InitialiseReplay()` 返回可辨识句柄 | **无** |

因此 `identity` / `controller.identity` 一律为 `unobservable` + 理由。
`opaque_local_token` 是**进程内 Python 侧 token**，**不是** RenderDoc 级身份，
**跨进程不可比** —— 两个不同的 `id()` 不是身份断言。

`test_row_d2_runtime_identity_is_unobservable` 把这条边界**写成断言**：
M1.5 若有人把 A1 的结论升级成 A2，该测试必须失败。

---

## 3. Acceptance Matrix 结果

| 层 | MCP | IDE | 必须证明 | 结果 |
| --- | --- | --- | --- | --- |
| 路径 | WorkerManager | WorkerManager | 不再进入 SessionManager | **PASS** |
| capture isolation | A/B → 不同 PID | 重配置 → 不同 PID 且旧 owner 已释放 | A1 | **PASS** |
| controller | transport 进程 `live_controllers == 0` | 同左 | 无 transport-local controller | **PASS** |
| init lifecycle | 每 worker `initialise_epoch == 1` | 同左 | 单 worker 单初始化 | **PASS** |
| ownership | worker PID ↔ capture 绑定 | configure/reconfigure/dispose 后 PID 对应 | 无 ghost | **PASS** |
| failure semantics | JSON body + `query_error` | JSON body + `query_error` | D3 闭环 | **PASS** |
| bad input | error payload | HTTP 400 + JSON body | 不丢连接 | **PASS** |
| worker death | bounded respawn + verify | bounded respawn + verify | §2.9 recovery | **PASS** |
| shutdown | registry/state 清理 + pid 消亡 | 同左 | 无残留 | **PASS** |
| D2 | **UNOBSERVABLE** | **UNOBSERVABLE** | 不推断 runtime identity | **PASS** |

**关于 IDE 的 capture isolation** —— IDE 同一时刻只拥有一个 capture（设计如此），
因此该行的准确含义是：**连续 owner 获得不同进程，且前一个被释放**，
而非「两个 capture 同时存活」（那是被设计禁止的）。测试
`test_row_capture_isolation_ide_distinct_pids` 同时断言了
`pid(A) != pid(B)` **且** `pid(A)` 进程已消亡。

**关于 `ci_check` 的验证**（M1.4 补充的 runtime op）—— 只验证三件事，未扩大
API compatibility 范围：

1. IDE 实际 workflow 可完成所需 CI 操作：真实 baseline 经 `/api/ci` 跨进程
   边界消费成功，返回 `status` / `failures`
2. 仍经 WorkerManager：`identity()` 显示 worker 的 `live_sessions == 1`
   而 IDE 进程为 `0`
3. 未重新引入 transport-local replay state：同上

附带验证 **篡改 `captureSha256` 的 baseline 会报 `regression` 而非 `pass`**
——CI 门禁确实能失败（F12 正是把错误结果送进 CI baseline 的缺陷家族）。

---

## 4. Negative Controls

| # | 场景 | 期望 | 实测 |
| --- | --- | --- | --- |
| **N1** | 故意在 transport 重新引入 `import rdebug.session_cache` | Gate A 直接拒绝 | 审计退出码 ≠ 0，输出含 `GATE A` + `session_cache`；恢复后重新转绿 |
| **N2** | 故意让两个 capture 共享一个 worker | 违反 A1/ownership invariant，**而非只产生一个「不同结果」** | in-worker bound-capture 守卫拒绝，报 `worker bound to`；且 `pid(b)` 为 `None` —— 注册表与现实已背离，即 ghost 形态 |
| **N3** | worker failure | `WorkerError` → transport JSON body → `query_error`，且**不得**被分类为 `bad_request` | MCP 与 IDE 均返回 body；`query_error` 两端可观测；IDE 侧无 `kind=bad_request` |

N2 另经二次反向验证：**禁用 worker 的 bound-capture 守卫后 N2 立即 FAIL** ——
证明该守卫是真实防线，而非恰好通过的装饰。

---

## 5. 迁移完成门槛

| 条件 | 状态 |
| --- | --- |
| Gate A | **PASS / hard** |
| MCP A1 | **PASS** |
| IDE A1 | **PASS** |
| MCP failure semantics | **PASS** |
| IDE failure semantics | **PASS** |
| MCP recovery | **PASS** |
| IDE recovery | **PASS** |
| MCP shutdown/reuse | **PASS** |
| IDE configure/dispose | **PASS** |
| negative controls | **PASS** |
| D2 runtime identity | **UNOBSERVABLE，已显式记录** |
| D4 / D5 / D6 / D7 | **unchanged / deferred** |

**Gate B 保持 DEVIATION。** 它是「代码中存在通用第二 controller 拒绝机制」的
proxy；本次迁移的实际安全性质已由 **process isolation + transport-local
controller count + worker lifecycle evidence** 验证。把 Gate B 改为硬失败会
要求 `CaptureSession.__init__` 拒绝第二个 controller，而 worker 进程内的
合法路径恰恰是「先建 session 再复用」——那会把正确状态判为违规。
**未为了审计数字变绿而改变其语义。**

---

## 6. 已知能力边界（非本次范围）

| 项 | 状态 | 依据 |
| --- | --- | --- |
| health probe / `unhealthy` 检测 | **无实现**（D4 defer） | `WorkerManager` 只检测进程存活；§2.9:139 在无 telemetry 证据前禁止通用 health-check |
| telemetry 事件基线 | **未换基**（D5 defer） | 仍发 `session_*`；`query_error` 已在两端可观测 |
| performance gate | **未变更**（D6 defer） | 未作为 M1.5 门槛；本次也未收集迁移引入的性能回归证据 |
| CLI | **移出范围**（D7） | 每次调用单 capture/进程，本无隔离问题 |
| 跨机器确定性（D7/N1） | **OPEN** | Machine B/C `unavailable`；本次迁移不产生跨机器证据 |

---

## 7. 本轮修正的两处自身设计错误

按项目的证据纪律，执行中与计划不符之处如实记录：

| 项 | 原设计 | 实际 | 原因 |
| --- | --- | --- | --- |
| `ci_check` 的注册位置 | 作为 **op** 注册，「不进 `_dispatch()` 以免扩大四工具面」 | 改为 `_dispatch()` 的第五项 | 我混淆了「worker 内部路由」与「transport 公开工具面」。前者不是 Contract；后者才是，且由 `test_exactly_four_tools` 强制（MCP 工具面**仍为四个**）。作为 op 会迫使 IDE 走 `query()` 并报 `unknown tool` |
| `_ci_check` 签名 | `(session, baseline)` | `(session, **a)` | 拒绝转发 `capture` 转发导致 `unexpected keyword argument 'capture'`；其余四项本就以 `**a` 读取所需键 |

另记录一处**测试自身的错误**（非生产代码）：篡改 baseline 时我先用了不存在的键
`captureHash`，使「CI 门禁能否失败」这一断言**假通过**。改用真实的
`captureSha256` 后才确认该门禁确实会报 `regression`。
**一个用错键的断言比没有断言更危险** —— 它看起来在验证什么。

---

## 8. 复现方式

```powershell
$env:PYTHONPATH = "src"
$env:RDEBUG_RENDERDOC_PATH = "<renderdoc pymodules>"
$env:RDEBUG_INTEGRATION_CAPTURE = "<a .rdc>"
$env:RDEBUG_ISOLATION_CAPTURE_DIR = "<a directory of .rdc>"

python -m unittest discover -s tests/integration -t .
python scripts/audit_boundaries.py
python -m ruff check .
```

实测：integration 45/45、audit 18/18 + 1 deviation、ruff 全绿。
