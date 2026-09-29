# D4 Evidence — live-but-unhealthy 是否是一个实际 failure mode

日期：2026-09-29
授权范围：**仅证据采集**。未实现 health probe、未改 WorkerManager recovery、
未加 heartbeat / periodic probe、未以 probe 结果触发 recycle、未改 recycle
threshold、未改 D5 telemetry 基础。

## 0. 结论

```
D4-E1  live-but-unhealthy        NOT_ESTABLISHED
D4-E2  当前机制的分类             NOT_APPLICABLE（E1 未复现，无可分类对象）
D4-E3  生产发生频率 / 影响         NOT_ESTABLISHED
Decision                          DEFER（维持）
```

**没有复现出 live-but-unhealthy 条件，因此没有关闭 D4。** §2.5 记录了
一次**确实达到该描述的观测**（bad-parameter 触发的错误语义结果），但按
D4 的定义它是 **bad parameter 类别，不是不健康 runtime**——它不满足
「worker 仍存活」之外的三项判据中的「因 runtime 失效而不可信」这一条，
且**后续有效查询完全不受影响**。它作为独立缺陷登记于 §4。

---

## 1. 问题为何被收窄

M1 之前，已知的不健康条件是 F-1/F-2：**同进程多个 ReplayController**
（`Capture A ─┐  ├─ 同一进程 → 同一 replay runtime → 2 controllers`）。
M1 的 isolation boundary 使该形态不可达：

```
Capture A → Worker A      Capture B → Worker B
```

因此 D4 不再能以跨 capture contamination 作为主要证据。D4 问的是更窄的问题：

> **单个 worker 自己的 replay runtime，在存活期间能否进入一种状态，
> 使 `proc.poll()` 看不到、而后续有效查询返回的不是有效 replay 结果？**

## 2. D4-E1 — 尝试与结果

`scripts/d4_evidence_probe.py`。**只发 API 视为有效的查询**；不注入
corruption、不制造故障——因为故障注入只能证明 detection path 是否存在，
不能证明该条件值得进入生产架构（授权明文禁止据此宣布需要 health check）。

方法：交错执行两个**结果不同**的像素查询（`pixels_differ_from_each_other`
为 true，确保漂移可被观测），每次交错后重新取 A 的指纹，比较是否与首取一致。
session 层与 worker 层分别测。

| capture | 规模 / 驱动 | 交错次数 | A 漂移 | 错误 | worker 存活 | epoch | live_sessions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `w00001_frame11.rdc` | 最小 D3D11 | 50 | **0** | 0 | 是 | 1 | 1 |
| `w20000_frame11.rdc` | 最大 D3D11（20000 draws） | 40 | **0** | 0 | 是 | 1 | 1 |
| `N3-05A1.rdc` | **Vulkan 34MB，Sascha glTF/PBR** | 15 | **0** | 0 | 是 | 1 | 1 |
| `N3-02-d3d12-basic_frame120.rdc` | D3D12 3.7MB | 15 | **0** | 0 | 是 | 1 | 1 |

`N3-05A1` 是迁移前真正崩溃过的那一个（F-N3-1、F-N3-4）。它在单 worker 内
交错查询下同样零漂移。

> **判定：E1 = NOT_ESTABLISHED。** 在当前 acceptance 环境中，用有效查询
> **无法复现**出「worker 存活 + 进程可响应 + replay 结果不再语义有效」。

**未做的事**：没有为凑一个 closure 而制造「看起来像不健康」的现象。
按授权，那样做比 `NOT_ESTABLISHED` 更不准确。

## 3. D4-E2 / D4-E3

| 项 | 状态 | 理由 |
| --- | --- | --- |
| **D4-E2** | NOT_APPLICABLE | E1 未复现，没有可分类的对象 |
| **D4-E3** | NOT_ESTABLISHED | 无任何 telemetry 可支撑频率/影响判断 |

若将来真出现该条件，**当前机制会如何分类**（据 M1 后代码事实，非推测）：

| 机制 | 能否看见 |
| --- | --- |
| `proc.poll()` / `WorkerManager.alive()` | **否** —— 只看进程存活 |
| 管道写入失败 | **否** —— 进程活着则管道可写 |
| bounded retry respawn | **否** —— 只在 `WorkerError(transient=True)` 时触发 |
| recycle policy | **否** —— 只看查询数 / 存活时长 / private memory 增量 |
| 语义层 | **否** —— 无「自上次已知良好以来结果是否仍然可信」的检查 |

即：**该条件若发生，会被静默通过**，直到它自己表现为别的错误。
这与 M0 §5.3 的记录一致；§2.9:139 禁止在有 telemetry 证据之前引入通用
health-check，而 D4-E3 恰恰说明**当前没有这样的证据**。

## 4. 一次确实达到「不健康」三要素的观测 —— 但属于 bad parameter

探针附带检查时发现（`w00001_frame11.rdc`，event 0–11 的 capture）：

```
pixel_history(target, 4, 4, context_eid=999999)
  → 不抛异常
  → 返回 contextEventId = 999999，modifications = 1

trace_pixel(s, 4, 4, context_eid=999999)
  → 不抛异常
  → 返回 nodes=3, edges=2 —— 一个「看起来完全正常」的局部因果图
  → 与任何真实 event (0..11) 的结果都不匹配
  → 与有效查询结果不同

随后：有效查询结果完全正确（runtime 未被污染）
```

**这是一个真实的缺陷，且属于此前修掉的 F12 家族**（失败/错误被呈现为
看似正常的语义结果）：一个**不存在的 event id** 被静默接受，并返回一份
不匹配任何真实 event 的数据，同时不报任何错。

但按 D4 的类别判据，它**不是** live-but-unhealthy：

| 判据 | 满足？ |
| --- | --- |
| worker / 进程存活 | 是 |
| transport 可响应 | 是 |
| **因 runtime 失效**而使 replay 操作不再语义有效 | **否** —— 触发因素是调用方传入了一个无效参数；runtime 本身未失效，后续有效查询完全正确 |

因此它是 **bad parameter 校验缺口**，不是 D4 意义上的不健康 runtime。

**归属**：
- 触发路径未变更：`set_event` 自 `76e9361`（初始 scaffolding）以来未改动，
  **非本次工作引入**
- 可达性：`eid` 是 **MCP 公开参数**（`server.py:82`），因此 LLM/agent 可传入
- 严重性：一次错误的 `eid` 会产生一份**与任何真实 event 都不匹配**的
  可信外观因果图；`contextEventId` 字段会自标 `999999`，但消费者未必检查
- **本轮不修**（授权仅限证据采集）。需单独裁决：是校验并拒绝非法 event id，
  还是把 `contextEventId` 与实际回退行为显式化

## 5. 状态

```
M1 migration             COMPLETE
D6 performance evidence  MEASURED / NO BLOCKER
D6 performance gate      UNCHANGED

D4 evidence              COLLECTED -> E1/E2/E3 NOT_ESTABLISHED
D4 implementation        NOT AUTHORIZED / NOT ATTEMPTED
D4 architecture change   NOT AUTHORIZED / NOT ATTEMPTED
D5                      DEFER
D7                      OPEN
```

**D4 维持 DEFER。** 这与 §2.9 的冻结原则一致：没有 telemetry 证据就不
引入通用 health-check，而本轮恰好确认了**不存在这样的证据**。

未因本轮证据触发任何实现、架构或 threshold 变更。

## 6. 复现

```powershell
$env:PYTHONPATH = "src"
$env:RDEBUG_RENDERDOC_PATH = "<renderdoc pymodules>"
$env:RDEBUG_ISOLATION_CAPTURE_DIR = "<a directory of .rdc>"
python scripts/d4_evidence_probe.py --interleaves 50
python scripts/d4_evidence_probe.py --capture <N3-05A1.rdc> --interleaves 15
```

### 方法记录

探针最初两次写错，都属「看起来在测量什么、实际测错了」：

| 错误 | 后果 | 修正 |
| --- | --- | --- |
| `sys.path.insert(0, ...)` 置于临时目录 | 该目录的 `dis.py` 遮蔽标准库，探针无法启动 | 改由 `PYTHONPATH` 外部注入 |
| `sess.current_event_id()` | `current_event_id` 是 `@property`，加括号即 `int is not callable` | 去掉括号 |

第二次尤其值得记：**没有报「属性不存在」，而是报「int 不可调用」**——
若当时不去查 `@property`，很容易误判为生产代码缺陷。
