# LINT-EXECUTION-CONTRACT

status: proposed
direction: integrate into existing unit gate
authorized: no
implemented: no

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

## 3. 当前授权状态

**未获实施授权。** 本文件仅记录方向，不构成规范条款，不改变任何现有裁决。

在获得单独授权前：

* `release-gates.json` 保持七个门不变；
* `unit` 门的执行入口不变；
* 四态映射与 exit 码不变；
* 不得据本文件声称 lint 已被门禁覆盖。

## 4. 实施时需要先解决的两个问题

1. **lint 失败归入哪一态。** 若沿用现有四态，lint 失败只能是 `REGRESSION`
   （静态确定性失败），但这会把「代码风格」与「行为回归」并入同一裁决项，
   需确认是否可接受；`unit` 门当前没有区分二者的先例。
2. **豁免机制。** `B007` 这类规则对测试代码中的循环变量有合理用法，需确定
   `noqa` 策略，否则会出现为过门禁而写的抑制注释。

## 5. 与本次审计的关系

本文件属于审计项 P1（「rule exists but no enforcement」）。
它不影响当前 release verdict：`BLOCKED_INFRA / exit 3` 的成因是 integration
门进程未干净退出，与 lint 无关。