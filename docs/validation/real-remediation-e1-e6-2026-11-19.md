# E1–E6 真实案例诊断与修复闭环（2026-11-19）

本批不使用合成 JSON 代替真实执行：`e-cases/copy_content/` 下的 D3D11 应用由
MSVC 14.44 真实编译，加载真实 `renderdoc.dll` 并在第 10 帧触发 Capture，
生成修改前后的真实 RDC。缺陷为**engineered defect**（植入式程序级错误），
不描述为生产应用已发现的问题。

## 1. 案例与独立失败 Oracle

| 项 | 内容 |
| --- | --- |
| 应用 | `triangle_baseline.exe` / `triangle_defect.exe` / `triangle_fixed.exe`（同一 D3D11 程序的最小差异版本） |
| 植入缺陷 | 上传源 `texels` 被清零（`triangle_app_defect.cpp:133-136`）；`CopyResource` 与采样关系仍存在，因此访问图看起来正常 |
| 独立 Oracle | 真实 `pixel-history` 在 `(320,240)`、事件 11 的 shader 输出：baseline `[0.348,0.244,0.214]`、defect `[0,0,0]`、fixed 与 baseline 逐值一致（maxdiff 0.0） |
| 判定依据 | Oracle 独立于分析器 Finding；仅凭 Finding 消失不允许判定修复成功 |

## 2. E2 Binary / PDB / Source Identity（真实 S4）

`scripts/e_case_identity.py` 从 EXE 的 CodeView RSDS 记录与 PDB 信息流分别
读取 GUID/Age，并比对；`llvm-pdbutil -l` 给出 PDB 记录的源码 SHA-256，
`llvm-symbolizer` 将代码地址解析为 `triangle_app_defect.cpp:133`：

| 版本 | EXE CodeView GUID / Age | PDB GUID / Age | 匹配 | 源码 SHA-256 与 PDB 记录 |
| --- | --- | --- | --- | --- |
| defect | `120B470E-2441-4F56-8BC8-F1BA2A06FCFB` / 3 | 同值 | 是 | 一致 |
| fixed | `3E240F3A-45D8-4DBB-8784-200CE3E2007A` / 3 | 同值 | 是 | 一致 |

没有因为文件名相同或路径相似而提升等级。

## 3. E3 真实诊断

`scripts/e_case_report.py` 用 Oracle + S4 身份生成报告：

- Findings = 2（1 个正常 Copy→Sampling observation + 1 个
  `sampled_content_mismatch` anomaly，severity critical / P0）
- Diagnosis = 1，结论 `established`（门槛：独立 Oracle 差异 + 已验证 binary/source 身份 + S3/S4）
- Recommendation = 1 × `code_change`，源位置为
  `triangle_app_defect.cpp:133`，`verifiedByAttribution: true`
- Change Plan line = 133；Verification Plan 含内容 Oracle 复测与无新 anomaly 断言
- 12 章节完整，Markdown/JSON 身份一致，质量检查 PASS

## 4. E4/E5 实际修改与 Before/After

`triangle_app_fixed.cpp` 为 `triangle_app_defect.cpp` 的单处修改（diff 归档在
`source_diff_fix.txt`），重新编译得到新 EXE/PDB（GUID 已变更），生成
`fixed_frame11.rdc`。`scripts/e_case_resolution.py` 用真实前后报告与 Oracle：

```
target finding: finding-5df58e3fdb07 (sampled_content_mismatch)
oracle: same, maxDifference = 0.0
resolution: resolved (finding absent after change AND targeted verification passed)
```

没有验证证据时同一对比输出 `verification_inconclusive`，由单测固定。

## 5. 控制与边界

7 项 E 阶段单测覆盖：真实 Oracle 差异/一致、缺输出 unknown、Oracle 触发
anomaly、一致 Oracle 不触发 anomaly、独立升级门槛、EXE/PDB 身份匹配、
源码哈希记录、Before/After 必须有验证证据。

`adapter/core.py`、Gate 4、CI report schema、MCP 签名、tracked `.rdc`（0）
均零变化。远端 replay 相关门仍 `BLOCKED_INFRA`，部署仍 `NOT_ESTABLISHED`；
本地真实案例成功不代表远端已验证。

## 6. 结论

E 阶段证明了一条完整闭环：真实编译程序 → 真实 Capture → 独立 Oracle →
真实 anomaly → S4 源码定位 → 实际最小修改 → 重建身份验证 → 修改后 Capture →
Oracle 一致 → `resolved`。这是受控引擎缺陷案例，不被外推为生产应用问题。
