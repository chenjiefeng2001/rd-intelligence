# D3/D4 诊断链与源码定位（2026-11-19）

本批按六个提交推进：D3.1 诊断链模型、D3.2 Diagnosis Engine、D3.3 替代解释、
D4.1 定位模型、D4.2 映射解析、D4.3 报告集成。D1 的 12 章节结构保持不变。

## 1. D3：诊断链模型

`src/rdebug/diagnostics/diagnosis_model.py` 定义互不复用的命名空间：

- 事实：`observed | inferred | unverified`，事实必须有证据引用，不允许写根因。
- 假设：`candidate | supported | weakened | ruled_out | untestable`，
  支持证据、反证、假设前提、缺失证据、区分性检查分别存放。
- 结论：`established | provisional | not_established | ruled_out`，
  必须引用假设与事实，`probabilisticConfidence` 恒为 null（不把证据数量换算为概率）。
- 诊断关系：`supported_by / explained_by / challenged_by / evaluated_as`，
  与资源访问的 RAW/WAR/WAW 因果语义分开。
- 反向可追溯：`Conclusion → Hypothesis → Facts → EvidenceRefs → Original Events`。

## 2. D3：引擎与替代解释纪律

`diagnosis_engine.py` 只对 `kind=anomaly` 的 Finding 生成诊断。
**正常 observation 不生成 Diagnosis**：D2 的 Copy→Sampling 正向样本产出
1 个 observation，D3 产出 0 条诊断链，报告明确写「没有触发需要诊断的异常」，
而不是构造一个假的 `not_established` 根因。

异常假设带有替代解释与区分性检查，例如：

- 生命周期顺序冲突：资源 ID 复用、时间戳精度 → 检查 release 后的 create 事件。
- Subresource 不匹配：同一资源的不同 view、部分更新 → 比较 view id 与 byte 范围。

结论默认 `provisional`，没有直接证据时不升级为 `established`。

## 3. D4：S0–S4 定位等级

`source_attribution.py` 与 `mapping_resolver.py` 规定：

| 等级 | 提升条件 |
| --- | --- |
| S0 | 有 Event ID（无其他映射时默认） |
| S1 | API 调用记录 + 证据引用 |
| S2 | S1 + 引擎 callsite + 符号身份匹配 + 二进制身份已验证 |
| S3 | S2 + 源文件/函数 + 源码 revision 已验证 |
| S4 | S3 + 行号已针对构建验证且二进制与源码 commit 匹配 |

负向控制明确：PDB 不匹配不得升 S2；仅路径映射不得升 S3；
行号不可验证不得输出 S4；多个候选 callsite 保留歧义；未建立源码身份时
`sourceLocation` 为空。`validate_mapping` 会重新计算等级，拒绝虚报。

## 4. 真实样本验证

`scripts/diagnostic_preview.py` 从已归档的真实分析结果生成完整 12 章节预览：

| 输入 | Findings | Anomaly | Diagnosis | 源码等级 |
| --- | --- | --- | --- | --- |
| a-d3d11 Copy→Sampling | 1 observation | 0 | **0**（不制造诊断） | **S0**（无符号/源码证据） |
| N3-02 零边样本 | 0 | 0 | 0 | S0 |

预览产物：`d34-preview-positive-2026-11-19.json`、
`d34-preview-negative-2026-11-19.json`。

## 5. 控制与边界

20 项 D3/D4 单测通过，覆盖：fact 必须有证据、假设状态、结论可追溯与无概率、
正常 observation 无诊断、零 Finding 无诊断、异常生成 provisional 链、
替代解释带区分检查、无元数据 S0、API 证据 S1、符号不匹配阻断 S2、
路径映射不升 S3、S4 需行号验证、多候选保留歧义、虚报等级被拒绝、
真实样本稳定性、12 章节保持完整。

D5（修改建议）、D6（Markdown 报告生成）尚未实现；本批报告中的
Recommendations / Change Proposals / Verification Plan 仍标为
`insufficient_evidence`。`adapter/core.py`、Gate 4、CI schema、冻结物零变化。
