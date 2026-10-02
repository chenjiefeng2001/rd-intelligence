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

## 2. F3 — `freshness_policy` 与治理 `FROZEN` 如何共存

**status: OPEN / CLASSIFICATION-CONSISTENCY GAP**

问题：`freshness_policy: living` 的语义是「必须与当前状态一致」；
`status: FROZEN` 的语义是「内容不再变更」。两者不矛盾，但共存规则不存在。
`LINT-EXECUTION-CONTRACT.md` 当前两者并存且无控制可判对错。

| 选项 | 后果 | 裁决前无法做的事 |
| --- | --- | --- |
| **A. 治理状态不参与 freshness** — `status` 属治理层，`freshness_policy` 只描述文本时效；FROZEN 的 living 文档即「规范文本已冻结，但若实现变化仍需更新」 | 需新增第三个维度或显式说明二者正交；现有分类控制可加一条正交性检查 | 无法判定 LINT contract 当前声明是否合法 |
| **B. FROZEN 蕴含 point_in_time** — 冻结文档不再要求与当前状态一致 | 已冻结的 6 份文档需重审 `freshness_policy`；「冻结但必须随实现更新」这一诉求无法表达 | 无法为 FROZEN 文档写正确的 living correction 流程 |
| **C. 禁止共存** — FROZEN 文档必须声明 `point_in_time` | 需修改至少 1 份已冻结文档；`as_of_commit` 语义要重新界定 | 无法判定哪些文档违规 |

**裁决所需的一句话**：「冻结」指的是规范文本冻结，还是治理状态冻结。

## 3. F4 — drift 界的基准节奏

**status: OPEN / CALIBRATION GAP**

问题：drift 界每 2 次提交即触发一次。它测量的是一个**节奏未声明**的刷新流程。

| 选项 | 后果 | 裁决前无法做的事 |
| --- | --- | --- |
| **A. 每提交刷新** — `baseline_commit` 随每次提交更新，`baseline_drift` 恒为 1 | drift 界退化为形式检查；陈旧度不再有信号 | 无法校准窗口 |
| **B. 每里程碑刷新** — 仅在里程碑提交更新基线 | 需先定义何为里程碑；非里程碑提交期间 drift 会增长 | 无法校准窗口 |
| **C. 事件驱动刷新** — 仅在状态文档所描述的事实变化时更新 | 需机器可判定「事实是否变化」；最复杂但语义最准 | 无法校准窗口 |

**裁决所需的一句话**：状态文档应在何时刷新。当前无论选哪个，`MAX_DRIFT=5`
都只是相对于未声明节奏的猜测。

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