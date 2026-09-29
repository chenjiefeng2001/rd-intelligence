# F12-family：`context_eid` Contract 调查

日期：2026-09-29
授权范围：**仅 Contract / 证据调查**。未修改任何生产代码。
优先级：**高于 shader reflection 与 CI**（本项已有实证证明能把错误数据
伪装成成功结果，且正落在 F12 家族）。

## 0. 裁决（2026-09-29）

> **采用 A：`context_eid` 严格成员判定。**
> **不采用 B（显式回退语义），也不采用「双字段回退语义」。**

选择依据**不是偏好，而是当前证据边界已把 B 排除**：

| 依据 | 出处 |
| --- | --- |
| `context_eid` 无 Contract，必须先定义再实现 | §1 |
| RenderDoc 无可验证的「实际生效 event」读回 → 任何 fallback 后的「实际 context」字段都是**不可证实的断言** | §5 |
| event ID 非连续区间 → 区间检查**可证伪为错误** | §4 |
| `action_rows()` / `flatten_actions()` 提供完整 action tree 的成员集合 | §4 |
| 内部调用方全部传入真实 event ID → 严格判定不破坏内部路径 | §6 |
| **合法嵌套非-draw event 必须被接受**，不得退化为 draw-only 集合 | §4、§9 |

裁决同时冻结的规则已写入规范正文：
`DESIGN_SPEC.md` **§2.10 `context_eid` 事件选择语义**。

### ⚠️ 环境缺口（影响假阳性对照的证据等级）

假阳性对照要求**合法嵌套非-draw event 必须被接受**。实测：

```
本机全部 19 个 .rdc（corpus 14 + validation 5）→ nested = 0
无任何 capture 含嵌套 action（含 20003 行的 w20000）
```

因此**该对照无法在真实 capture 上验证**。处理方式：

- **谓词层**：以**合成 action tree**（含嵌套非-draw 子 action）验证
  ——这能精确证明谓词是「flattened tree 成员判定」而非 draw-only。
- **真实 capture 层**：由正/负对照 + 恢复检查覆盖集成路径。
- **诚实标注**：假阳性对照的证据等级为**合成树证明**，**非真实 capture 证明**。
  需要含 dispatch/indirect 的 capture 才能补齐；不得以合成结果冒充真实证据。

---

## 1. 规范说了什么：什么都没有

`DESIGN_SPEC.md` 全文**从未出现 `context_eid`**。其中仅有的两处 `eventId`
属于**另一件事**——证据回链：

| 位置 | 内容 | 是否与本项相关 |
| --- | --- | --- |
| `DESIGN_SPEC.md:42` | 每条结论边/层状态可回链 `eventId` | **否**：讲的是输出证据的出处，不是输入事件的选取 |
| `DESIGN_SPEC.md:79` | Evidence 结构含 `eventId` | **否**：同上 |

`docs/` 下所有验证报告同样没有任何关于事件选取的约定（唯一命中是本轮
自己写的 `D4-EVIDENCE.md`）。

**结论：既无「必须是合法 event id」的定义，也无「允许回退」的声明。
当前的隐式行为是第三种状态——「非法 eid → 正常形状的错误因果图」，
这正是裁决中明令不得维持的。**

## 2. 调用方预期：不存在

| 表面 | 现状 |
| --- | --- |
| MCP `trace_pixel` / `trace_resource` / `debug_pixel` | 签名含 `eid: Optional[int] = None`，**三处 docstring 均未说明其含义或取值范围** |
| CLI `pixel-history` / `debug-pixel` | `help="context event id (default: last event in frame)"` —— 只说明**缺省**行为，未说明**合法性** |
| CLI `trace-pixel` / `trace-resource` | `--eid` 无 help 文本 |
| IDE | 不暴露 `eid` |

**没有任何调用方能被告知「什么算合法 eid」** —— 包括 LLM/agent。
这把「一个看似合理的 event id」变成了纯粹的猜测。

## 3. 代码实际做了什么：记录意图，而非事实

```
core.py:358-361   def set_event(self, event_id):
                       eid = int(event_id)
                       self._ctrl.SetFrameEvent(eid, True)   ← 无返回值检查、无范围校验
                       self._current_eid = eid              ← 记录「请求值」

core.py:560-562   if context_eid is None:
                       context_eid = self.last_event_id()   ← 仅对「缺省」有定义
                   self.set_event(context_eid)

core.py:574       "contextEventId": int(context_eid)      ← 同样记录「请求值」
```

因此 payload 中的 `contextEventId` 是**意图的记录**，不是**事实的读数**。
这就是为什么先前观测到的非法 eid 结果会自标 `999999`：
它如实报告了「你要求了什么」，却完全不说明「实际得到了什么」。

## 4. 缺陷范围比「越界 eid」严重得多

先前只用 `999999` 观测，结论偏轻。进一步穷举一个小 capture
（`w00001_frame11.rdc`）的**全部** event id：

```
合法 event 集合 (action_rows) : [1, 2, 11, 12]
draw events                  : [11]
last_event_id()              : 12

对 0..12 中每一个「不在合法集合」的 id 逐个实测：
  eid = 0, 3, 4, 5, 6, 7, 8, 9, 10   →  全部不抛异常，全部返回数据，
                                          且与任何真实 event 的数据都不匹配
```

**即 13 个「看起来合法」的 id 里有 9 个会静默产出不存在的数据。**

这带来一条**可证伪的推论，直接排除「范围检查」这种实现**：

> event id **不是连续区间**。即使在简单 capture 中也不连续
> （`w20000_frame11.rdc`：20003 rows / 20003 unique eids，`contiguous=False`）。
> 因此 `0 <= eid <= last_event_id()` 会**错误接受** 9/13 个不存在的 id，
> 并继续产出垃圾。**有效性谓词必须是集合成员判定，不能是范围判定。**

好消息：成员判定是**良定义且现成可得的**——
`action_rows()` 使用 `flatten_actions()`，后者用栈**递归进入 `action.children`**，
因此嵌套 action 的 event id 也在集合内。不会误伤合法的嵌套事件。

## 5. A 与 B 的关键分歧点（决定性证据）

| | A：严格语义 | B：明确的回退语义 |
| --- | --- | --- |
| 需要运行时支持 | 只需**校验**请求值 | 需要**读回**实际生效的事件 |
| RenderDoc 是否支持 | ✅ 支持 | ❌ **不支持** |

**决定性事实**：`ReplayController` 暴露的事件相关成员只有
`GetFrameInfo` 与 `SetFrameEvent`：

- **没有 current-event 读回**（无 `GetCurrentEvent` / `CurrentEvent` 之类）；
- `GetFrameInfo()` 返回的是 **capture 级别的 `FrameDescription`**
  （docstring：*"Retrieve the information about the frame contained in
  the capture"*），**不是当前所处事件**。

因此：

> **B 无法被诚实实现。** 若允许越界 eid 并回退到某个 context，
> 系统**无法观测** RenderDoc 实际做了什么，因此只能输出一个
> 「我们请求过的」标签去冒充「实际生效的」标签——那恰恰是当前缺陷
> 的同一形态，只是换了包装。**任何回退标签都是无法验证的断言。**

> **A 可以被诚实实现。** 在调用 `SetFrameEvent` 之前，
> 用 `action_rows()` 的 event 集合做成员判定即可。

**证据倾向 A。但修法不在本文件决定。**

## 6. 现有测试没有为当前行为背书

| 检查 | 结果 |
| --- | --- |
| 任何测试传入不存在的 `context_eid`？ | **无**。全部使用 `context_eid=None` |
| 唯一的字面量 `eid=11` | 走 `FakeSession.pipeline()`，**对任何 eid 都返回同一个 PIPELINE**（`test_transport.py:77-78`），因此**未固定任何真实校验行为** |
| 内部调用方是否只用真实 id？ | 是：`ci.py:45`、`pixel_diff.py:313`、`shader_trace.py:116` 均用 `last_draw_event_id()` |

即：**没有既有期望需要保留**，也**没有内部路径会被严格校验打断**。
这降低了 A 的风险，但不构成选择 A 的理由。

## 7. 与已冻结验收条件的对应

裁决冻结的 7 条，无论最终选 A 还是 B 都应满足。逐条核对 A 是否覆盖：

| # | 条件 | A 是否满足 | 备注 |
| --- | --- | --- | --- |
| 1 | 合法 eid 现有结果不变 | ✅ | 合法 id 走同一条路径，仅增加一次成员判定 |
| 2 | 越界 eid 不得产生「看似正常」的错误图 | ✅ | 直接命中；且比「越界」更强——**所有**不存在的 id |
| 3 | 调用方能区分 valid / invalid parameter / genuine failure | ⚠️ **需配套** | 见 §8 |
| 4 | 非法 eid 后合法查询仍与 baseline 一致 | ✅ | 已实测：runtime 未被污染；但**不可依赖**，应作为回归断言 |
| 5 | 不得当成 worker death / unhealthy | ✅ | 参数错误与 `WorkerError` 已是不同类型（§8） |
| 6 | regression 覆盖真实 capture | ✅ | 需真实 capture，不能只用 FakeSession |
| 7 | 三对照（正/负/假阳性） | ✅ | 见 §9 的对照设计 |

**条件 3 是 A 单独无法满足的**——它需要错误分类配合，见下。

## 8. 错误分类的接线点（实现阶段才会动，本文件不改）

裁决要求分类为：

```
invalid eid → bad parameter → JSON error body → no semantic result
```

且**不得**被包装成 runtime failure（会污染 M1 刚保护下来的 recovery 遥测）。

现有机制已经能承载它，本文件仅记录**位置**，不实施：

| 层 | 现状 | 与本项的关系 |
| --- | --- | --- |
| 错误类型 | `RDebugError` 之下的 `QueryError` | 已有；非法 eid 应归入**参数**类而非查询失败类 |
| MCP `_safe` | `except RDebugError` → `{"error": ..., "tool": ...}` | 已有，会自动转成 error body |
| IDE `route()` | `except RDebugError` → 400 + body | 已有 |
| telemetry | `query_error`（无 `kind`）vs `kind="bad_request"` | **已存在该区分**（`app.py:209-210`），且有测试钉住（`test_ide_app.py`）。参数错误须走带 `kind` 的那条 |

即：**分类基础设施已具备**，缺的是「非法 eid 被识别出来」这一步。

## 9. 三对照设计（实现阶段执行时必须跑）

| 对照 | 期望 | 说明 |
| --- | --- | --- |
| 正对照 | 合法 id → 结果不变 | 条件 1 |
| 负对照 | 不存在的 id（含 `0`、中间空洞、`999999`）→ 参数错误、无 semantic payload | 条件 2/3 |
| **假阳性对照** | **嵌套/非 draw 的合法 id 必须仍然被接受** | **这是最关键的一条**：`flatten_actions` 递归进入 children，若谓词只用 draw 集合就会误杀合法嵌套事件 |

## 10. 状态

```
D4                         NOT_ESTABLISHED / DEFER
D6                         MEASURED / NO BLOCKER
eid silent wrong result    CONTRACT DEFINED（裁决 A）/ FIX NOT YET APPLIED
                           ⚠️ 尚**未**推进到 FIXED / VERIFIED——
                           该状态须待实现 + 三对照 + 恢复检查全部成立后才可写入
                           （Contract 文本见 DESIGN_SPEC §2.10；
                             假阳性对照的环境缺口见 §0）
shader reflection         OPEN
CI                         OPEN
D5                         DEFER
D7                         OPEN
N3-05B / F-N3-1            NOT AUTHORIZED
```

**本文件记录的调查阶段未修改任何生产代码。**
实现阶段严格按裁决顺序执行：Contract 文本 → 缺陷回退/三对照机械验证
→ 实现 → MCP/IDE 错误契约钉住。
