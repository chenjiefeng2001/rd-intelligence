---
document_role: contract
freshness_policy: living
document_living_note: >-
  本文档规定新增控制必须声明它断言的是哪一种性质。它约束的是「将来写的控制」，
  不是某次运行的事实，因此随规则演进而更新，属 living。
---

# CONTROL ADMISSION CONTRACT

status: proposed
schema_version: 1
applies_to: controls added on or after this document
grandfathers: every control that existed before it

## 1. 要解决的问题

同一个失效模式在本轮以三种形态出现，三次都没有被现有控制抓到：

| 现象 | 控制的断言 | 事实 |
| --- | --- | --- |
| `schema_history` 被截断 | 「当前版本存在吗」——是 | 旧版本的解释全被删掉 |
| `build_report` 的 `.get(field, [])` | 「键存在吗」——是 | 值恒为空列表，与「确实没有缺失前置」无法区分 |
| `unit.lint` 在 PASS 路径为 `null` | 「字段存在吗」——在该路径上否 | 该出现时是否会出现，从未被问 |

共同点不是粗心：**存在性代替了流动**。一个键在、一个版本在、一个文件在，
都不等于它承载的事实被保留、被传递、进入了最终产物。

## 2. 准入规则

新增控制必须在其名称或 docstring 中声明它断言下列哪一种性质：

* **RETENTION（保留）** —— 断言某物**仍在**，例如历史未被覆盖。
* **FLOW（流动）** —— 断言某事实**从产生处走到消费处**，而不是被默认值补齐。
* **ARTIFACT（产物）** —— 断言某事实**出现在最终产物中**，而不仅是代码里。

并且：

* 只断言「键 / 文件 / 版本存在」的控制，必须在 docstring 中说明
  **为什么存在性在此足够**。说不出理由的，视为尚未通过准入。
* 若一个控制的自然断言是存在性而实际需要 FLOW 或 ARTIFACT，
  则该控制**不完整**，必须补上产生侧或产物侧的断言。

## 3. 与本项目既有实践的关系

第 2 条不是新规矩，是把已经发生过的事写下来：

* 「unmarked ≠ error」让「未标记文档」不被强制，但要求**分类必须声明**
  —— 保留。
* `test_schema_history_is_append_only` 问的是「旧版本还在吗」—— 保留。
* `test_the_facts_are_produced_not_defaulted` 断言 `record()` 输出该字段，
  而不是 `build_report` 转发它 —— 流动。
* lint acceptance 用**真实 pipeline 运行**核对 7 个断言，而非单测映射函数
  —— 产物。

## 4. 已知不满足项（记录，不假装已修）

现有控制中有若干仍只断言存在性。本规则**不追溯**要求它们全部重写 ——
那是一次大规模改动，需单独授权。但逐条记录，避免「已符合新规」被误读：

* 分类控制断言 schema 字段存在，未断言其**值**与文档正文
  `status:` 是否自洽（即审计 F3）。
* `test_the_four_states_and_exit_mapping_are_unchanged` 以正则断言源码中存在
  映射字符串，断言的是**文本存在**而非**运行结果一致**。

## 5. 未纳入

* 未规定控制的**数量**或分布。数量不是覆盖质量的指标，本轮已证。
* 未规定存量控制何时重写。§4 只记录。
* 未新增任何门。本规则作用于既有 `unit` 门内的测试代码。