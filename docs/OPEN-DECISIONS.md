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

本节只列**尚未裁决**的项。已裁决项移入 §4 并注明其裁决位置，不在此保留 ——
否则一个「待决清单」里大半是已决项，会把下一个读者送去重新推导已经做过的决定。

| 项 | 状态 | 缺什么 |
| --- | --- | --- |
| **Release blocking** | FROZEN / NOT AUTHORIZED | 授权。技术前置是 teardown：required gate 每次通过测试却无法干净退出，会**永久阻断** |
| **RenderDoc attribution（函数级）** | FROZEN / DEFERRED | 该构建的完整非裁剪 PDB，或可符号化的 RenderDoc build。故障**字节**已确立，映射到函数仍需符号 |
| **RenderDoc fork replay 修改** | NOT AUTHORIZED | 若归因落在 replay，需先重开 scope decision |
| **Layer B / R2（内容身份与替换检测）** | OPEN / **阻塞于外部前置条件** | R2 = 保留 canonical 名而替换其内容。Layer A **结构上无法检出**，不得声称已解决。关闭它需要足以证明 O1 重复生成确定性的**外部证据**；本项目当前**不产生**该证据。见 `FIXTURE-POPULATION-CONTRACT.md` §14.9、§14.4 |

### 2.1 N4 的事实基线（2026-10 复核）

**先更正一处已过时的表述。** N4 的未决事项**不是** N3 corpus manifest 的 schema：

- N3 corpus manifest **已存在**：`rdebug-validation/n3-corpus/manifest.json`，`schema: 1`，2026-08-28 冻结。
- 其登记的 4 个 capture 的 manifest / metadata / provenance 状态**已有独立证据**
  （`reports/n3/N3-provenance-verify.json`、`reports/n3/N3-pilot.json`），并带
  `known_issues` 与 `do-not-backfill` 政策。
- 因此 N3 corpus manifest **不是**本文档的 OPEN 项。`CAPTURE-CORPUS-CONTRACT.md` §7
  所说「不在此处授权」指的是该契约自身的 scope（`rd-intelligence` 侧），不是
  「manifest 尚不存在」。

**已决、不再重开：** 本 milestone 是否要求 external corpus → **required**
（`CAPTURE-CORPUS-CONTRACT.md` §4 的 `required / source: external / tracked: false /
provenance_required: true`，以及 G4 裁定）。

**N4 的实际问题：** 以下只有「观察」成立，**归属与定性均不成立**：

- `rd-intelligence/tests/workload/corpus/` 下有 **14 个 `.rdc`**，`git ls-files`
  为 **0**，**无本仓库侧 manifest / sha256 / provenance 登记**。
- 至少一条门禁路径**实际读取**其中 capture（`RDEBUG_INTEGRATION_CAPTURE`）。

`tracked_captures = 0` 与「工作树里存在 14 个 untracked captures」**并不矛盾**：
前者是 Git tracking 的计数，后者是文件存在与门禁依赖的事实。真正未决的是——
**这批未跟踪文件是否属于 `CAPTURE-CORPUS-CONTRACT` 所定义的 corpus population，
当前没有契约规则回答。**

未决且**不推定**：治理归属、来源契约、门禁依赖方式、是否需要本仓库侧
manifest/provenance。

故本项曾作为**治理分类缺口**保持 OPEN。此处只陈述观察，不作定性、不补 manifest、
不补 provenance、不改门禁行为。

**后续**：本节的观察是 §2.3 补充事实的基础，N4 已于裁决中选定**选项 A** 并按
move-out 规则移入 §4，规则落在 `FIXTURE-POPULATION-CONTRACT.md`。本节保留为该裁决
的依据，不因此成为已决项。

### 2.2 `unit` 门禁裁决的环境敏感性

同一份代码、两次真实 pipeline 运行，因环境变量不同而得到不同 `unit` 裁决。
**行为本身已定义且 fail-closed；未裁决的是它是否为期望语义。**

证据问题：在不同 RenderDoc 可用性/环境条件下，unit gate 的
`executed/skipped → gate outcome → overall exit` 是否形成明确、可解释且不会被
误读为 replay 语义结论的行为边界？**本节为取证/决策材料，不含实现。**

#### 2.2.1 现状行为（实测）

| 条件 | executed | skipped | failures | process exit | unit outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| 无 `RDEBUG_RENDERDOC_PATH` | 475 | 3 / 478 | 0 | 0 | **`UNKNOWN`** |
| 有可用 RenderDoc 环境 | 478 | 0 | 0 | 0 | **`PASS`** |

`UNKNOWN` 的 `detail` 原文：`3 of 478 tests skipped; no content conclusion for the
skipped part`。两次运行的 `overall` 均为 `BLOCKED_INFRA / exit 3`。

#### 2.2.2 跳过条件

- 跳过项为 `tests/unit/test_cold_warm_gate.py` 的三项，触发条件是
  `skipTest("renderdoc module not importable")`；同文件另有一处
  `skipTest("capture not present")`。
- 跳过**不会**形成 PASS：`skipped > 0` 落在 `UNKNOWN`
  （`release_gate.py:393-397`），`UNKNOWN ∈ BLOCKING`，而 `PASS` 分支仅在
  `skipped == 0` 时可达（`:398-400`）。
- **不存在「测试未执行但 gate 看起来成功」的路径**（见 2.2.5）。

#### 2.2.3 四状态归约（只记录，不修改）

unittest 类门的判定顺序（`release_gate.py:343-400`）：

| 次序 | 条件 | 裁决 |
| --- | --- | --- |
| 1 | 输出无法解析 | `INFRASTRUCTURE_FAILURE`（`executed=0`） |
| 2 | `executed == 0` | `INFRASTRUCTURE_FAILURE`（"a gate that verified nothing is not a pass"） |
| 3 | `executed < min_executed`（unit 声明 `100`） | `INFRASTRUCTURE_FAILURE` |
| 4 | 发现异常 | `INFRASTRUCTURE_FAILURE` |
| 5 | 有 failures / errors | `REGRESSION` |
| 6 | 非零退出且无 failures | `INFRASTRUCTURE_FAILURE` |
| 7 | **`skipped > 0`** | **`UNKNOWN`** |
| 8 | 其余 | `PASS` |

skip 只会落到 `UNKNOWN`，前提是已执行数 > 0、满足 floor、无发现异常、无内容失败、
干净退出——与实测吻合。

总体 precedence `REGRESSION > INFRASTRUCTURE_FAILURE > UNKNOWN`（`:523-528`），
故 `UNKNOWN → NEEDS_REVIEW / exit 4`。

**已实测**：无环境那次运行中 `unit = UNKNOWN` 与 `integration =
INFRASTRUCTURE_FAILURE` 并存，`overall = exit 3` ——即 **`UNKNOWN` 在 overall 中被
`INFRA` 掩盖**，只留在门禁行。

**仅为推导、未测量**：`unit = UNKNOWN` 且 `integration = PASS` 时 overall 为
`exit 4`。**不得**写成一次真实运行结果。

#### 2.2.4 环境与内容结论的边界

- 「RenderDoc 不可用」只证明**环境/执行能力不足**，不构成任何 semantic 结论。
- **不能**从 skipped 得出 semantic PASS 或 FAIL。
- **不能**把环境敏感性与当前 teardown crash 混为同一故障：后者是 `integration`
  门在 onexit 阶段的 `0xC0000005`，与 unit 的 skip 无关。

#### 2.2.5 完整性风险评估：**未发现**

| 担心的路径 | 源码结论 |
| --- | --- |
| required unit gate 在环境缺失时被误判 PASS | **不可能**：`executed == 0` 在第 2 步即判 `INFRASTRUCTURE_FAILURE`；`skipped > 0` 判 `UNKNOWN`；`PASS` 仅在 `skipped == 0` 且 `executed > 0` 时可达 |
| 门禁行显示 PASS 但实际未执行 | **不可能**（第 2 步先于 PASS 分支） |

因此当前行为是**既有设计行为**，不自动认定为 defect。真正存在的弱点是
**可解释性**：在 `INFRA` 并存时 `UNKNOWN` 在 overall 中被掩盖，只看 overall 的读者
会漏掉身份信号。

#### 2.2.6 决策分支（只比较，不选择）

| 分支 | 做法 | 后果 |
| --- | --- | --- |
| **U1 维持现状 + 文档化** | 把环境 prerequisite 显式写入文档或既有 accounting 措辞，语义零改动 | 不改 gate；可解释性提升；掩盖风险仍在 |
| **U2 把环境 prerequisite 纳入现有 accounting** | 让「因环境不可用而 skip」成为门禁行的一等事实 | 需改报告字段或 detail 措辞；属 accounting 变更，不改四状态 |
| **U3 改变 gate semantics** | 例如把 skip 从 `UNKNOWN` 重新归类 | 会改变四状态归类，属独立授权范围；本轮不比较实施 |

#### 2.2.7 本节不做

不改 `release_gate.py`、不改四状态或 precedence、不改 report schema、不新增 gate、
不改 release blocking、不修 RenderDoc、不改 skip 条件、不把 `UNKNOWN` 强转成
PASS/INFRA、不把 `UNKNOWN` 从 `overall` 中提出。

**后续**：本节材料是 U1 裁决的依据，该项已按 move-out 规则移入 §4。本节保留为证据，
不因此成为未决项。

与 §2 的 N4 项相邻但不同：N4 是 capture 的**治理归属**，本项是**门禁对环境的依赖**。
本仓库无 remote、`ci.yml` 从未执行，故该路径至今未被任何真实 CI 验证。

### 2.3 N4 的新增观测与可裁决选项（2026-10；选项，非裁决）

§2.1 之后补得的事实，改变了这个问题的性质。

**新增观测（均为观察，不含定性）：**

1. 这 14 个 `.rdc` 由**仓库内脚本生成**：`scripts/workload_corpus.py` 从
   `tests/integration/fixtures/triangle_app.cpp` 按
   `DRAWS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 10000, 20000]`
   每档生成一个 —— 与目录中 14 个文件的数量和命名（`w00001`…`w20000`）逐一对应。
2. 生成需要**真实 GPU replay**（`renderdoccmd.exe` + `RDOC_DLL` + MSVC 工具链），
   因此**在缺少该栈的机器上不可复现**。这是它们 untracked 但存在于工作树的原因。
3. **同一目录同时是 drop-in 位置。** 该脚本 docstring 写明：XL 档需要真实游戏
   capture，「place any `*.rdc` into the corpus directory and it will be
   discovered automatically」，而 `_probe_corpus` 与 workload harness 均按
   `*.rdc` glob 发现。**即：外部提供的 capture 放入该目录会被门禁采用，且无
   manifest / sha256 / provenance 校验。**
4. 它们**不是** N3 外部 corpus（那是 Vulkan / D3D12 真实应用 capture，带独立
   provenance 记录）；这里是参数化 triangle 扫描。

因此「这些 capture 是否属于 corpus population」的答案很可能是「否」——但**归属
本身仍需裁决**，不由本节推定。

**可裁决的选项（曾列出；A 已裁决，B / C / D 未采纳）：**

| 选项 | 做法 | 后果 | 状态 |
| --- | --- | --- | --- |
| **A** | 宣布其为 corpus 契约**范围外**的仓库自生成 fixture，并另立规则（按需生成 + gitignore，生成确定性需验证） | 不触碰 §6；需新规则与确定性验证 | **已裁决** |
| **B** | 纳入 corpus 契约作为 declared population | 需**修改契约**（§6 目前禁止把 capture 纳入版本控制），需受限例外 + redistribution 裁决 | 未采纳 |
| **C** | 解除门禁对该目录的依赖，由门禁**自行生成**所需输入 | 需 GPU + 工具链，且是**行为变更**；需授权；生成时间进入门禁 | 未采纳 |
| **D** | 本 milestone **接受现状**，关闭 N4 | 成本最低；但第 3 条 drop-in 通道保留 | 未采纳 |

**已裁决结果**：选 **A**。规则与边界见 `FIXTURE-POPULATION-CONTRACT.md` §2–3；
N4 已按 move-out 规则移入 §4。**注意**：A **不豁免**下面这条 drop-in 通道 —— 它
不接受任何 capture 注入问题，而是把该问题单独立项。

**第 3 条 drop-in 通道已独立成为 OPEN 项**（见 §2 表）：目标是禁止未声明 capture
通过目录注入改变门禁 population，实现方式未授权。该通道与
`CAPTURE-CORPUS-CONTRACT.md` §6「替换 capture 使门禁运行，让缺失变得不可见」的
张力，正是它必须单独裁决的原因。

**未裁决，且不由本节合并**：把「已提供的外部 corpus 只能被计数、无法被验证」
（`AUDIT-2026-10-02-B.md` §257）单独立项，还是并入其他范围。

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
| N4 fixture population 归属 | 选项 **A** — `tests/workload/corpus/` 下 14 个 capture 定为**仓库自生成的参数化 replay fixtures**，属 corpus-contract 范围外的独立 fixture population；不改 external corpus 定义、不加 redistribution/provenance、不声明为 tracked。`FIXTURE-POPULATION-CONTRACT.md` §2–3 |
| fixture drop-in 输入身份（Layer A 部分） | 已关闭 — 范围 **C1 仅 integration**、裁决 **S1 pre-run INFRA**、source **producer declaration**。`integration` 只接受 producer 声明的 canonical 路径；非成员在运行前归入既有 `INFRASTRUCTURE_FAILURE` 并带独立 reason。`FIXTURE-POPULATION-CONTRACT.md` §8–13 |
| fixture 确定性 / 完整性验证 | **EXTERNAL PREREQUISITE / NOT ESTABLISHED / NOT IMPLEMENTED** — 本项目**不具备**该能力且**不产生**该证据；关闭 R2 / 实施 Layer B 前必须先由外部提供足以证明 O1 重复生成确定性的证据。`FIXTURE-POPULATION-CONTRACT.md` §14.9 |
| `unit` 门禁裁决的环境敏感性 | **DOCUMENTED / VERIFIED INVARIANT / FROZEN** — 裁决 **U1：维持现状 + 文档化**。实测与源码均证明 `executed == 0`、低于 `min_executed`、`skipped > 0` 均**不可能**产生 `PASS`，属既有设计行为而非 defect。环境 prerequisite 已写入 `CI-ORCHESTRATION-CONTRACT.md` §6.1；三条不变量由 §6.2 与真实 unittest 运行（非 mock）回归钉住。`overall` 中 `UNKNOWN` 被更高优先级 `INFRA` 掩盖，记为**已知可解释性边界**，非当前 defect。证据材料见本文档 §2.2 |

## 5. 已冻结项（不在本文档内裁决）

`Lint execution`（`2c6079e`）、
`Schema-history preservation`、
`Real report artifact production`、
`Report schema ownership`（`2bb188e`，未冻结但已验证）。
