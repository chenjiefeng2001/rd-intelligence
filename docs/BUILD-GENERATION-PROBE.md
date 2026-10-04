---
document_role: contract
freshness_policy: living
document_living_note: >-
  本文档定义 MSBuild classic VCXPROJ generation 探针的边界与验收命题，随探针阶段
  的授权与结论演进而变。各阶段的**实测结果**记录在
  docs/PDB-ATTRIBUTION-RESULT.md §7；本文档只定义「允许收集什么证据」与
  「什么算通过」，不记录结果，也不得被结果反向改写。
---

# BUILD GENERATION PROBE（Scheme B）

## 1. 目的

本探针仅回答一个问题：

> **在当前 RenderDoc checkout 中，classic `.vcxproj` 是否存在一种可重复、可观测、
> 可证伪的 MSBuild 机制，能够证明 `Release|x64` 项目的「完整 generation」已经完成，
> 同时证明过程中没有进入 C++ compilation。**

本探针**不是** RenderDoc 构建、事故复现、attribution 或修复验证。

目标不是「找到一个能返回 0 的 target」，而是同时建立：

1. project evaluation 已完成；
2. generation 阶段所定义的必要 MSBuild targets/tasks 已执行；
3. generation 产物已生成，或被明确证明为当前项目 generation 的完整输出；
4. 没有发生 C++ compilation；
5. 失败时能区分：**探针定义错误** / **项目不支持该 generation 路径** /
   **generation 不完整** / **意外进入 compilation**。

若上述条件无法建立，结果必须保持 `UNKNOWN`。**不得**以 exit code=0、
`PrepareForBuild` 成功、或 `DesignTimeBuild` 参数存在本身推导完整 generation。

## 2. Scope

### 2.1 允许

- 当前 checkout；当前已固化的 fork delta；MSBuild / Visual Studio 现有工具链
- `renderdoc.sln`、`renderdoc\renderdoc.vcxproj`、`Release|x64`
- 不产生源码修改
- **不修改** `.vcxproj`、`.sln`、props、targets、`release-gates.json`、fork exception
- 输出目录必须位于仓库之外，或使用现有项目允许的隔离输出位置
- 读取 MSBuild binlog、task execution、target execution 与产物差异

### 2.2 明确禁止

本探针不得：

- 编译任何 C/C++ translation unit；运行 `cl.exe` 编译动作；运行 `link.exe`
- 以生成 `renderdoc.dll`、`renderdoc.pyd` 等最终二进制作为验收目标
- 修改源代码以增加 probe target；修改 `.vcxproj` 以制造 `DesignTimeBuild` 路径
- 修改项目条件使 compilation 被人为跳过后，再声称「项目原生 generation 完成」
- 进入事故复现；进行 attribution；以事故崩溃作为 generation 成败依据
- 通过 `os._exit`、exit-code masking、wrapper 改变结果
- **将「没有观察到 `cl.exe`」单独作为 no-compilation 证据**

## 3. Generation 的操作性定义

「完整 generation」定义为：

> MSBuild 已执行 classic `.vcxproj` 中位于 **compilation boundary 之前**、且对当前
> Configuration/Platform 有效的**全部** generation prerequisites，并产生该阶段定义的
> **全部**可观察生成产物；同时没有进入 C++ compilation 或 linking。

必须先从当前 `.vcxproj`、imported `.props/.targets` 与实际 binlog 建立 **G-Map
（Generation Target Map）**，记录：

- entry target
- dependency chain
- 每个 target 的实际执行状态
- 每个 target 所属阶段：`evaluation` / `generation` / `compilation` / `linking`
- generation target 的输入与输出
- 是否存在 `BeforeTargets` / `AfterTargets` / `DependsOnTargets` 条件
- Configuration/Platform 条件
- 是否存在 `DesignTimeBuild` 条件
- 是否存在 `BuildingInsideVisualStudio` 等条件
- 是否存在 `BuildProjectReferences` 等影响路径

> **G-Map 必须来自当前 checkout 的实际项目定义与实际 MSBuild binlog，不得凭
> MSBuild 常识预先指定。**

## 4. Probe P0 —— 只读建立 Generation Map

目的：在不执行 generation 的前提下，确定 classic `.vcxproj` 中哪些 target 可构成
generation 边界。

允许：读取 `.vcxproj`；读取其 imported `.props/.targets`；搜索 target /
`DependsOnTargets` / `BeforeTargets` / `AfterTargets`；读取已有 MSBuild diagnostic
信息；使用 MSBuild 项目求值能力，**但不得触发 compilation**。

输出：`generation_entry_candidates`、`generation_dependency_chain`、
`generation_output_candidates`、`compilation_boundary_candidates`、
`design_time_conditions`、`configuration_conditions`。

**P0 PASS 仅表示**已建立一个由当前项目文件支持、可追溯的 generation target map。
**P0 不证明 generation 已执行。** 若无法确定 generation 边界 → `UNKNOWN`，而**不是**
项目失败。

## 5. Probe P1 —— No-Compilation Sentinel

目标：建立可**靠检测** compilation 是否发生的证据，而非观察系统中是否存在 `cl.exe`。

### A. MSBuild binlog task/target evidence

检查：`CL` task 是否执行；`ClCompile` 是否实际执行 compilation command；`Link` task
是否执行；是否存在实际 compiler command line；是否存在 `/c`；是否存在 `.cpp` → `.obj`
command。

> `ClCompile` 作为 item/type/reference 名称**本身不得视为 compilation**。
> `ClCompile` item evaluation、`CommandLineForReferenceDependsOn`、
> `ResolveReferences`、`GetClCommandLineForReferenceSupported` 均不得单独解释为
> C++ 编译。

### B. Output-diff evidence

probe 前后记录 `x64\Release` baseline、probe output directory，以及 `.obj`、`.lib`、
`.dll`、`.pdb`、generation-specific outputs，必须记录：

```text
baseline_count
after_count
new_files
removed_files
changed_files
```

### C. Command evidence

只有在 binlog 中出现**实际 compiler invocation** 时才记录 compilation。
**进程名扫描不是验收证据。**

### P1 PASS 条件（须同时满足）

```text
actual_cl_invocation == 0
actual_link_invocation == 0
no_cpp_compilation_command == true
```

并且有 binlog 或等价的 MSBuild execution evidence 支撑。

## 6. Probe P2 —— Native Generation Target Candidates

**只有 P0 已建立 target map 后**，才允许测试候选 target。候选必须来自当前项目实际
存在的 target，**不得人工发明**。每个候选单独执行，记录：

```text
target
exit_code
executed_targets
executed_tasks
outputs
actual_cl_invocation
actual_link_invocation
environment_difference
```

结果分类：

| 类 | 含义 | 处理 |
| --- | --- | --- |
| **A. INVALID_PROBE** | 如 `MSB4057: target does not exist` | 探针选择错误，**不计入项目失败** |
| **B. VALID_NOOP / EVALUATION_ONLY** | target 存在但只做 evaluation/prepare，无 generation output | 不计为完整 generation |
| **C. GENERATION_PARTIAL** | 确实执行了 generation task，但无法证明全部 prerequisites/output 完成 | `UNKNOWN` |
| **D. GENERATION_COMPLETE_CANDIDATE** | 满足 G-Map 全部 generation targets/prerequisites，产生预期 outputs，且 no-compilation evidence PASS | 才进入 P3 |

## 7. Probe P3 —— `DesignTimeBuild` 语义独立验证

`DesignTimeBuild=true` **不得**作为 generation 语义假设。仅在 P0/P2 已确定存在与
DesignTimeBuild 相关条件时执行。需分别比较 `ordinary_project_evaluation` 与
`DesignTimeBuild=true`，但**比较目标不是「哪个返回 0」**，必须回答：

1. `DesignTimeBuild=true` 实际改变了哪些 target/condition；
2. 哪些 generation targets 被执行；
3. 哪些 targets 被跳过；
4. 输出是否发生；
5. 是否存在 compiler invocation；
6. 这些输出是否属于项目定义的 generation outputs；
7. DesignTimeBuild 是否只是 IDE metadata / evaluation path。

**重要规则**：即使 `/p:DesignTimeBuild=true /t:Build` 返回 0，**也不能**直接判定
generation complete。只有当 `DesignTimeBuild=true` + G-Map 完整 generation chain +
generation outputs complete + no compilation 全部成立时，才可进入 P4。若
DesignTimeBuild 只产生 IDE/evaluation metadata → `GENERATION_NOT_ESTABLISHED`，
而**不是**项目失败。

## 8. Probe P4 —— Generation Output Closure（关键验收）

对 P0 建立的 G-Map 建立 `ExpectedGenerationOutputs`，来源**必须**是当前
`.vcxproj`、imported targets、实际 target outputs 与 MSBuild binlog，**不得凭经验
列举**。对每个 output 验证：

```text
declared/generated
exists
new_or_updated
belongs_to_generation_target
```

并建立 closure：**每一个 generation target 都有对应的实际执行证据；每一个 required
generation output 都有对应的生成证据；不存在未解释的 required generation
target/output。**

### P4 PASS 条件（须同时满足）

1. Generation Target Map 已建立；
2. 所有 required generation targets 已执行；
3. 所有 required generation outputs 已产生；
4. output closure 完整；
5. `cl.exe` 实际 compilation invocation = 0；
6. `link.exe` invocation = 0；
7. `.obj/.lib/.dll` 等 compilation/link outputs 未被本 probe 新生成；
8. binlog 与 filesystem evidence 一致；
9. probe output 与仓库 baseline 隔离；
10. 没有未解释的 generation condition/path divergence。

否则 → `BUILD_GENERATION_UNKNOWN`。

## 9. 「完整 generation」与 shader precompile 的关系

G2 已提供正面证据：shader precompile / evaluation path **可以实际运行**。但本探针
**不得**把 shader precompile 单独升级为完整 generation，只能记为：

```text
GENERATION_COMPONENT_CONFIRMED
```

即「至少一个项目定义的 generation component 已被实际观察」。最终 generation 是否
完整，仍由 G-Map + output closure 决定。

## 10. Probe Result Vocabulary

本探针**不新增 CI 四状态**。探针内部允许：`PASS`、`UNKNOWN`、`INVALID_PROBE`、
`GENERATION_PARTIAL`、`GENERATION_COMPLETE_CANDIDATE`、`BUILD_BLOCKED`。这些是
**探针内部分类**，不是 release gate verdict。

| Probe finding | Governance interpretation |
| --- | --- |
| generation complete + no compilation | evidence established |
| 存在有效 generation path 但完整性未证 | `UNKNOWN` |
| candidate target 无效 | `INVALID_PROBE`；不构成项目失败 |
| 项目阻断所有有效 generation 路线 | `BUILD_BLOCKED` |
| probe 环境妨碍判定 | `UNKNOWN` |
| 意外出现 compiler invocation | probe containment failure；停止并报告，不继续 |

**不得引入 `INVALID_CORPUS_MEMBER` 等新的 gate verdict。**

## 11. Stop Conditions

出现以下任一情况立即停止，**不寻找替代 target 追求绿色**：

1. 实际执行 `cl.exe` compilation；
2. 实际执行 `link.exe`；
3. probe 修改 checkout；
4. generation output 写入仓库；
5. target 需要修改项目文件才能运行；
6. 无法建立 generation boundary；
7. binlog 与 filesystem evidence 相互矛盾；
8. DesignTimeBuild 仅能证明 IDE/evaluation 行为；
9. candidate target 不存在；
10. generation completeness 只能靠「没有看到失败」推断。

停止后保持 `BUILD_GENERATION_UNKNOWN`，除非已建立明确的 `BUILD_BLOCKED` 证据。

## 12. 最小执行阶梯

```text
P0  Read-only Generation Target Map
        ↓
P1  No-Compilation Evidence Boundary
        ↓
P2  Native Generation Target Candidates
        ↓
P3  DesignTimeBuild Semantics
        ↓
P4  Generation Output Closure
```

每级都须有明确验收结果。**不得**：P0 未完成就猜 target；P2 失败后直接改参数；
P3 返回 0 就判 generation；用进程名扫描替代 binlog；用 shader precompile 代替
generation closure；进入 actual build。

## 13. 成功标准

只有以下命题全部被证据支持，才允许将 `BUILD_GENERATION_UNKNOWN` 升级为
`BUILD_GENERATION_ESTABLISHED`：

> 当前 checkout 的 classic `.vcxproj` 存在一个原生 MSBuild generation path；该 path
> 的完整 target dependency chain 已由项目定义和实际 binlog 建立；所有 required
> generation targets 均实际执行；所有 required generation outputs 均实际产生；同
> 时整个过程没有发生任何 C++ compilation 或 linking。

任何一项不能证明 → **保持 UNKNOWN**。这不是失败，而是探针没有获得足够证据。

## 14. 与后续 Scheme B 的边界

即使 P4 成功，也只证明 **Build-generation feasibility established without C++
compilation.** 它**不**证明：RenderDoc 可以完整编译；`renderdoc.dll` 可生成；事故
DLL 可被重建；crash 可复现；fault address 可迁移；attribution 可建立；upstream
responsibility 可建立；teardown defect 已修复。

**P4 PASS 后仍必须重新授权 actual build。**

## 15. 本定义执行前的预期状态

```text
source relation              = ESTABLISHED
delta provenance             = SOLIDIFIED
CMake route                  = BUILD_BLOCKED
MSBuild solution loading     = PASS
MSBuild project evaluation   = PASS
shader precompile/evaluation= PASS
MSBuild generation           = UNKNOWN
actual build                 = NOT AUTHORIZED
reproduction                 = NOT AUTHORIZED
attribution                  = NOT AUTHORIZED
```

**本定义本身不得改变上述状态。** 它只定义下一次允许的证据收集边界。