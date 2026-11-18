# R6.2 远端 CI 前置条件核对（2026-11-18）

本记录把远端 `BLOCKED_INFRA` 的三个成因逐一落到可复核证据上。**不修改
workflow、gate 定义、状态映射或 corpus/fixture 边界；不以放宽门禁取得 PASS。**

## 1. 证据来源

- HEAD `5ff1ac6` 对应的远端 run `44316206734`（push 触发），`ci-reports`
  artifact 中的 `ci_pipeline_report.json`。
- 同一提交的本地全量管线（带 `RDEBUG_RENDERDOC_PATH` 与
  `RDEBUG_INTEGRATION_CAPTURE`）为 `overall = PASS / exit 0`。
- 远端 `section4-gates` exit 3；`package-build` job success。

## 2. 三个阻塞项

| 门 | 远端裁决 | 缺失前置（报告原文） | 能否在代码内解决 |
| --- | --- | --- | --- |
| `integration` | `INFRASTRUCTURE_FAILURE / executed=0` | `env:RDEBUG_RENDERDOC_PATH`、`env:RDEBUG_INTEGRATION_CAPTURE`、`module:renderdoc`、`capture:RDEBUG_INTEGRATION_CAPTURE` | 否：需与解释器匹配的原生模块、GPU replay runtime 与外部供给的 capture |
| `cold_warm_equivalence` | `INFRASTRUCTURE_FAILURE / executed=0` | `env:RDEBUG_RENDERDOC_PATH`、`module:renderdoc`、`capture:RDEBUG_INTEGRATION_CAPTURE` | 否：同上；该门会真实 spawn replay worker |
| `fork_integrity` | `INFRASTRUCTURE_FAILURE / exit=1` | `F3 ABSENCE_EXTERNAL`：`/home/runner/work/.../rdebug-validation` 下无 `n3-corpus/metadata/N3-05A*.json` | 否：外部冻结证据不在本仓库，workflow 只供给 fork workspace |

## 3. 可确认的事实

- 远端 unit `PASS / 1116`、transport `PASS / 58`、boundary_audit `PASS`、
  benchmark_archive `PASS`（R4.3 的 blob 哈希修复后持续可达）；这些门不依赖
  GPU / capture / 外部验证目录。
- 本地同一提交七门全 PASS，说明代码本身没有内容回归；远端 INFRA 成因
  仅为环境/外部输入缺失。
- `tracked .rdc = 0` 是既定契约（capabilities 声明 `source: external /
  tracked: false / provenance_required: true`）。把 14 个仓库自生成 fixture
  或任何 capture 作为 artifact 注入 runner 会改变 replay 门的 population，
  属独立裁决，**本批次不做**。
- `../rdebug-validation` 是仓库外的冻结验证环境，不在本仓库版本控制内；
  fork 审计按 `CAPTURE-CORPUS-CONTRACT` §5 把缺失外部 artefact 报为 infra，
  这是契约规定的正确分类。
- hosted runner 无 GPU / RenderDoc replay runtime，无法通过代码配置补齐。

## 4. 结论

在环境变量、匹配模块、外部 capture 与外部验证目录真正供给到 runner 之前，
远端 `BLOCKED_INFRA / exit 3` 仍是**正确且诚实**的结果。本批次不改变该状态，
也不把 CI 通过等同为部署完成。

下列项目保持 **NOT_ESTABLISHED**：远端真实 replay 结果、远端 cold-warm
等价性、远端 fork 审计结论、部署状态。若后续供给前置条件后重跑并出现真实
回归，应按既有四态契约原样报告，不得折叠为 INFRA 或 PASS。
