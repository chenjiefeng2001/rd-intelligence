---
document_role: contract
freshness_policy: mixed
document_living_preamble: true
document_default_policy: historical
document_living_sections:
  - "1. 要解决的问题"
  - "2. 维度一：`document_role`"
  - "3. 维度二：`freshness_policy`"
  - "4. v1.1：`mixed` 的全覆盖"
  - "5. 已标记的样本文档"
  - "6. 控制范围"
  - "8. 与已冻结决策的关系"
document_mixed_note: >-
  §1-§6、§8 为 living；§7（实施过程中暴露的两个缺陷）为
  发现记录，按 document_default_policy 为 historical。preamble 含
  schema_version 与 migrated_documents 等当前状态字段，故为 living。
---
# DOCUMENT CLASSIFICATION CONTRACT

status: proposed
schema_version: 1.1
scope: 4 sample documents only
migrated_documents: 4 / 41
gate: none (controls live in the existing `unit` gate; no new gate added)

## 1. 要解决的问题

一个文件可能同时承担三种内容：

```
一个文件
  ├── 当前规范      ← 必须随实现更新
  ├── 历史阶段记录   ← 不追随 HEAD
  └── 一次运行的验证结果
```

仓库当前**没有声明**哪些内容描述现在、哪些记录过去。因此：

* 无法判断一个 stale 断言是 bug（该改）还是记录（不该改）；
* 「修正事实漂移」这类任务只能逐行追补 —— `CI-ORCHESTRATION-CONTRACT.md`
  的 L5 / L186 / L268 / L280 / L318 / L376 就是这样变成一串待补项的；
* 反过来，把点时冻结记录强行要求匹配 HEAD 会让冻结记录失去时间意义。

本 schema 不试图让文档自动变正确，只让「这份文档应当如何被对待」成为
可声明、可检查的事实。

## 2. 维度一：`document_role`

```yaml
document_role: contract | evidence_record | audit_record | historical_note
```

| role | 含义 | 典型 |
| --- | --- | --- |
| `contract` | 当前约束，要求与可执行实现一致 | `CI-ORCHESTRATION-CONTRACT.md` |
| `evidence_record` | 某次运行 / 某次冻结的事实 | `CURRENT-EVIDENCE-FREEZE.md` |
| `audit_record` | 调查或审计的过程与结论 | `AUDIT-2026-10-02-B.md` |
| `historical_note` | 阶段状态，已结束 | （第一批未使用） |

## 3. 维度二：`freshness_policy`

```yaml
freshness_policy: living | point_in_time | mixed
```

| policy | 处置 |
| --- | --- |
| `living` | **必须**与当前状态一致；陈旧即为缺陷 |
| `point_in_time` | **不得**与 HEAD 比较；须声明 `as_of_commit` |
| `mixed` | 混合型；须声明 living 区域与默认策略（见 §4） |

`living` 与 `point_in_time` 是本 schema 的核心区分。已裁决：**测量结果
（`unit=402`）属 `point_in_time`，不自动校验**；身份事实（commit、日期、
gate 名）与语义事实（exit 定义、流程约束）属 `living`，可校验。

## 4. v1.1：`mixed` 的全覆盖

### 4.1 v1 的漏洞

v1 的 `mixed` 只能声明「本文档**含有** living 区域」，不能声明「**哪些**区域是
living」。于是存在这样的内容：

* 不在任何 anchor 内；
* 也不受任何默认覆盖；
* 无声明、无归属、无控制可见。

`CI-ORCHESTRATION-CONTRACT.md` 的开篇摘要（L5：未接线 / 未实现门 3 /
release blocking）正落在这里。这不是控制失败，而是**表达能力不足**。

### 4.2 v1.1 的修法：region 级声明 + 全覆盖

```yaml
document_role: contract
freshness_policy: mixed

document_living_preamble: true      # 首个 section 之前的内容是否 living
document_default_policy: historical # 未声明 section 的默认处置

document_living_sections:
  - "0. 本阶段确立的 Contract 基础"
  - "真实状态"
```

三个字段合起来保证**全覆盖**：preamble 有策略，未声明 section 有默认，
声明的 section 精确到标题。修好之后，文档的每一行要么显式 living，
要么显式 historical —— **不存在无归属区域**。

### 4.3 继承与提升

**living 按结构向下继承。** 子节位于父节体内，因此继承属于文档结构，
不是对措辞的判断 —— 而措辞判断是本 schema 明确拒绝做的。

没有继承时模型恰好是反的：声明 `## 2.` 为 living，反而让它下面的
`### 2.2 当前实际结果` 落到 historical，文档中最规范的内容被排除在
living 之外。

**显式声明可以提升历史父节内的子节。** 这是同一规则的另一半，且必需：
`### 真实状态` 位于阶段历史段落 `## 10.` 之下，正是这种情况。

**已在 living 祖先之下的 living 声明是冗余**，会被控制拒绝 —— 不增加任何
覆盖，却读起来像「该区域已被审阅且确认无需归属」。

### 4.4 不做的事

**不扫描未声明 section 并判断其是否 stale。** 文本语义判断不是可靠控制：

```
历史记录：「Phase 2 未实现 Gate 3」   ← 正确历史
当前契约：「Gate 3 未实现」            ← 错误
```

没有关键词测试能区分二者，因此不做此类测试。

## 5. 已标记的样本文档

| 文档 | role | freshness_policy | 验证目标 |
| --- | --- | --- | --- |
| `docs/CI-ORCHESTRATION-CONTRACT.md` | `contract` | `mixed` | 混合型文档如何声明 |
| `docs/CURRENT-EVIDENCE-FREEZE.md` | `evidence_record` | `point_in_time` | 冻结数字不被误判为 stale |
| `docs/AUDIT-2026-10-02-B.md` | `audit_record` | `point_in_time` | 审计记录不被要求匹配 HEAD |
| `docs/CAPTURE-CORPUS-CONTRACT.md` | `contract` | `living` | 默认行为（living） |
| `docs/DOCUMENT-CLASSIFICATION-CONTRACT.md`（本文件） | `contract` | `mixed` | schema 自身被同一套规则约束 |

本文件标记自身，是为了让 schema **不能只约束别人**：若本文件日后出现
living 区域的失效断言，它同样会被 living correction 的流程覆盖。

`AUDIT-*` 与 `validation/phase*` 属于点时历史证据，**不新标记**。
已标记的 `AUDIT-2026-10-02-B.md` 声明为 `point_in_time`，因此**不会**被要求
匹配 HEAD —— 它不模拟 living 文档，这正是「不要让历史证据伪装成当前规范」
的实现方式；取消标记只会把它退回「无声明」的模糊状态。

**不把「未标记」当作错误。** 未标记文档不受本 schema 约束。

`CI-ORCHESTRATION-CONTRACT.md` 的解析结果：26 个 section 中 16 个 living，
preamble living，`### 真实状态` 从历史父节提升，**未分类 section 为 0**。

## 6. 控制范围

`tests/unit/test_document_classification.py`，12 项，全部位于既有 `unit` 门内。
**不新增 gate**，不改门数、exit 映射或 readiness 组合。

1. `document_role` 存在且取值合法
2. `freshness_policy` 存在且取值合法
3. `living` 文档不得携带点时锚点（`as_of_commit`）
4. `point_in_time` 文档必须携带 hash 形态的 `as_of_commit`
5. `point_in_time` 文档不得声明 living section（否则应声明为 `mixed`）
6. 本模块**不得读取仓库状态** —— 使「记录不与 HEAD 比较」成为结构性质而非承诺
7. 四份样本未被取消标记
8. `mixed` 必须声明 preamble 与默认策略（v1 洞口的直接修复）
9. 每个 living section 必须解析到**真实标题**（拒绝 `Gate` 这类模糊定位）
10. 不得重复声明；不得在 living 祖先之下冗余声明；living section 不得为空
11. **每个 region 都必须解析出策略**（计算得出，不是检查字段存在的代理）
12. front matter 内不得出现 markdown 标题

**明确不做**：数字同步检查、全文时态检查、自动改写建议。

## 7. 实施过程中暴露的两个缺陷（记录在案）

**front matter 吞掉正文。** 写入 front matter 时结尾 `---` 少了换行，
与紧随的 H1 粘连成 `---# CI integration...`。闭合分隔符于是不成其为分隔符，
非贪婪的 front matter 正则一路吃到下一条水平分隔线，把标题、日期、授权范围
和整个开篇摘要当成了元数据吞掉。

**当时 7 项控制全部通过** —— 因为一份把自身一大块塞进 front matter 的文档
依然解析得出来。这正是新增控制 12 的理由：front matter 里出现标题永远是
这个 bug，永远不会是意图。

**living 不继承导致规范内容被判为历史。** 见 §4.3，由覆盖报告发现。

## 8. 与已冻结决策的关系

* 未迁移其余 37 份文档；未标记的文档**不受本 schema 约束**，
  控制不要求它们声明分类（否则会一次性产生 37 个失败）。
* `historical_note` 已定义但第一批未使用 —— 如实记录，不为凑齐而误标。
* 不改变任何现有事实文本；本阶段只新增 front matter、修复一处
  front matter 粘连，并新增本文件。