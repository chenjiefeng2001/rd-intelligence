---
document_role: contract
freshness_policy: living
document_living_note: >-
  本文档的规范条款描述当前规则，随规则演进而更新，故为 living。
  注意：正文的 status 行是**散文**，不是 schema 字段；本文件的
  freshness_policy 与它并存不是冲突，二者分属不同层——见
  OPEN-DECISIONS.md F3。
---
# LINT EXECUTION CONTRACT

status: FROZEN
schema_version: 1
implementation: complete
authorized: yes
frozen_at_commit: 2c6079e
scope: existing unit gate; no eighth gate
frozen: lint execution contract + implementation, COMPLETE / VERIFIED
open_by_decision: noqa permanent-suppression approver; expiry auto-check

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

**已实施。** `release-gates.json` 的 `unit` 门带 `lint` 前置（`schema` 由 `/5` 升为 `/6`），门数仍为 7。

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

## 6. 实施结果与实施中发现的三件事

**归类的可执行形式需要可用性探测。** ruff 只用退出码即可分类，但
`python -m ruff` 在没有 ruff 的机器上退出码也是 **1**，与「发现违规」相同。
不做探测时，「ruff 缺失」会被报成内容回归 —— 这一点是被
`test_lint_that_cannot_run_stops_the_gate` 抓到的，因为它驱动的是真实
`run_gate` 而不是纯映射函数。`unit.lint.probe_command`（`ruff --version`）
因此是契约的一部分，不是便利设施。探测失败 → INFRA。

**已有控制抓到了我的回归。** 加入 lint 前置后，
`test_orchestrator_marks_child_processes` 失败：递归 marker 原本在门命令
spawn 之前设置，而 lint 的 `subprocess.run` 出现在它之前。当时并无实际递归
（ruff 不执行测试套件），但该控制的意图是 orchestrator 的每个子进程都应看到
marker，而一个日后多走一步的 lint 命令会悄悄绕过它。修法是把 marker 提前到
任何子进程 spawn 之前，并把 lint 辅助函数移到 `run_gate` 之后，使文件文本
顺序与 spawn 顺序一致。

**报告曾丢弃 lint 子记录。** `build_report` 按白名单重建 gate 行，
`lint` 不在其中，于是 unit 因 lint 判 `REGRESSION` 时，报告只有一串 detail
而没有任何字段指明是哪个检查产生的。已透传，并加控制防止再次被丢 ——
这与当初把 `tests_executed` 加进白名单是同一理由。

**语法错误与规则违规同为退出码 1。** ruff 对「文件无法解析」与「发现违规」
都给 1，因此都归 `REGRESSION`。对语法错误而言这是可辩的：文件坏了就是代码
坏了。但「退出码 1 = 存在规则违规」并不严格成立，本文件据此修正措辞。

## 7. 验收（真实 pipeline 运行，非模拟）

向仅由 `unit` 门执行的文件注入一条真实 `UP031` 违规：

```
基线        exit 3 / BLOCKED_INFRA    unit PASS 434
注入违规后  exit 2 / FAIL_REGRESSION  unit REGRESSION executed=0 exit=None
                                    integration INFRASTRUCTURE_FAILURE 63
                                    accounting_consistent True / 0 条不一致
恢复后      exit 3 / BLOCKED_INFRA    unit PASS 434
```

七项断言全通过：unit 为 `REGRESSION`；**integration 仍保留自己的
`INFRASTRUCTURE_FAILURE`**；总体按既有优先级升为 `FAIL_REGRESSION / exit 2`；
accounting 未产生假不一致；unit 未执行测试（`executed=0`）；lint 子记录
保留独立 outcome。

`exit_code` 为 `None` 而非 lint 的 1 是刻意的：门的进程从未运行，把它记为 1
会让 accounting 报出「非零退出但裁决未承认」这一并不存在的矛盾。

第一次验收尝试注入的是 `scripts/cold_warm_gate.py`，即
`cold_warm_equivalence` 门自己的脚本，于是该门一并失败，accounting 报的
不一致是**真实的**而非误报。那次失败属于验收构造不当，不是实现缺陷。

## 9. 冻结边界

本文件冻结于 commit `2c6079e`，worktree clean。冻结的是
**lint execution contract + implementation**，即 §2–§7。

**以下不在冻结范围内，仍为 OPEN / UNDEFINED BY DECISION**：

* **noqa 永久 suppression 的批准人** —— 未定义。§4 只要求理由，未指定谁能批准
  「永久」。
* **到期日的自动检查机制** —— 未实现。控制只强制「临时 suppression 必须带
  日期」，**不检查该日期是否已过**。按裁决，未自行决定机制。

冻结 lint 实现**没有**顺带解决这两项，也不得被引用为它们已有答案。

## 8. 仍未决定

* §3.1 三条出路已由裁决定为「沿用现有优先级，不新增状态、不降级」。
* **noqa 永久抑制的批准人**仍未定义。
* **到期日的自动检查机制**仍未实现：本阶段只强制「临时抑制必须带日期」，
  不检查该日期是否已过。按裁决，未自行决定。
