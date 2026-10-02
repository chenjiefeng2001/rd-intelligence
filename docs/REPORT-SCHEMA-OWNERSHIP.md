---
document_role: contract
freshness_policy: living
document_living_note: >-
  本文档定义报告 schema 的归属规则：契约与实现不一致时以谁为准、如何登记、
  由什么控制强制。它描述当前规则而非某次运行的事实，故为 living。
---

# REPORT SCHEMA OWNERSHIP CONTRACT

status: implemented
schema_version: 1
workstream: 立项于第三轮审计 F1 / F2

## 1. 要解决的问题

`docs/CI-ORCHESTRATION-CONTRACT.md` §6.1 是 gate 会计字段的规范表述，
`ci_pipeline_report.json` 是实际产物。两者**独立漂移，且漂移无声**：

* F1：实现向报告新增了 `lint` 子记录，而 §6.1 连早已存在的
  `process_exit_code` / `execution_clean` / `blocking` / `tests_executed`
  都没有列出。
* F2：`release-gates` 因新增子记录由 `/5` 升为 `/6`，`ci-pipeline` 同样是
  报告字段的改动却仍是 `/3`；且 `release-gates.json` 声明 `/6` 的同时只
  记录了 `/5` 的理由 —— 声明了一个自己未解释的版本。

**time drift 与 schema drift 的区别**：陈旧的数字描述的是过去；
漂移的 schema 让工具、审计、人读三方对**同一个形状**产生不同理解。
后者更难发现，因为两份文件各自都显得合理。

## 2. 归属规则

schema drift 有两个方向，本次**不采用单一方向**，按字段性质分别裁决：

| 字段性质 | 方向 | 理由 |
| --- | --- | --- |
| 承载 PASS/FAIL 不变式 | 实现必须服从契约 | 改它等于改门禁语义 |
| 承载**诊断**（能否区分未运行 vs 运行失败） | 实现必须服从契约 | 散文不是机器可读的同一事实 |
| 纯命名漂移 | 契约服从实现 | 实现名已被全部报告与控制引用 |
| 同义更精确的命名 | 契约服从实现 | `tests_*` 比 `skipped/failures/errors` 更准确 |

§6.2 的不变式实际只依赖 `executed` / `attempted` / `required_execution` /
`state` —— 这四项在两侧都已一致。因此本次没有任何一项裁决触及门禁语义。

## 3. 本轮具体裁决

* **实现补齐**（契约 → 实现方向）：
  `missing_prerequisites`、`discovery_anomaly`、`discovery_anomalies`、
  `spec_gate`。前两者此前**只以散文存在于 `detail`**。
* **契约跟随实现**：`gate_id` → `gate`；
  `skipped`/`failures`/`errors` → `tests_executed`/`tests_failed`/`tests_errors`。
* **登记实现已有而契约未声明者**：`blocking` / `command` / `detail` /
  `spec_ref` / `test_result` / `lint`。
* **schema 升版**：`ci-pipeline /3 → /4`，报告 `/2 → /3`，并补齐两处理由条目。

## 4. 待裁决（本 workstream 不单方面处理）

* `evidence_ref` —— 契约要求，实现从未输出，§6.2 不依赖。
* `duration_s` —— 同上。

删除任一项都属于**放宽契约**，须经裁决。它们目前在 §6.1 中显式标为
「待裁决」，由 `test_pending_rulings_are_still_recorded_as_pending` 保证
该标注不会随时间消失。

## 5. 强制手段

`tests/unit/test_report_schema.py`，8 项，位于既有 `unit` 门内，**不新增门**。

1. 契约表可被解析（防空过）
2. 契约右列承诺的每个字段确实被报告输出
3. 每行契约要求都落到实处（输出 / 重命名 / 待裁决）
4. 报告输出的每个字段都被契约绑定 ← **F1 实际咬人的方向**
5. 「待裁决」标注仍然存在（豁免不得比需求活得更久）
6. spec 的 schema 字段与代码一致 ← **F2**
7. 现行 schema 版本有理由条目 ← `release-gates` 曾在 `/6` 声明 `/5` 的理由
8. **事实被产生，而非被默认值满足** ← 见 §6

revert-only：**6/6 全部捕获**。

## 6. 一条值得记住的失效模式

控制第 4 条最初只检查报告里**有没有这个键**，于是第 8 条是补上的：
`build_report` 写的是 `g.get(field, [])`，把 `release_gate.record()`
里的输出删掉之后，键依然存在、值恒为空列表 —— 看起来与「该门没有缺失前置」
完全一样。第 8 条改为断言产生侧。

这是本项目反复出现的同一类：**控制被一个默认值或一个近似命中满足，
而不是被事实满足。**

## 7. 与已冻结项的关系

本 workstream 只处理**报告形状**。以下保持不变：

* 四态语义与 exit 映射
* release blocking（未启用、未授权）
* RenderDoc attribution（外部 PDB 阻塞）
* lint execution（`2c6079e` 已冻结）
* gate 数量（7）

## 8. pipeline verdict 未因本 workstream 改变

`BLOCKED_INFRA / exit 3`，成因仍是 integration 的 RenderDoc native
teardown `0xC0000005`。