# DOCUMENT CLASSIFICATION CONTRACT

status: proposed
schema_version: 1
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
| `mixed` | 混合型；须用 `document_living_anchors` 声明哪部分是 living |

`living` 与 `point_in_time` 是本 schema 的核心区分。已裁决：**测量结果
（`unit=402`）属 `point_in_time`，不自动校验**；身份事实（commit、日期、
gate 名）与语义事实（exit 定义、流程约束）属 `living`，可校验。

## 4. 条件字段

```yaml
as_of_commit: <sha>            # freshness_policy: point_in_time 时必填
document_living_anchors: [...] # freshness_policy: mixed 时必填，非空
```

`as_of_commit` 使「这份记录截至何时」永远可回答。
`document_living_anchors` 使混合文档无需拆文件也能声明哪部分受 living 约束 ——
每个 anchor 是正文中必须存在的字面串。

## 5. 第一批四个样本文档

| 文档 | role | freshness_policy | 验证目标 |
| --- | --- | --- | --- |
| `docs/CI-ORCHESTRATION-CONTRACT.md` | `contract` | `mixed` | 混合型文档如何声明 |
| `docs/CURRENT-EVIDENCE-FREEZE.md` | `evidence_record` | `point_in_time` | 冻结数字不被误判为 stale |
| `docs/AUDIT-2026-10-02-B.md` | `audit_record` | `point_in_time` | 审计记录不被要求匹配 HEAD |
| `docs/CAPTURE-CORPUS-CONTRACT.md` | `contract` | `living` | 默认行为（living） |

## 6. 第一阶段控制范围

`tests/unit/test_document_classification.py`，只做四件事：

1. `document_role` 存在且取值合法；
2. `freshness_policy` 存在且取值合法；
3. `living` 文档**不得**携带点时锚点（`as_of_commit`）—— 不得自称是记录；
4. `point_in_time` 文档**必须**携带 `as_of_commit`，且本模块**不得**把
   点时文档与 HEAD 比较。

外加一条支撑 `mixed` 的检查：`document_living_anchors` 非空，且每个 anchor
确实存在于正文中。

**明确不做**：数字同步检查、全文时态检查、自动改写建议。
**明确不做**：新增 gate。控制位于既有 `unit` 门内，不改变门数、exit 映射
或 readiness 组合。

## 7. 已知弱点（不掩饰）

**`mixed` + anchors 无法覆盖 anchor 之外的正文。**
`CI-ORCHESTRATION-CONTRACT.md` 的开篇摘要（L5：未接线 / 未实现门 3）
位于任何 anchor 之外，因此本 schema **不会**把它判为 stale ——
它既不在声明为 living 的段落内，也没有被声明为历史。

这是本设计已知的漏洞，而不是已解决的问题。修法有两条，都需要先拆文件
或引入段落级标记，属于结构变更，超出本阶段授权。**因此 L5 仍是未决项**，
不能因为「已分类」就认为它已被处理。

## 8. 与已冻结决策的关系

* 未迁移其余 37 份文档；未标记的文档**不受本 schema 约束**，
  控制不要求它们声明分类（否则会一次性产生 37 个失败）。
* `historical_note` 已定义但第一批未使用 —— 如实记录，不为凑齐而误标。
* 不改变任何现有事实文本；本阶段只新增 front matter 与本文件。