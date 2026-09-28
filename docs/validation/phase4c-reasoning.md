# Phase 4c：Grounded Reasoning Benchmark

日期：2026-08-24 · 被测模型：ox-alpha（self-play，仅见 diff_pixel 工具输出）
原始数据：`phase4c-reasoning.json` · 答案存档：`phase4c-answers.json`
Evaluator：`scripts/reasoning_bench.py`（ground truth 自动取自确定性 DiffResult）

## 结果（Clear 语义修正后）

| 指标 | 得分 |
| --- | --- |
| Cause correctness（firstDivergence 层判定） | **4/4** |
| Evidence correctness（引用 id ⊆ ground truth evidence） | **4/4** |
| Fact correctness（(eventId, resourceId) 声明均有 evidence 支持） | **4/4** |
| Unknown discipline（逐层状态与 ground truth 完全一致） | **4/4** |
| No over-inference（无超出证据的因果断言） | **4/4** |

## Benchmark 抓到并修复了一个真实缺陷

**第一轮评分：facts 2/4、no over-inference 2/4。**

失败原因不是 LLM 幻觉，而是 **Semantic API 的 evidence 缺口**：`diff_pixel` 的
`input_bindings` / `resource_provenance` 层只携带 history evidence，未携带其断言所依赖的
`reads` / `written_by` evidence——导致"PS 读取 Texture::47"、"Texture::47 由 Copy#2 写入"
这类**真实且可验证**的声明，在 diff 输出内部无法核验。

这正是 Evidence-first 架构要防范的："证据只到 A，结论说到 B"——即使结论碰巧为真。

**修复（v1 加法演进，`d92d6e5` 之上）**：
- `input_bindings` 层 evidence 补齐两侧所有 reads 证据；
- `resource_provenance` 层 evidence 补齐两侧全部 writer/reader 证据（不再只收集差异项）。

修复后重跑：**5 项指标全部 4/4**，且 69 个核心测试全绿。

## 四个 Case 与 Ground Truth

| Case | 输入 | comparison | firstDivergence | 关键 unknown |
| --- | --- | --- | --- | --- |
| case_same | (10,10) vs (20,10) | same | — | fragment/shader/shader_input_values（两侧仅 clear） |
| case_fragment | (320,240) vs (10,10) | different | **input_bindings**（good 读 ::47，bad 可证无读取） | shader / shader_input_values / provenance |
| case_deep_input | (330,240) vs (320,240)，deep | different | **shader_input_values**（v0/v1 逐值） | — |
| case_structural_unknown | 同上，structural | different | pixel_value | **shader_input_values**（被正确保持为 unknown） |

## 结论

确定性 DiffResult → 自动 evaluator → LLM 解释的完整评估链路成立。
benchmark 在第一轮就发现了人工审查大概率会错过的 evidence 缺口，
修复后 LLM 解释与确定性结论完全对齐。

**至此证据链闭环**：`Replay → Facts → Evidence → Local Causal Graph → Deterministic
Diff → First Divergence → MCP → LLM → Evidence-grounded Explanation`，且每一环都有
自动化验证。

## 后续（按优先级，均未开工）

1. transport 会话复用（2.4–3.3s/调用 → 预期 <100ms/后续调用）
2. 采样到的纹理内容比较（当前 shader_input_values 只覆盖插值输入）
3. IDE / CI 集成试点

> **2026-09-29 核对（历史状态已过时）**：第 1 项已由 **Phase 4d** 完成
> （稳态 184.5ms vs cold 6993.5ms ≈38×，见 `phase4d-session-reuse.md`）；
> 第 3 项已由 **Phase 5a**（CI 门禁）与 **Phase 5b**（IDE 原型）完成。
> **仅第 2 项（采样纹理内容比较）仍未开工**，并已在 `DESIGN_SPEC.md:169` 冻结，
> 触发条件为 unknown 分布证明深层原因需求。
