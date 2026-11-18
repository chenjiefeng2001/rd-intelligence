# D1/D2 诊断报告模型与 Finding 构建（2026-11-19）

本批次建立 `Analysis → Findings` 的分层，不改变 R0–C6 的底层分析语义，
不生成源码级修改建议（D4/D5），也不生成完整报告（D6）。

## 1. D1：独立报告模型

`src/rdebug/diagnostics/report_model.py` 定义 `rdebug-diagnostic-report/1`：

- **12 个核心章节固定存在**：Executive Summary、Analysis Scope、Workload
  Overview、Evidence Coverage、Findings、Diagnosis、Impact Analysis、
  Recommendations、Change Proposals、Verification Plan、Limitations、
  Evidence Appendix。
- 章节不因缺数据而省略，也不填推测内容；缺数据时使用独立状态
  `not_established` / `unknown` / `not_observed` / `insufficient_evidence`
  并附 reason。
- **状态命名空间严格分离**：evidence 的 `observed|inferred|unknown`、
  finding 的 `confirmed|inferred|pending|not_established`、severity
  `critical…info`、priority `P0…P3` 互不复用。`supportLevel` 未被转成
  百分比置信度。
- 复现字段记录 capture、sha256 与 analysis revision；schema 与 CI report
  schema 无关。

## 2. D2：Finding 构建规则

`src/rdebug/diagnostics/finding_builder.py` 以规则数据描述三类 Finding：
`copy_sampling_dependency`（观察）、`lifetime_order_conflict`（异常）、
`subresource_mismatch`（异常）。每条规则声明 trigger、required evidence、
exclusions、alternatives、allowed / disallowed conclusions。

关键纪律：**依赖关系不等于问题**。RAW / Copy→Sampling 是图形工作负载中的
正常关系，只有出现生命周期顺序冲突或被观测到的 subresource 范围不匹配
时才生成 anomaly。Finding 必须带证据引用或明确标为 `not_established`，
且声明不允许得出的结论（例如 `confirmed_content_propagation`、
`application_source_location`）。

## 3. 真实样本验证

`scripts/finding_preview.py` 从已归档的真实分析结果生成报告骨架与 Findings：

| 输入 | 章节数 | Findings | Anomaly | 结论 |
| --- | --- | --- | --- | --- |
| a-d3d11 Copy→Sampling | 12 | 1 | **0** | 正确描述 inferred Copy→Sampling，不宣称内容传播或源码位置 |
| N3-02 零边样本 | 12 | 0 | 0 | `not_established` + 证据缺口，不误报异常 |

预览产物：`d2-finding-preview-positive-2026-11-19.json`、
`d2-finding-preview-negative-2026-11-19.json`。

## 4. 控制与边界

14 项 D1/D2 单测通过，覆盖：章节完整性、状态命名空间、无证据章节不得
伪造、规则边界声明、正常依赖不误报、负向样本无 Finding、生命周期冲突与
subresource 不匹配产生 anomaly、证据缺失被拒绝、stable findingId。

本批次不生成 Markdown 报告、不做源码定位、不输出修改建议；这些属于
D3–D6。`adapter/core.py`、Gate 4、CI schema、冻结物均零变化。
