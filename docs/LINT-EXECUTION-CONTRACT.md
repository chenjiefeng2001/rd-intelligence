---
document_role: contract
freshness_policy: living
document_living_note: >-
  本文档定义尚未实施的 lint 执行设计。它不描述发生过的事，
  其中的失败案例是设计输入而非记录，因此 freshness_policy 为 living。
---
# LINT EXECUTION CONTRACT

status: design-approved
schema_version: 1
implementation: pending
authorized: no
gate: none — no gate reads this file yet

## 1. 记录原因

`pyproject.toml` 配置了 `[tool.ruff]` 与 `[tool.ruff.lint]`，但 ruff 在本仓库中
**没有任何执行路径**：不在 `release-gates.json` 的七个门内，不被任何脚本调用。

「规则存在但无执行者」是一个**名义上存在的控制**。已实证后果：`tests/workload/
termination.py`（3 处 UP031）与 `tests/unit/test_termination_classification.py`
（1 处 B007）在多轮全量 pipeline 中存活，因为没有任何门会读 ruff 的结论。
它们最终是被一次人工检查发现的，而非被 CI 发现。

## 2. 已选方向

ruff 作为**既有 `unit` 门的前置条件**，而非新增第 8 个门：

```
unit gate
  ├── tests
  └── lint (ruff)     ← 前置
```

不采用「Gate 8 lint」，理由是：

* 新增门会产生新的 exit 映射、失败分类与 readiness 组合；
* gate **数量**不是覆盖质量的指标，已由本轮审计证明；
* 静态质量检查的性质更接近 unit 的前置条件，而非独立验证域。

**本阶段只做设计。未获实施授权，不改门。**

## 3. 问题 A：lint failure 的归类

lint 不得默认塞进 unit regression。按失败原因分类：

| 情况 | 归类 | 理由 |
| --- | --- | --- |
| ruff 未运行 | `INFRASTRUCTURE_FAILURE` | 门的前置未完成，无内容结论 |
| 环境缺少 ruff | `INFRASTRUCTURE_FAILURE` | 同上；缺的是执行环境 |
| ruff 配置损坏（`pyproject.toml` 无法解析） | `INFRASTRUCTURE_FAILURE` | 配置是门的一部分，不是被检查对象 |
| ruff 运行且存在违规 | `REGRESSION` | 对已交付代码集的确定性判定失败 |

前三种归 `INFRA` 而非 `REGRESSION` 的理由：它们**不构成对代码内容的结论**，
只说明门没跑成。把「跑不成」记成「内容回归」会污染执行记账 —— 这与
`integration` 门当前的处境是同一个错误的两个来源。

### 3.1 归类带来的裁决影响（尚未解决，需在实施前决定）

`REGRESSION` 在四态中**优先级最高**。因此「ruff 存在违规 → `REGRESSION`」
一旦成立，总体裁决将从当前的 `BLOCKED_INFRA` 变为 `FAIL_REGRESSION`，
即**风格问题会盖过真实的基础设施故障**。

这与「bug 不应掩盖基础设施问题」的既有立场冲突。三条出路：

1. 接受现状（lint 违规确实是最严重的确定性失败）；
2. lint 违规归入第四态或独立子级 —— 但这改动四态语义，**需要单独授权**；
3. lint 作为 required 前置但**不计为 gate outcome**，即
   `ruff 违规 → run 失败但 outcome 不变`。

**实施前必须先裁决这一条**，否则接上去的就是一个会掩盖故障的门。

### 3.2 与既有记账的一致性

「未执行（0 executed）」在现有四态中已可归 `INFRASTRUCTURE_FAILURE`
（`required_execution` 且 `executed == 0` 不得为 `PASS`）。
ruff 未运行应复用同一路径，**不新增分类**。

## 4. 问题 B：noqa 治理

没有治理的 noqa 会让 lint 门成为装饰品。

| 项 | 规则 |
| --- | --- |
| 谁允许写 | 引入该抑制的改动本身的作者，随该改动在同一提交内 |
| 是否需要原因 | **必须**。`# noqa` 后必须写明为何该规则在此不适用 |
| 禁止的理由 | `# noqa` 不带理由、`# noqa: E501` 用于「以后再说」 |
| 是否需要 expiry | 临时抑制**必须**带到期日；永久抑制必须写明为何永久成立 |
| 是否进入 audit | **是**。noqa 计数按规则汇总，是 review 信号；新增抑制须在 diff 中可见 |
| 谁可以批准永久抑制 | 需要在 contract 中指名角色（**当前未定义**） |

**未定义项**：批准永久抑制的角色、以及到期日的检查方式（需要控制还是仅
review）。这两项留待实施阶段确定，本文件不猜测。

## 5. 与本次审计的关系

本文件属于审计项 P1（「rule exists but no enforcement」）。
它**不影响当前 release verdict**：`BLOCKED_INFRA / exit 3` 的成因是
integration 门进程未干净退出，与 lint 无关。

## 6. 下一步的前置条件

实施前需要单独授权，且需先裁决 §3.1 的三条出路。
在本文件状态变为 `implemented` 之前，不得声称 lint 已被门禁覆盖。