# CURRENT EVIDENCE FREEZE

冻结日期：2026-09-29
冻结点 commit：`ed59113`（57 commits）
覆盖仓库：`rd-intelligence`（`rdebug-validation` 冻结物只读未触碰）

```text
CURRENT EVIDENCE FREEZE
──────────────────────────────────────────────
context_eid             FIXED / VERIFIED
CI gate verdict (§4.1)   DEFINED / FROZEN
  zero-check pass       FIXED / VERIFIED
  regression detection  VERIFIED
  ignore_capture_hash   VERIFIED
  passedChecks          VERIFIED
CI configuration        NOT AUTHORIZED
shader reflection       CONTRACT DEFINED
reflection runtime      NOT ESTABLISHED
reflection catch        DEFERRED / defensive
D6                      MEASURED / NO REGRESSION
D4                      DEFER
D7                      OPEN
N3-05B                  NOT AUTHORIZED
F-N3-1                  NOT AUTHORIZED
──────────────────────────────────────────────
```

## Checkpoint 事实（冻结时实测）

| 项 | 值 |
| --- | --- |
| commits | 57（冻结点） |
| 工作树 | clean |
| 冻结物 | `rdebug-validation` **14/14 MATCH（INTACT）** |
| unit | 130 OK |
| transport | 58 OK |
| integration | 63 OK |
| audit | 18/18 + 1 recorded deviation |
| ruff | clean |

## 三条已闭环的项

**`context_eid`** —— 完整 correctness 闭环：

```
CONFIRMED → Contract undefined → Contract defined (§2.10) → FIXED / VERIFIED
```

含机械验证闭环（缺陷存在 8 FAIL → 修复后 16 OK → 仅回退 `core.py` 再现 8 FAIL）。
⚠️ 保留 OPEN 注记：**false-positive control verified by synthetic action tree;
real capture confirmation pending** —— 不得升级措辞。

**CI gate 裁决（§4.1）** —— Contract + implementation 闭环：
机械验证闭环（6 FAIL → 16 OK → 仅回退 `ci.py` 6 FAIL → 16 OK），
真实 capture 矩阵、假阳性对照、边界对照全部成立。
⚠️ 边界：**证明的是裁决逻辑满足 Contract，不是证明 CI 已成为放行门禁。**
详见 `docs/FREEZE-CI-2026-09-29.md`。

**shader reflection** —— Contract 已定义，边界已调查，
**未被证实为 runtime defect**。O2 经 **code-only identical** 机械验证
（剥离注释后 685 行逐行比对 IDENTICAL，diff 35 行纯新增 0 删除），
避免了「注释落错位置却以为完成」。

## 🔁 Reopen trigger（保留）

> **未来一旦获得真实 reflection failure，立即重开 §2.11；
> 不需要因为「catch 看起来可疑」提前修改。**

`DESIGN_SPEC.md` §2.11.4 已载明三项重开条件：

```
1. 真实 capture 使路径可达        —— 已满足（S2.1）
2. 在该 capture 上复现失败         —— 届时为触发点
3. 证明 consumer 响应              —— 届时为触发点
```

## 保持生效的 scope decision（为何现在不开启）

| 项 | 不开启的理由 |
| --- | --- |
| **CI configuration** | §4.1 裁决 Contract 已闭环，但**接线是新的工程边界**，须先答 6 个问题（放行/开发者检查之分、是否具备真实 replay runtime、`unknown` 的最终处理、5 个门的最小执行证据、baseline 进入方式、**能否区分 regression / unknown / infrastructure failure**）。**详见 `docs/FREEZE-CI-2026-09-29.md`** |
| **F-N3-1** | 虽为 `REPRODUCED / NOT_EXPLAINED`，但 ExecuteIndirect 已被正式降为 extra coverage sample 并移出 frozen acceptance scope。**重开将直接突破现有 scope decision。** |
| **N3-05B** | N3-05A 已完成 frozen acceptance；05B 属 renderer/generalization 扩展，**不是当前 correctness blocker**。 |
| **D7 / D5** | 均属「增加证据能力」，当前**没有新的 correctness defect 在等待**。D7 另受实际硬件矩阵限制，单机无法推导 cross-machine claim。 |

## 下一次开启工作时

**单独选择一个 workstream，并从它自己的 Contract / evidence question 开始**，
而不是自动从 OPEN 状态表中挑一个继续。

若选择 CI，则起点是 `docs/FREEZE-CI-2026-09-29.md` 中预先识别的
**6 个 CI integration Contract 问题**，而不是直接写 pipeline 配置。

## 本冻结**不**授权

```
CI 接线 / 放行门禁配置                     NOT AUTHORIZED
修改 reflection catch 行为 / 新增 error flag   NOT AUTHORIZED
修改 semantic schema / diff logic / error contract  NOT AUTHORIZED
新增语料                                       NOT AUTHORIZED
O3（构造失败条件以证明该 catch）               NOT AUTHORIZED
重开 F-N3-1                                    NOT AUTHORIZED（突破 scope decision）
N3-05B / D5 / D7                              NOT AUTHORIZED
```
