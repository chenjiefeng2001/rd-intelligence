# 冻结点：eid silent wrong result

冻结日期：2026-09-29
仓库：`rd-intelligence`　HEAD：`e8b363c`（本次冻结为其后新增提交）
工作项：F12 家族 — `context_eid` 事件选择语义（`DESIGN_SPEC.md` §2.10）

## 冻结结论

```
eid silent wrong result
    CONFIRMED
        ↓
Contract undefined
        ↓
Contract defined (§2.10)
        ↓
FIXED / VERIFIED
```

## 状态表（冻结值）

| 项 | 状态 |
| --- | --- |
| context_eid Contract | **DEFINED** |
| 非法 eid 静默产生 semantic result | **FIXED** |
| strict membership validation | **VERIFIED** |
| bad_request / QueryError chain | **VERIFIED** |
| runtime health | **unchanged** |
| D4 | **DEFER** |
| D6 | **measured / no regression** |
| D7 | **OPEN** |

## 证据清单（冻结时成立）

| 证据 | 载体 | 类型 |
| --- | --- | --- |
| Contract 文本 | `DESIGN_SPEC.md` §2.10 | 规范 |
| 调查与推理链 | `docs/F12-CONTEXT-EID-CONTRACT.md` | 文档 |
| 正对照（合法 draw / 合法非-draw） | `tests/integration/test_context_eid_contract.py` | **真实 capture** |
| 负对照（区间内空洞、越界 id） | 同上 | **真实 capture** |
| 恢复检查（非法后合法查询 == baseline） | 同上 | **真实 capture** |
| 假阳性对照（合法嵌套非-draw 必须被接受） | 同上 | ⚠️ **合成 action tree** |
| MCP 结构化 error + `kind="bad_request"` | 同上 | 真实 capture（经 worker 进程） |
| 分类链路修复（worker 边界压平 kind） | `src/rdebug/workers.py` 等 | 实现 |
| 机械验证闭环（8 FAIL → 16 OK → 8 FAIL） | 提交 `e8b363c` 记录 | 机械验证 |

门禁（冻结时）：unit 114 / transport 58 / integration 61 /
audit 18/18 + 1 recorded deviation / ruff clean / 冻结物 14/14 MATCH。
D6 复测：校验 ~4µs vs `SetFrameEvent` ~9ms → <0.05%，无可测量回归。

## ⚠️ 必须保留的 OPEN 注记

> **false-positive control verified by synthetic action tree;
> real capture confirmation pending.**

**不得**升级为「all real nested events verified」。

理由：本机全部 19 个 `.rdc` 的 `action_rows()` 均报告 `nested=0`
（含 20003 行的 `w20000_frame11.rdc`），**未取得任何含嵌套 action 的
真实 capture**。假阳性对照由**合成 action tree**（顶层 Dispatch 持有
嵌套 Dispatch 子节点）证明：若谓词退化为 draw-only 集合，该子节点必被误杀；
合成树证明其不会被误杀。

这与 D2 / A2 的纪律一致：**不能把合理推断升级成观测事实。**
合成树证明的是**谓词设计正确**，不是**真实 capture 上已观测**。

补齐条件：需要一个含 dispatch / indirect 等嵌套 action 的 capture
（现有 corpus 均为平坦的三角形 fixture 与 D3D11/D3D12 简单 fixture），
并在其上重跑假阳性对照。

## 本次冻结**不**授权

```
CI          NOT AUTHORIZED
D5          NOT AUTHORIZED
D7          NOT AUTHORIZED
N3-05B      NOT AUTHORIZED
F-N3-1      NOT AUTHORIZED
```

`context_eid` 项已闭环，**不再扩大范围**。

## 下一项（已开启，仅 Phase 1 调查）

**shader reflection 可归因性（`DESIGN_SPEC.md` §2.4）** —— 与本项同属
「失败/缺失被包装成合法结果」的风险族：

```
eid             :  invalid input  → fake valid result
shader reflection: missing reflection → empty-looking result
```

理由：属 core semantic correctness，优先于 CI（验证自动化不足）、
D5（observability）、D7（环境泛化）。

**仅授权 Phase 1 Contract 调查**，不授权修复；修复须先确认
`failure → empty semantic result` 路径成立，再走与本项相同的
Contract-first 流程。
