# C1–C6 收口记录（2026-11-19）

本记录把资源访问语义与真实工作负载覆盖扩展的第一轮工作收口。R0–R6
保持冻结；本轮不重新审计已通过项，不以 CI/部署作为能力完成判据。

## 1. 提交清单

| 批次 | 提交 | 内容 |
| --- | --- | --- |
| C1/C2 | `3e102b6` | 现有 capture 覆盖核查；真实 Copy→Sampling 正向关系（a: 256 边、b: 128 边） |
| C3 | `6fd6f24` | RAW/WAR/WAW 类型依赖 + Copy/Resolve via 标注，真实样本 256 条 raw(via=copy) |
| C4 | `0d8c3c7` | descriptor-level subresource/region 解析（mip/layer/byte range）+ coverage 三分类 |
| C5 | `f702cde` | 5 个真实工作负载的依赖/生命周期一致性核查 |
| C6 | 本记录 | 双语 API 同步、全量回归与收口 |

## 2. 能力修正

- **正向真实关系已建立**：此前 N3-05A1/A2 零边被正确解读为「样本未观测到」，
  而非分析器无能力。已登记的 D3D11 fixture 提供真实的
  `CopyDst@2 → PS_Resource@11..266` 关系，256 条边全部带两端 GetUsage
  证据引用、`supportLevel=inferred_from_order`。
- **依赖类型可检查**：RAW/WAR/WAW 规则明确，Copy/Resolve 通过 writer 的
  accessType 标注；所有关系仍为顺序推断，不升级为内容传播。
- **Subresource 不再一律 unknown**：`GetDescriptorAccess` + `GetDescriptors`
  真实提供 mip/layer/byte 范围与资源引用；无证据时仍显式 unknown。
  该实现放在 `adapter/descriptors.py`，`adapter/core.py` 与 Gate 4
  受控面保持零 diff，无需重归档。
- **Coverage 可审计**：analyzed / unobserved / missingInput 三类互斥，
  不再以「存在若干访问事件」声称完整覆盖。
- **Alias 与内容传播保持 NOT_ESTABLISHED**：资源 ID 相同不证明物理别名。

## 3. 最终回归矩阵

| 检查项 | 结果 |
| --- | --- |
| unit | **PASS**，executed **1140** |
| transport | **PASS**，executed 58 |
| integration | **PASS**，executed 77 |
| boundary_audit / cold_warm_equivalence / benchmark_archive / fork_integrity | 全 PASS |
| overall | **PASS / exit 0**，release blocking enabled |
| ruff | All checks passed |
| 专项控制（parity / unknown discipline / entry consistency / compat / docs index / explain / query / dependency / subresource） | **91 项 PASS** |

## 4. 仍开放的能力缺口

- 现有已登记 capture 未覆盖：Render Target 写入→后续采样、Compute UAV→SRV、
  Depth 写入→使用、Resolve→读取、多 Mip/Array Layer 的 writer→reader 匹配。
- N3-03-execute-indirect 因已知 F-N3-1 崩溃保持 NOT_ESTABLISHED。
- Alias、内容传播、跨资源物理身份没有可用证据。
- 远端 replay/cold-warm/fork 门与部署状态保持 NOT_ESTABLISHED / BLOCKED_INFRA，
  属独立基础设施工作。

## 5. 边界核对

`adapter/core.py`、benchmark manifest（`archived_at_commit = 732a0d0`）、
`CURRENT-EVIDENCE-FREEZE.md`、CI report schema、MCP 签名、tracked `.rdc`（0）
均零变化；未把 fixture 加入 tracked corpus，未把分析结果注入 CI 报告。

## 6. 结论

C1–C6 把资源访问分析从「能记录访问与推断边」推进到「在真实 Copy→Sampling
工作负载上有正向关系证据、有类型化依赖、有可解析的 subresource 与可审计
的覆盖分类」。下一项工作应由新的真实输入或明确需求驱动，不以 CI 收口或
新增字段替代能力验证。
