# CURRENT EVIDENCE FREEZE

冻结日期：2026-09-29
冻结点 commit：`28058a9`（54 commits）
覆盖仓库：`rd-intelligence`（`rdebug-validation` 冻结物只读未触碰）

```text
CURRENT EVIDENCE FREEZE
──────────────────────────────────────────────
context_eid             FIXED / VERIFIED
shader reflection       CONTRACT DEFINED
reflection runtime      NOT ESTABLISHED
reflection catch        DEFERRED / defensive
D6                      MEASURED / NO REGRESSION
D4                      DEFER
D7                      OPEN
CI                      OPEN
N3-05B                  NOT AUTHORIZED
F-N3-1                  NOT AUTHORIZED
──────────────────────────────────────────────
```

## Checkpoint 事实（冻结时实测）

| 项 | 值 |
| --- | --- |
| commits | 54（冻结点） |
| 工作树 | clean |
| 冻结物 | `rdebug-validation` **14/14 MATCH** |
| unit | 114 OK |
| transport | 58 OK |
| integration | 61 OK |
| audit | 18/18 + 1 recorded deviation |
| ruff | clean |

## 两条已闭环的项

**`context_eid`** —— 完整 correctness 闭环：

```
CONFIRMED → Contract undefined → Contract defined (§2.10) → FIXED / VERIFIED
```

含机械验证闭环（缺陷存在 8 FAIL → 修复后 16 OK → 仅回退 `core.py` 再现 8 FAIL）。
⚠️ 保留 OPEN 注记：**false-positive control verified by synthetic action tree;
real capture confirmation pending** —— 不得升级措辞。

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
| **F-N3-1** | 虽为 `REPRODUCED / NOT_EXPLAINED`，但 ExecuteIndirect 已被正式降为 extra coverage sample 并移出 frozen acceptance scope。**重开将直接突破现有 scope decision。** |
| **N3-05B** | N3-05A 已完成 frozen acceptance；05B 属 renderer/generalization 扩展，**不是当前 correctness blocker**。 |
| **D7 / D5** | 均属「增加证据能力」，当前**没有新的 correctness defect 在等待**。D7 另受实际硬件矩阵限制，单机无法推导 cross-machine claim。 |
| **CI** | 值得做，但更适合作为**下一阶段的工程化工作包**，而非紧接 correctness 调查继续堆改动。 |

## 本次冻结下唯一推进的一项（破坏性最小）

在所有候选中，破坏性最小、且**不开启任何新 workstream** 的一项：
**补上 O2 冻结文件自己记录的那条限制** —— 可达性事实原本无测试固定，
注释会腐化。

`tests/integration/test_reflection_reachability.py`：

- 纯新增测试，**不改动任何生产代码**；
- 在真实 capture 上钉住 `(center)` 附近 fragment 写入像素
  产生 shader 节点、且 `entryPoint` 非空、`debuggable` 为 bool；
- 钉的是**已冻结的事实**，不是新行为 —— 与 eid 项的
  「假阳性对照」不同，这条是**真实 capture 证据**；
- 覆盖了本轮调查暴露的 sampling 陷阱：
  角落像素仅被 clear 写过（`fragmentCandidate=false`），
  故测试从**中心**开始并用小螺旋搜索。

### 该 guard 非空转（已验证）

临时把 `pipeline()` 改成产出 catch 的形状（丢弃 `entryPoint`）：

```
FAILED (failures=1)
AssertionError: '' == '' : entryPoint must be a real observed fact,
                           not an empty default
```

还原后恢复 `OK`。在 `w00001`（S2.1 证据对象）与 `w00016` 上均通过。

## 下一次开启工作时

**单独选择一个 workstream，并从它自己的 Contract / evidence question 开始**，
而不是自动从 OPEN 状态表中挑一个继续。

## 本冻结**不**授权

```
修改 reflection catch 行为 / 新增 error flag   NOT AUTHORIZED
修改 semantic schema / diff logic / error contract  NOT AUTHORIZED
新增语料                                       NOT AUTHORIZED
O3（构造失败条件以证明该 catch）                 NOT AUTHORIZED
重开 F-N3-1                                    NOT AUTHORIZED（突破 scope decision）
N3-05B / D5 / D7 / CI                          NOT AUTHORIZED
```
