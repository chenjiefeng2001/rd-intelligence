# S2 证据记录：shader reflection 可归因性

日期：2026-09-29
授权范围：S2-A（acquire minimal capture / register provenance / verify
reflection reachability）。**未修改任何生产代码。**
未授权：修改 `core.py`、semantic schema、diff logic、error contract、测试期待值。

---

## 0. 对上一轮结论的更正（重要）

上一轮（`SHADER-REFLECTION-INVESTIGATION.md` §4）判定
「当前 corpus 上不可达，缺陷休眠」，并据此建议先获取新语料。
**该判定是错误的**，由探针缺陷导致：

1. 采样只覆盖像素 `0..9` —— 那是 640x480 目标的**角落**，仅被 event 1 的
   **clear** 写过；clear 的 `fragmentCandidate = false`，
   故 `pixel_trace.py:146` 的 `is_fragment` 为假，shader 节点被正确抑制。
2. 首轮扫描用 `except: continue` 吞掉异常，掩盖了真实原因。

真实情况：**存在 fragment candidate 的像素上，路径可达。**
更正后本项的结论方向发生了实质变化，见 §1。

---

## 1. S2.1 Reachability：**PROVEN**（真实 capture，无注入）

### 证据对象（provenance 已登记）

| 字段 | 值 |
| --- | --- |
| path | `tests/workload/corpus/w00001_frame11.rdc` |
| sha256 | `1ba59eb94d631c3737fe2efe80b769d2dbbe2f50f703f0e3254ad8f287f5d8c6` |
| size | 403973 bytes |
| API | **D3D11**（`CaptureFile.DriverName()` 实测） |
| actions | 4（eid 1 clear、eid 2、**eid 11 唯一 draw**、eid 12 Present） |
| pixel shader | 存在，`entryPoint='main'`，`debuggable=True`（eid 11 实测） |
| 资源绑定 | `ResourceId::35` 640x480 颜色目标；`ResourceId::47` 64x64（writer `CopyDst`，出现在因果图中） |
| provenance | 合成三角形 fixture（D3D11），登记于本仓库 `tests/workload/corpus`；生成器源码不在本仓库，故生成者 commit **无法登记**——如实标注为未知 |

**满足 §2.11.5**：PS 写入像素 ✅ / reflection 路径被执行 ✅ /
失败可注入或可观测 → 见 §2（本轮未获得，见下）。

### 可达性链路（真实 capture，无注入）

```
w00001_frame11.rdc  (single draw eid=11)
  → trace_pixel(320, 240, target=ResourceId::35, context_eid=11)
  → pixel_history 写入事件 = [1(clear), 11(draw)]
  → eid 11: fragmentCandidate=true, directWrite=false, PS=('main', True)
  → build_graph 生成 shader 节点
  → core.py:757-765 reflection 路径执行
```

实测输出：

```
nodes=7 edges=6
  node kind=shader  id=shader:11:ResourceId::53
       attrs={"stage":"Pixel","resource":"ResourceId::53",
              "entryPoint":"main","debuggable":true}
```

→ **路径进入、无异常、artifact 可记录。S2.1 达标。**
→ 结论：`reflection path reachable`（**不是** unreachable）

**同时修正**：`entryPoint` / `debuggable` 在真实 capture 上是
**真实的 observed fact**，不是空值。

---

## 2. S2.2 Failure observation：**NOT OBTAINED**

按裁决，不允许以 monkey-patch 生产逻辑作为最终证据。本轮尝试三条**非注入**途径：

### 2.1 真实 capture 普查（19 个 capture × 全部事件 × 6 个 stage）

| 语料 | 数量 | 结果 |
| --- | --- | --- |
| 合成 fixture（`tests/workload/corpus`） | 14 | 全部字段完整 |
| 真实应用（`N3-05A1/A2`、`N3-02-d3d12-basic`、`N3-03-alt`、`N3-03-execute-indirect`） | 5 | 全部字段完整 |

```
reflection MISSING fields : 0
EMPTY entryPoint          : 0
API failure / exception   : 0
```

> 覆盖 stage：`Vertex / Hull / Domain / Geometry / Pixel / Compute`
> （即 `_STAGE_NAMES` 全集）

**注**：上一轮的普查只覆盖了 19 个 capture 中的合成 fixture 子集
（14 合成 + 5 lru/d3d11），**真实应用 capture 从未被普查过**。
本轮已补齐，`N3-03-execute-indirect` 亦在内。

### 2.2 RenderDoc API 契约（结构性依据）

`PipeState.GetShaderReflection` 的官方 docstring：

```
GetShaderReflection(stage)
Retrieves the shader reflection information for a shader stage.
This returns ``None`` if no shader is bound.
:rtype: ShaderReflection
```

→ **只文档化了两种返回：`None`（无 shader 绑定）或 `ShaderReflection`。**
**没有任何文档化的异常/失败返回路径。**

而 `None` 这一情形**已被上游处理**：`core.py:753-755` 在
`sid == null`（无 shader 绑定）时即 `continue`，reflection 根本不会被调用。

### 2.3 结论

> **`core.py:764` 的 `except Exception: pass` 防御的是一个 API 契约未文档化、
> 且在本机 19 个 capture 的全部事件、全部 6 个 stage 上从未发生过的条件。**

按裁决的决策树（failure observable? = **no**）：

```
keep contract gap
```

| 项 | 状态（不变） |
| --- | --- |
| shader reflection Contract gap | **IDENTIFIED** |
| shader reflection runtime defect | **NOT ESTABLISHED** |

**未使用注入作为最终证据。** 上一轮的注入观测（`{"resource": ...}` 无 flag）
现降级为**说明性**，不作为缺陷成立依据。

---

## 3. S2.3 Semantic impact：**无法评估**（failure 未发生）

无 failure 即无从评估「unavailable 是否被伪装成 semantic empty」。
但**健康路径**已确证：`entryPoint` / `debuggable` 在真实 capture 上
是真实 observed fact，参与因果图 `shader` 节点并被 LLM 面向面读取。

---

## 4. 风险重估（与 eid 项的本质差异）

| | eid 缺陷 | reflection 缺陷 |
| --- | --- | --- |
| 触发条件 | **普通输入即触发**（每次非法 eid 调用） | **需 API 契约外的失败** |
| 实际观测 | 每 capture 9/13 个 id 静默出错 | **19 个 capture 零观测** |
| 风险性质 | 主动产生错误数据 | **防御性 / 潜在** |

> **这改变了优先级判断。** eid 缺陷每次调用都产出错误结果；
> reflection 的 catch 防御的是一个尚未观测到的条件。
> **不应按同一紧急度处理。**

---

## 5. 状态

```
S2-A minimal capture / provenance     DONE（复用既有 w00001，无新增语料）
S2.1 Reachability                    PROVEN
S2.2 Failure observation              NOT OBTAINED（结构性不可得）
S2.3 Semantic impact                 NOT EVALUABLE
上一轮「路径不可达」判定                CORRECTED（探针缺陷导致）
shader reflection Contract gap       IDENTIFIED（不变）
shader reflection runtime defect     NOT ESTABLISHED（不变）
§2.11 实现                            仍不授权（三项前置未满足）
```

**未做**：未修改 `core.py:764`、未新增 error flag、未改 semantic schema、
未改 diff logic、未改 error contract、未改测试期待值、未新增语料、
未重开 F12。

**下一步可选**（均需裁决）：
- **O1** 保持现状：Contract gap 已记录，行为不改，项转为 DEFER；
- **O2** 仅在 `except` 分支加注释指向 §2.11（**行为零变化**，
  防止未来读者误以为该 catch 已按 §2.11 处理）；
- **O3** 取得能真实触发 reflection 失败的 capture（当前 API 契约下
  可能不存在此类输入），再重做 S2.2。
