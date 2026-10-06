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
  - "8. 治理边界与纳入条件"
document_mixed_note: >-
  §1-§6、§8 为 living；§7（实施过程中暴露的两个缺陷）为
  发现记录，按 document_default_policy 为 historical。preamble 含
  schema_version 等当前状态字段，故为 living。
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

## 9. F3 / F4 裁决（已定义，可实施）

本节记录两项裁决及其依据。裁决不等于实现 —— 实施按 defect-version →
revert-only → restore → real validation → freeze 流程进行。

### 9.1 F3 — 正文散文 `status:` 不受 schema 约束

**RESOLVED — NOT A SCHEMA CONFLICT**

* schema 约束的是**已声明的 machine-readable classification metadata**，
  即 front matter 中的键。
* 正文中的 `status: ...` 是**散文治理状态**，不是 schema field。
* 因此不得由 `freshness_policy: living` 与正文 `status: FROZEN` 同时出现
  推导出 schema 矛盾。
* **规则**：`status:` 出现在正文时，除非被明确纳入 schema，否则
  **不得被 classification controls 当作 machine-readable metadata**。
  未来若需机器约束正文 status，应另行定义 canonical status 字段与语法。

这也解释了为何其余四份文档的 `proposed` / `active` / `implemented`
不与 `living` / `mixed` 冲突：它们描述**治理进度**，不是文本时效。

### 9.2 F4 — 状态文档按 milestone 刷新

**RESOLVED — milestone / authorized workstream state change refresh**

**不是每个 commit 刷新。** 「milestone」定义为：产生需要成为当前状态事实的
已授权工作流变化，即

* 已授权 workstream 完成并冻结；
* 实现状态从 `proposed` → `implemented` / `verified`；
* 已有 OPEN 项得到正式裁决；
* 冻结状态发生实质变化。

普通实现 commit、控制修复 commit、纯测试或文档内部修正，
**若未改变当前状态事实，不触发状态刷新**。

### 9.3 calibration（两次：先值，后范围）

**第一次：初始数值。**

```
MAX_DRIFT = 19 commits
```

依据实测的刷新间隔分布（`CURRENT-EVIDENCE-FREEZE.md` 相邻两次刷新的提交间隔）：

```
[1, 1, 1, 2, 1, 1, 3, 3, 3, 2, 2, 1, 19, 9, 1, 1, 3]
median 2   max 19   17 个间隔
```

19 **不是「永远正确」**，而是以当前真实 milestone cadence 校准出的初始窗口。

**改阈值来消除报警：否。** 若 milestone 节奏改变，F4 重新进入 calibration，
不得静默调整数值。

**第二次：改的是适用范围，数值未变。** `MAX_DRIFT` 仍为 **19**。

原控制把该上界无区分地施加于所有带 `baseline_commit` 的文档。但它是为
「**按 milestone 刷新的状态文档**」校准的，而被施动的目标文档自报分类为：

```
document_role: evidence_record
freshness_policy: point_in_time
```

并自述「任何时点声明都自动过期。按本合同 §3，`point_in_time` 记录描述
**某一个时刻**，本就应随 HEAD 前进而老化。要求它跟随 milestone 节奏，是把
证据记录当成状态文档的**类别错误**。

触发场况：P9a 封存后的功能开发（React 前端、事件流、查询存储）
本身**不产生任何 P9a 证据**，因而在该文档的语义下没有发生一次
F4 意义上的 milestone；真正发生的状态变化（工作流 A 由 CLOSED/NOT IMPLEMENTED
转为 IMPLEMENTED、IDE HTTP 表面 7 → 9 端点）已分别记录在各自的契约文档中。

**上界改为按文档类别分流**：

| 声明的 `freshness_policy` | 受约束的不变式 |
| --- | --- |
| `living` / `mixed` | 实际陈旧 ≤ **19 commits**（数值未变） |
| `point_in_time` | 无 commit 上界；`as_of_commit` 必须是 HEAD 的**真实祖先** |

`point_in_time` 的新不变式**同样会失败**：它拒绝一份指向本仓库不内容有的
提交的时点记录——这正是「描述一个已不存在的仓库」的实际形态，
且无法靠等待绕过。

**漏洞已被主动合上**：以一份文档声明 `point_in_time` 来躲免上界，在理论上可行。
缓解所靠的是：该声明同时出现在前缀 front matter 与 `docs/README.md` 索引表中，
而索引一致性本身受 `test_docs_index.py` 控制——重分类是一个**可见的变更**，
而不是一个只需要等待的状态。

### 9.4 与之相适应的漂移不变式

在 milestone 节奏下，文档声明的 `baseline_drift` 在两次刷新之间**必然落后于**
实际值 —— 普通 commit 不触发刷新。因此「声明值 ≈ 实际值」不可强制，
它编码的是被本裁决取代的每提交节奏。可强制的只有两条：

* **`baseline_drift` 不得高于实际值** —— 文档永不声称自己比实际更新；
* **实际 drift 不得超过 `MAX_DRIFT`** —— 陈旧度有界。

「声明值至少接近实际值」这一检查随每提交节奏一并移除。

## 8. 治理边界与纳入条件

### 8.1 范围是治理边界，不是 rollout 进度

先前把未标记的文档描述为「待完成的遗漏」，理由是第一批评测覆盖。这个理由
描述的是**暂时的推进状态**，因此一旦 schema 演进就会失效 —— 事实上它已失效：
schema 现为 1.1，F3/F4 已裁决并实施。

**现行范围**：分类 contract 治理的是**参与现行状态、CI、证据冻结与审计闭环**
的文档。尚未纳入该治理面的文档，**不因未分类而成为错误**。

未分类因此不再是待补的缺口，而是一个**边界外的事实**。

### 8.2 纳入条件（admission condition）

> 一个未分类文档，一旦被 active contract、current-state record、CI gate 或
> audit control 作为**机器可解释输入**使用，就必须先完成分类。

这条取代「逐步迁移 41 份」。它把义务放在**依赖发生的那一刻**，而不是放在
一份永远追不上的迁移清单上：既不要求低价值的大规模迁移，也不允许新的
active 依赖绕过分类。

该条件由 `test_unclassified_documents_are_not_machine_read` 机械强制 ——
凡被控制以路径常量引用的 `.md`，必须已分类。

### 8.3 与已冻结决策的关系

* 未迁移其余 41 份文档，且**不将其记为负债**。
* `historical_note` 已定义但第一批未使用 —— 如实记录，不为凑齐而误标。
* 本阶段不改变任何现有事实文本。

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
