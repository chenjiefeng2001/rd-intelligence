# D5–D7 修改建议、报告生成与端到端闭环（2026-11-19）

本批从 `3bb3e19` 推进，建立 `Finding → Recommendation → Change Plan →
Verification Plan → Complete Report → Before/After` 的完整链条。不重建
`rdebug-diagnostic-report/1` 顶层 schema，不生成自由撰写的结论。

## 1. D5：证据门槛驱动的建议

`recommendation_model.py` 分离 action type 与可执行状态：`code_change /
api_state_correction / instrumentation / capture_workload / no_change`，
`insufficient_evidence / actionable / blocked`。源码位置只能来自已验证
attribution（`verifiedByAttribution`），模型拒绝虚构文件/函数/行号。

`recommendation_engine.py` 先判断证据门槛再选措施：

| 条件 | 输出 |
| --- | --- |
| 无 Finding | `no_change` |
| 只有正常 Observation | `no_change`（不生成代码修改） |
| Finding + 未建立诊断 | `instrumentation` / `insufficient_evidence` |
| provisional 诊断 | `capture_workload` / `insufficient_evidence` |
| established + S0/S1 | `api_state_correction`，无源码位置 |
| established + S2 | 引擎级 `api_state_correction` |
| established + S3/S4 | 文件/函数/行级 `code_change` |

**关键纪律：诊断成立不等于需要修改代码。** 合法 RAW 依赖输出 `no_change`。
正向真实样本的 1 个 observation 不产生任何代码修改建议。

## 2. D5.3：Change / Verification Planner

`change_planner.py` 输出目标、范围、受影响路径、理由、前置条件、预期结果、
兼容性风险与回滚；只有 actionable 的 change 才产生计划。
`verification_planner.py` 按 Finding 类别生成针对性验证（lifetime order、
subresource mismatch、dependency 等），不是通用空清单。

## 3. D6：单一数据源的双格式报告

`report_assembler.py` 从结构化对象组装 12 章节 JSON；
`markdown_renderer.py` **只从同一 report 对象渲染** Markdown，不引入新结论。
`report_validator.py` 检查 Finding/Diagnosis/Recommendation/Change/Verification
的交叉引用，并比较 Markdown 与 JSON 的身份集合和章节数。

真实产物：

| 样本 | Finding | Diagnosis | Recommendation | 报告结论 |
| --- | --- | --- | --- | --- |
| Copy→Sampling | 1 observation | 0 | 1 × `no_change` | `no_defect_reported` |
| N3-02 零边 | 0 | 0 | 1 × `no_change` | 无 Finding |

产物：`diagnostic-report-positive-2026-11-19.json/.md`、
`diagnostic-report-negative-2026-11-19.json/.md`。两者均 12 章节、质量检查 PASS。

## 4. D7：单一工作流与 Before/After

`pipeline.py` 协调各层且不复制分析逻辑；`resolution.py` 以 finding id 关联
修改前后报告。仅当同一 Finding 在后继报告中消失**且**提供针对性
verification evidence 且通过时，才输出 `resolved`；否则为
`verification_inconclusive` / `unresolved`，不因 Finding 消失而自动关闭。

## 5. 控制

16 项 D5–D7 单测覆盖：状态词表、证据门槛、正常 observation 不产生代码修改、
established+S0 不虚构源码位置、S3 文件级方案、Change/Verification 关联、
12 章节一致性、Markdown/JSON 身份一致、伪造身份被拒、Before/After 必须有
验证证据。正向异常机制由受控 fixture 验证，**未被宣称为真实应用问题已修复**。

## 6. 边界

`adapter/core.py`、Gate 4、CI report schema、MCP 签名、tracked `.rdc`（0）
均零变化。远端 `BLOCKED_INFRA` 与部署 `NOT_ESTABLISHED` 不受本批影响。
入口一致性由共享 pipeline 保证，CLI/MCP/IDE 若接入本能力应调用同一函数。
