# 冻结点：shader reflection 可归因性

冻结日期：2026-09-29
仓库：`rd-intelligence`
工作项：shader reflection 可归因性（`DESIGN_SPEC.md` §2.11）
裁决：**O2**（仅在 `core.py` 的 reflection catch 增加指向 §2.11 的注释）

## 冻结结论

> **Contract 已定义，但当前没有观测到违反该 Contract 的真实 failure；
> `core.py` 的 reflection catch 是未被证实需要承担该语义的防御性 catch。**

## 状态表（冻结值）

| 项 | 状态 |
| --- | --- |
| `context_eid` | **FIXED / VERIFIED** |
| shader reflection Contract | **DEFINED** |
| shader reflection runtime defect | **NOT ESTABLISHED** |
| reflection catch | **DEFERRED / defensive path** |
| D4 | **DEFER** |
| D6 | **MEASURED / NO REGRESSION** |
| D7 | **OPEN** |
| CI | **OPEN** |
| N3-05B | **NOT AUTHORIZED** |
| F-N3-1 | **NOT AUTHORIZED** |

## O2 的确切边界（已执行并核验）

**唯一改动**：`core.py` 的 reflection `except Exception:` 分支前增加注释。

**零行为变更的证明**：

```
剥离注释与空行后逐行比对 HEAD：
  code-only lines: HEAD=685  now=685
  IDENTICAL
原始 diff：35 行纯新增，0 删除
ruff: All checks passed
```

注释明确记录五点：

1. 当前 catch 是**防御性**行为；
2. **尚未观测到** reflection failure；
3. **不应**把 catch 后的空值解释为「reflection 成功但无输入」
   （那是把 unavailable 当作 observed fact，违反 §2.5 / §2.11）；
4. 若未来出现真实 failure，**应重新执行 §2.11 的 evidence / consumer-impact 验证**；
5. **本次不改变行为、不改变 schema、不改变 error propagation**。

注释**未**声称「此处已正确处理 reflection failure」—— 恰恰相反，
它明确写出当前**没有**该证据。

## 支撑证据

| 事实 | 载体 |
| --- | --- |
| 路径**可达**：真实 capture 上产生真实 shader 节点 | `docs/S2-REFLECTION-EVIDENCE.md` §1 |
| 19 capture × 全事件 × 6 stages **零失败** | 同上 §2.1 |
| API 契约**无失败返回**（只文档化 `None` / `ShaderReflection`） | 同上 §2.2 |
| `None` 情形已被 `sid == null` 提前处理 | `core.py`（catch 之上） |
| consumer impact **未进入可验证状态** | 同上 §3 |

## ⚠️ 调查方法学记录（保留）

> **第一轮的「路径不可达」不是系统事实，而是观测缺陷。**

成因是两项叠加：

1. **probe sampling 缺陷** —— 只采样像素 `0..9`；在 640x480 目标上
   那是**角落**，仅被 event 1 的 **clear** 写过，而 clear 的
   `fragmentCandidate = false` 会**正确**抑制 shader 节点；
2. **exception swallowing 缺陷** —— 首轮扫描用 `except: continue`
   吞掉异常，使真实原因不可见。

更正依据是真实 capture 的路径证据：
`w00001_frame11.rdc`（D3D11，单 draw）上
`trace_pixel(320,240)` 产生 `entryPoint='main'` / `debuggable=true`
的真实 shader 节点。

**教训（可复用于后续调查）**：
可达性判断必须**穷举可区分的输入类别**，而非采样少数代表点；
且**不得**在探测脚本中静默吞掉异常——两者都会把
「探针没看到」误报成「系统里没有」。

## 已知限制（如实记录）

- 该注释**无测试固定**，注释可能随时间腐化。
  若未来重开本项，建议补一条回归测试钉住
  「`w00001_frame11.rdc` 的 `(320,240)` 路径产生
  `entryPoint='main'`」这一可达性事实。
  **本次未新增测试**（超出 O2 授权边界）。
- 注入观测（`{"resource": ...}` 无 flag）**已降级为说明性**，
  不作为缺陷成立的依据。

## 本次冻结**不**授权

```
修改 core.py 行为 / 新增 error flag      NOT AUTHORIZED
修改 semantic schema / diff logic        NOT AUTHORIZED
修改 error contract / 测试期待值          NOT AUTHORIZED
新增语料                                  NOT AUTHORIZED
O3（构造失败条件以证明该 catch）            NOT AUTHORIZED
CI / D5 / D7 / N3-05B / F-N3-1           NOT AUTHORIZED
```

## 重开条件（已由 §2.11 提供）

若未来**真的**观测到 reflection failure，
`DESIGN_SPEC.md` §2.11.4 的三项前置即成为重开 Phase 2/3 的触发条件：

```
1. 真实 capture 使路径可达                —— 已满足（S2.1）
2. 在该 capture 上复现 reflection 失败      —— 届时为触发点
3. 证明某 semantic consumer 的响应         —— 届时为触发点
```

**O2 后不追 O3。** 当前继续追只会增加实验面，
而不会提高现有结论的可信度。
