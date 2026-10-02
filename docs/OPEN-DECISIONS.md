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

## 2. 仍需裁决的项

本节只列**尚未裁决**的项。已裁决项移入 §5 并注明其裁决位置，不在此保留 ——
否则一个「待决清单」里大半是已决项，会把下一个读者送去重新推导已经做过的决定。

| 项 | 状态 | 缺什么 |
| --- | --- | --- |
| **Release blocking** | FROZEN / NOT AUTHORIZED | 授权。技术前置是 teardown：required gate 每次通过测试却无法干净退出，会**永久阻断** |
| **RenderDoc attribution（函数级）** | FROZEN / DEFERRED | 该构建的完整非裁剪 PDB，或可符号化的 RenderDoc build。故障**字节**已确立，映射到函数仍需符号 |
| **RenderDoc fork replay 修改** | NOT AUTHORIZED | 若归因落在 replay，需先重开 scope decision |
| **Corpus manifest（N4）** | NOT DECIDED | 语料入版本控制，还是正式声明为外部前置条件。G4 已裁定为外部前置，manifest 本身未决 |

## 3. 与 verdict 上限的关系

`benchmark_archive` 为 `PROCESS_ONLY` / `UNKNOWN`，按 G4 裁决贡献 `UNKNOWN`，
故**总体永不可能 `PASS`** —— 这是设计后果，不是缺陷。

实测裁决上限：

| 情形 | 总体 | exit |
| --- | --- | --- |
| 现状（integration INFRASTRUCTURE_FAILURE） | `BLOCKED_INFRA` | 3 |
| 若 teardown 完全修复 | `NEEDS_REVIEW` | 4 |

即：**只有 teardown 能把总体从 3 推到 4；已授权工作无法使总体变为 `PASS`。**

## 4. 已移出本节的已裁决项

| 曾列于此的项 | 已裁决，位置 |
| --- | --- |
| F3 `freshness_policy` 与正文 `status:` | RESOLVED — prose `status:` 不属 classification schema。`DOCUMENT-CLASSIFICATION-CONTRACT.md` §9.1 |
| F4 drift 基准节奏 | RESOLVED — milestone / authorized state change refresh，`MAX_DRIFT = 19`。同上 §9.2–9.4 |
| `evidence_ref` 契约要求 | REMOVED — 实现从不产生、§6.2 不依赖。`CI-ORCHESTRATION-CONTRACT.md` §6.1 |
| `duration_s` 契约要求 | REMOVED — 同上；且不为满足声明而补未使用的计时器 |
| 永久 `noqa` 批准人 | DEFINED — 受影响模块的 Code Owner；无 registry 时不得标为 permanent |
| `noqa` 到期检查 | DEFINED — 日期必须**解析并与运行时日期比较**；缺失或过期即 REGRESSION |
| 其余 41 份文档分类 | 范围已定为**治理边界**而非 rollout 进度；义务移到依赖发生的那一刻。`DOCUMENT-CLASSIFICATION-CONTRACT.md` §8 |

## 5. 已冻结项（不在本文档内裁决）

`Lint execution`（`2c6079e`）、
`Schema-history preservation`、
`Real report artifact production`、
`Report schema ownership`（`2bb188e`，未冻结但已验证）。