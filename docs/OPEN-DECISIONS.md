---
document_role: contract
freshness_policy: living
document_living_note: >-
  本文档只陈列待裁决项的选项与各自后果，不含任何已作选择。它描述当前待决状态，
  故为 living；一旦某项被裁决，该项移出本文档而非就地改写。
---

# OPEN DECISIONS

status: active
schema_version: 1
purpose: 让待裁决项的选项与后果可见，使裁决成为一次选择而非一次推导

## 1. 本文档不做的事

**不做选择。** 每项只列出选项、各自的后果，以及裁决前无法推进的部分。
任何一项在没有裁决的情况下被实现，都等于把未决语义伪装成已决规则。

## 2. F3 — `freshness_policy` 与正文 `status:` 行

**status: OPEN / CLASSIFICATION-CONSISTENCY GAP**

### 2.1 实测后范围已缩小

**`status:` 位于正文，不在 front matter。** front matter 里出现 `status`
会被分类控制当未知键拒绝 —— 这不是巧合，而是该 schema 的既有约束。
因此这不是「两个字段冲突」，而是「机器校验的 schema 字段」与
「无人校验的散文状态行」并存。

全仓同时具备两者的文档共 5 份：

| 文档 | freshness_policy | 正文 status |
| --- | --- | --- |
| `LINT-EXECUTION-CONTRACT.md` | `living` | **FROZEN** |
| `CONTROL-ADMISSION-CONTRACT.md` | `living` | `proposed` |
| `DOCUMENT-CLASSIFICATION-CONTRACT.md` | `mixed` | `proposed` |
| `OPEN-DECISIONS.md` | `living` | `active` |
| `REPORT-SCHEMA-OWNERSHIP.md` | `living` | `implemented` |

**只有 1 份主张内容冻结。** 其余四份的散文状态都不与 `living` 冲突：
`proposed` / `active` / `implemented` 描述的是治理进度，不是文本时效。

故实际待决问题不是「二者如何普遍共存」，而是**一个**用例。

### 2.2 该用例的选项

| 选项 | 后果 | 裁决前无法做的事 |
| --- | --- | --- |
| **A. 散文 status 不受 schema 约束** —— 二者分属不同层，无需规则 | 无需改任何文档；F3 关闭。但「散文状态可与 front matter 矛盾」成为既定事实 | 无法为散文行写任何检查 |
| **B. 散文 status 须与 freshness_policy 相容** —— `FROZEN` 要求文档声明 `point_in_time` | 该文档改为 `point_in_time`；「冻结但随实现更新」的表述不再可用 | 无法判定它当前声明是否合法 |
| **C. 禁止正文出现 status 行** —— 状态必须是 schema 字段 | 5 份文档的状态需全部迁入 front matter 并加入 SCHEMA_KEYS | 无法迁移 |

**裁决所需的一句话**：正文的散文 `status:` 行是否受 schema 约束。
先前记录的「冻结指规范文本还是治理状态」仍然有效，但它是 B 与 A 的区分点之一，
而非唯一要回答的问题。

## 3. F4 — drift 界的基准节奏

**status: OPEN / CALIBRATION GAP**

### 3.1 实测节奏

`CURRENT-EVIDENCE-FREEZE.md` 相邻两次刷新的提交间隔：

```
[1, 1, 1, 2, 1, 1, 3, 3, 3, 2, 2, 1, 19, 9, 1, 1, 3]
中位数 2   最大 19   共 17 个间隔
```

**实测节奏不是「每 2 提交」。** 中位数为 2，但存在 19 与 9 的长间隔。
`MAX_DRIFT=5` 低于实测最大间隔 19，因此它会在长间隔期间触发。

### 3.2 后果测算

| 若节奏定为 | 则 MAX_DRIFT 至少需 | 现状 |
| --- | --- | --- |
| 每提交或近每提交（中位 1–2） | 3–5 即足够 | 5 偏宽，不会触发 |
| 每阶段 / 里程碑（实测最长 19） | ≥ 19 | 5 会误报，且**已经**误报过 |

即：5 是否合适，完全取决于节奏选择。**在节奏未定之前没有可校准的基准**，
这正是 F4 不能靠调阈值关闭的原因。

**裁决所需的一句话**：状态文档应在何时刷新。选定后窗口即由实测分布直接给出，
不需要猜测。

## 4. 其余待裁决项（无选项，因为缺的是授权而非定义）

| 项 | 状态 | 缺什么 |
| --- | --- | --- |
| `evidence_ref` / `duration_s` | OPEN | 删除属**放宽契约**的授权 |
| 永久 `noqa` suppression 批准人 | OPEN / UNDEFINED BY DECISION | 指定角色 |
| `noqa` 到期日自动检查机制 | OPEN / UNDEFINED BY DECISION | 指定机制；当前只强制「必须带日期」 |
| Release blocking | FROZEN / NOT AUTHORIZED | 授权，且被 teardown 阻塞 |
| RenderDoc attribution | FROZEN / DEFERRED | 完整非裁剪 PDB（外部输入） |
| 其余 41 份文档分类 | DEFERRED | 授权；理由（schema 仍在演进）仍成立 |

## 5. 已冻结项（不在本文档内裁决）

`Lint execution`（`2c6079e`）、
`Schema-history preservation`、
`Real report artifact production`、
`Report schema ownership`（`2bb188e`，未冻结但已验证）。