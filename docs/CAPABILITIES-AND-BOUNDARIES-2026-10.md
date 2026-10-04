---
document_role: audit_record
freshness_policy: point_in_time
as_of_commit: d691050
document_point_in_time_note: >-
  本文档是基线快照，描述 as_of_commit 时的能力边界，不追随 HEAD。其中的实测数字
  （门禁裁决、测试计数、tracked/declared 计数）属于该时点，按裁决不做自动数值校验；
  「能否做到 / 不能做到」的语义事实受 OPEN-DECISIONS.md 与各 Contract 约束。
---

# 能力矩阵与能力边界（快照）

## 0. 一句话状态

`overall = BLOCKED_INFRA / exit 3 / failure`，`accounting_consistent = True`，
7 门中 6 个 PASS。唯一成因：`integration` 在 RenderDoc native onexit 阶段的
`0xC0000005`。

## 1. 门禁层（权威 spec `release-gates /6`）

| 门 | spec | blocking | required | runner | 快照实测 | 独立通过 |
| --- | --- | --- | --- | --- | --- | --- |
| `unit` | 4.1 | 是 | 是 | unittest | PASS，executed 502 | 可 |
| `transport` | 4.1 | 是 | 是 | unittest | PASS，58 | 可 |
| `boundary_audit` | 4.2 | 是 | 是 | exit_code | PASS，18/18 + 1 已记录 deviation | 可 |
| `cold_warm_equivalence` | 4.3 | 是 | 是 | verdict_json | PASS | 可 |
| `fork_integrity` | 4.5 | 是 | 是 | exit_code | PASS，1 tracked / 1 declared，F1–F4 全 not present | 可 |
| `integration` | 4.1 | 是 | 是 | unittest | INFRASTRUCTURE_FAILURE，63 项 OK，`process_exit 3221225477` | **不可** |
| `benchmark_archive` | 4.4 | 否 | 否 | — | UNKNOWN（PROCESS_ONLY） | **设计如此** |

`integration` 的失败形态本身是 accounting 的产出：63 项 `test_result=OK`、
`tests_failed=0`，但进程无法干净退出 → `INFRASTRUCTURE_FAILURE` 而非
`REGRESSION`。二者并排保留、互不覆盖。

## 2. 可执行套件

| 套件 | 规模 | 快照状态 | 是否门禁 |
| --- | --- | --- | --- |
| `tests/unit` | 502 collected | 499 passed / 3 skipped（无 RenderDoc）；502 executed（有环境） | 是 |
| `tests/integration` | 63 | 全 OK，进程退出失败 | 是 |
| `tests/workload` | 7 passed / 9 skipped | 通过 | **RULED AGAINST** |
| `tests/pipeline` | 1 skipped | — | 否 |

## 3. 治理与证据层

| 能力 | 快照实测 |
| --- | --- |
| 文档总量 / 分类 | 41 份：8 `contract`、2 `audit_record`、1 `evidence_record`、30 未分类 |
| 未分类文档 | **不被任何机器控制读取**（治理边界，非债务） |
| execution accounting | 一致，0 条不一致 |
| release blocking | 关闭（`release_blocking_enabled = False`） |

## 4. 能做到什么

1. 把 native 崩溃定位到指令级：`mov rbx, qword ptr [rax]`（`48 8b 18`）@
   image offset `0x4A0A4E`，`RAX = 0` 为解引用源；`RBX` 非空、`[RBX] = 1` 可读，
   二者被**排除**为故障源；空检查位于解引用之后。原始 cdb 输出逐字留存。
2. 推翻自己先前写入冻结记录的结论，并把撤回标注传播到全部三个相关文档。
3. 区分「测试逻辑通过」与「进程干净退出」，并在报告中并排保留两个事实。
4. fail-closed 覆盖七种失败形态：缺前置、0 执行、发现异常、低于 floor、内容失败、
   非零退出、跳过 —— 均不可能被读成通过。
5. 强制门禁输入身份：`integration` 只接受 producer 声明的 canonical 路径，非成员
   在**运行前**判失败，声明不可读也不静默放行。
6. 让生成器对自己诚实：producer 曾把跳过计数当 population 数量上报，现以单一
   canonical 命名 + 精确成员判断修正。
7. 区分「不具备」与「具备」：确定性验证被判为外部前置，同时保留
   `NOT ESTABLISHED`。
8. 判定归因不可行并给出原因：本地 PDB 与故障映像分属不同构建
   （`6A8B9BFE` vs `6A8B9BA9`）。
9. 证明不存在可执行修复路径（枚举四条路线及各自阻塞依据）。
10. 维持单点真源：主动消除双真源漂移风险。

## 5. 不能做到什么

| 不能做 | 阻塞类型 | 依据 |
| --- | --- | --- |
| `overall` 变为 `PASS` | **设计不可达** | `benchmark_archive` 为 PROCESS_ONLY / UNKNOWN，按 G4 贡献 UNKNOWN；teardown 全修后上限也只到 `NEEDS_REVIEW / exit 4` |
| `integration` 通过 | OPEN / BLOCKED_BY_ATTRIBUTION | 修 RenderDoc 需知道改哪里；归因不可得 |
| 修复 teardown | NOT_EXECUTABLE UNDER CURRENT EVIDENCE | 见 §6 |
| 函数/源码级归因 | BLOCKED_BY_EXTERNAL_INPUT | 需与 `6A8B9BA9` 匹配的 PDB 或可符号化构建 |
| 检出 R2 | BLOCKED_BY_EXTERNAL_DETERMINISM_EVIDENCE | Layer A 只覆盖存在性与成员资格 |
| 启用 release blocking | OPEN / NOT_AUTHORIZED | 现启用会永久阻断 CI |
| 证明 fixture 内容确定性 | BLOCKED_BY_EXTERNAL_DETERMINISM_EVIDENCE | 本项目不产生该证据 |
| 在 CI 中运行 | 无 remote | `ci.yml` 从未执行；证据为单机 |
| 从干净 clone 复现 gate | 外部 corpus | 14 个 fixture untracked，供应为外部前置 |

## 6. 为什么 teardown 修复是「不可执行」而非「尚未推进」

- 改 RenderDoc → 需知道改哪里；归因未确立且已测定不可行，**即使授权也写不出
  正确修复**
- 退出码掩码 / `os._exit` / 子进程 wrapper → 明文禁止
- 排除门禁 / 把缺失当通过 → 契约禁止；accounting Contract 已冻结
- 扩大 replay 排除面 → 唯一可得链条 `crash → 怀疑 replay → 扩大排除` 不被允许

这是当前证据的结论，不是进度落后。

## 7. 已知缺口（全部 OPEN，未修）

1. **R2 内容替换检测** —— 阻塞于外部确定性证据
2. **`cold_warm` 单点声明** —— spec 只声明一个硬编码路径，未断言成员资格；且
   前置检查路径与实际执行路径可不一致（C1 裁决**故意保留**）
3. **`manifest_match` population 错位** —— 唯一 sha256 校验覆盖门禁**不消费**的
   那批 capture
4. **`harness.discover_corpus` 的 glob** —— 同样接受 `w00001_evil.rdc`；非门禁消费者

后两项在单机环境下不改变任何裁决；CI 接入后会成为实际风险。

## 8. 一处必须保留的确定性边界

`unit = UNKNOWN` 且 `integration = PASS` → `overall = exit 4`，**仅为归约顺序
推导，未测量**。已实测的是 `unit = UNKNOWN` 与 `integration = INFRA` 并存时
`overall = exit 3`。

## 9. 重新开启工作流所需事件（任一）

1. 与 `6A8B9BA9` 匹配的 PDB / 可符号化构建
2. 上游修复或替换 RenderDoc 构建
3. O1 重复生成确定性证据
4. 独立于崩溃推断的正式治理提案

---

**文档用途**：把「不可修复是因归因证据缺失，而非进度落后」这一结论机器可读化，
防止后续迭代重演「反复尝试写不出正确修补」的无效循环。任何重开都必须引用
`OPEN-DECISIONS.md` 的四项 OPEN 之一或一份正式治理提案。