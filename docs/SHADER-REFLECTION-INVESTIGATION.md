# Phase 1 调查：shader reflection 可归因性

日期：2026-09-29
授权范围：**仅 Phase 1 Contract 调查 + Phase 2 分类矩阵证据**。
**未修改任何生产代码。** 依据裁决，Phase 3（Contract-first 修复）
**未触发**（见 §5）。

## 0. 规范定位更正

裁决中称 shader reflection 属 `DESIGN_SPEC.md` **§2.4**。核对后：
**§2.4 实为 Evidence Contract**（`DESIGN_SPEC.md:74`），
与 reflection 无关。全文检索 `reflect` / `shader`：

```
DESIGN_SPEC.md 中 "shader" 仅出现于：
  :53  analysis/ 目录注释
  :236 Reasoning Layer（GPU facts + code facts）
  :262 证据链示意
```

> **发现 0：shader reflection 在 DESIGN_SPEC 中没有任何 Contract。**
> 与 `context_eid` 修复前属同一类缺口（规范未定义 → 行为无约束）。

## 1. 三个 reflection 调用点的实际行为

| # | 位置 | reflection 失败时 |
| --- | --- | --- |
| 1 | `core.py:642` `debug_pixel()` | **无 try → 异常向上抛出**。另有 `debuggable` 检查（:644）与 `trace is None` 检查（:655），均抛 `QueryError` |
| 2 | `core.py:694` `debug_pixel()` 返回体 | 位于上述已验证路径之后 |
| 3 | `core.py:757-765` `pipeline()` | **`except Exception: pass` —— 静默吞掉** |

**路径 1、2 的防护是充分的。** 特别地，
`analysis/shader_trace.py:80` 的 `"debuggable": True` 看似硬编码伪造，
但 `build_shader_trace` 仅在 `session.debug_pixel()`（:162）成功后才被调用（:171），
而该调用已在 `core.py:644` 验证过 `debuggable`。
**故该字段由构造保证，不属伪造。** （此假设经查证后被推翻。）

## 2. 核心发现：路径 3 静默吞掉，且与已修复的兄弟路径不对称

```python
# core.py:757-765  —— reflection
try:
    refl = pipe.GetShaderReflection(stage)
    shader_entry["entryPoint"] = str(refl.entryPoint)
    di = getattr(refl, "debugInfo", None)
    if di is not None:
        shader_entry["debuggable"] = bool(di.debuggable)
        shader_entry["debugStatus"] = str(di.debugStatus)
except Exception:
    pass                      # ← 静默
```

而**紧邻 10 行之下**的 descriptors 路径，同类缺陷**已被修复**：

```python
# core.py:767-778  —— descriptors
except Exception as e:
    # An empty descriptor list and a failed enumeration are NOT the same
    # fact. Returning [] here used to make build_graph emit no "reads" edges,
    # which made diff-pixel compare [] against [] and report ... as "same" --
    # a fabricated verdict out of a failure to look, which DESIGN_SPEC §2.5
    # forbids. The flag lets the analysis layer map this to `unknown` instead.
    used = []
    out["descriptorsError"] = f"{type(e).__name__}: {e}"
```

`analysis/pixel_trace.py:142-143` 消费该 flag → `reads_enumerable = False` → diff 输出 `unknown`。

**reflection 路径没有对应的 `shadersError` flag。**
这不是"两种不同的设计"，而是**同一类缺陷修了一处、漏了一处**。

### 注入实证（合成，非真实 capture）

对 `w00016_frame11.rdc` 注入 `GetShaderReflection` 抛异常：

```
shader entry : {"resource": "ResourceId::53"}
*Error flag  : NONE
```

→ **reflection 查询失败产生的条目，与「该 shader 确实没有 reflection 数据」
在结构上完全不可区分。**

## 3. 分类矩阵（Phase 2）

| 情况 | 当前输出 | 是否正确 |
| --- | --- | --- |
| valid shader | `entryPoint='main'`, `debuggable=True` | ✅ **正确**（14/14 corpus capture 实测） |
| shader 无 debug info（合法缺失） | `entryPoint` 仍填；**无** `debuggable`/`debugStatus` 键 | ⚠️ **不完整**：合法缺失与查询失败不可区分，但本身不算错误事实 |
| non-debuggable shader | `pipeline()`：`debuggable=False` + `debugStatus`；`debug_pixel()`：抛 `QueryError` | ✅ **正确** |
| **reflection API failure** | `{"resource": ...}`，无 error flag，**静默** | ❌ **不正确**（与已修复的 `descriptorsError` 不对称） |
| malformed shader | **无法判定** | ❓ 语料中不存在此类样本 |

### 空值是否为合法结果？—— 是

因此 Contract 必须区分「**合法地没有**」与「**没查到**」，
这正是 `descriptorsError` 已确立的先例。`entryPoint=""` 可能是合法值，
因此**不能**简单地把空值当作错误。

## 4. 为什么 F12 型「semantic comparison accepts」**未**被确认

裁决要求确认的完整路径是：

```
failure → "" → semantic comparison accepts
```

实测结果：**后半段不成立**。

1. **diff 层不比较 reflection 字段。** `pixel_diff.py` 只比较
   `input_bindings` / `shader_input_values` / `resource_provenance`
   （:189、:201-220、:230、:268）。全仓 `entryPoint` 仅出现于
   `pixel_trace.py:155`（写入图节点）与 `shader_trace.py:77`，
   **均非比较点**。
2. **⚠️ 本条判定已被 S2 推翻（2026-09-29）。**
   原文称「当前 corpus 上不可达 / 缺陷休眠」，该结论**错误**，
   源于探针缺陷：采样只覆盖像素 `0..9`（640x480 目标的角落，
   仅被 event 1 的 **clear** 写过，而 clear 的 `fragmentCandidate=false`
   会正确抑制 shader 节点），且首轮扫描用 `except: continue` 吞掉了异常。

   **更正**：在 fragment candidate 像素上（如 `w00001_frame11.rdc` 的
   `(320,240)`，写入事件 `[1(clear), 11(draw)]`），**路径可达**，
   且 `entryPoint='main'` / `debuggable=true` 是真实 observed fact。
   证据与 provenance 见 `docs/S2-REFLECTION-EVIDENCE.md` §1。

> `entryPoint: ""` 这条**失败**路径在现有语料上仍未观测到，
> 但**不能**再表述为「代码路径不可达」——路径本身是可达的。

## 5. 结论：Phase 3 未触发

| 环节 | 状态 |
| --- | --- |
| Contract 存在？ | ❌ 无（发现 0） |
| `failure → empty-looking pipeline entry` | ✅ **已确认**（合成注入） |
| `empty entry → 语义比较接受` | ❌ **未确认**，且结构上不成立（字段不参与比较） |
| 当前 corpus 可观测？ | ❌ 不可达（`directWrite` 抑制） |

> **裁决的 Phase 3 触发条件「确认 `failure → empty semantic result`」
> 仅满足前半段。按既定纪律，不进入 Contract-first 修复流程。**

理由：若现在修复，改动的是一个**在本环境无法观测**的分支，
且无法用真实 capture 构造正/负对照——这正是 eid 项中
假阳性对照被迫降级为合成证据的同类困境。不应重复该困境。

### 建议（待裁决，本次不执行）

| 选项 | 内容 | 代价 |
| --- | --- | --- |
| **S1** | 仅补 §2.x reflection Contract 文本（明确「合法缺失 vs 查询失败」必须可区分，`pipeline()` 须有 `shadersError` 类 flag），**不改行为** | 文档成本，无行为风险；但 spec 会先于实现 |
| **S2** | 取得含 **PS 写入像素**的 capture（使 `directWrite=False`），重做 Phase 2 取得真实证据后再裁决 | 需新语料；证据等级最高 |
| **S3** | 直接按 descriptors 先例补 `shadersError` flag + `unknown` 映射 | 立即收口，但**无真实 capture 证据**，属"按推断修复" |

**建议顺序：S2 → S1 →（证据成立后再）修复。**
在取得真实 capture 前，不做行为改动。

## 6. 状态

```
shader reflection §2.4 investigation   PHASE 1 + 2 COMPLETE
                                       PHASE 3 NOT TRIGGERED
                                       真实 capture 证据 PENDING
CI / D5 / D7 / N3-05B / F-N3-1          NOT AUTHORIZED
context_eid                             FROZEN（FIXED / VERIFIED）
```

**未做**：未修改生产代码；未补 Contract 文本；未改错误分类；
未新增 flag；未新增语料。
