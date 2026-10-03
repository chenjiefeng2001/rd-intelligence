---
document_role: contract
freshness_policy: living
document_living_note: >-
  本文档只承载已裁决的 fixture population 定义与边界。未决项留在
  docs/OPEN-DECISIONS.md，不在此就地改写；若某项获得裁决，其规则写在此处。
---

# FIXTURE POPULATION CONTRACT

## 1. 本文档不做的事

不做技术工作，不裁决未决项，**不修改** `CAPTURE-CORPUS-CONTRACT.md`。
未决项留在 `docs/OPEN-DECISIONS.md`；本文档只承载已裁决的部分。

## 2. 已裁决：population 定义（N4，选项 A）

> `rd-intelligence` 仓库自生成的参数化 replay fixtures，属于
> `CAPTURE-CORPUS-CONTRACT` 范围外的**独立 fixture population**。

事实依据（实测，非推断）：

- `scripts/workload_corpus.py` 从 `tests/integration/fixtures/triangle_app.cpp`
  按 `DRAWS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 10000, 20000]`
  每档生成一个 `.rdc`；与 `tests/workload/corpus/` 中 14 个文件
  （`w00001`…`w20000`）的数量与命名**逐一对应**。
- 生成需要真实 GPU replay（`renderdoccmd.exe` + `RDOC_DLL` + MSVC 工具链），
  在缺少该栈的机器上**不可复现** —— 这是这些文件 untracked 却存在于工作树的原因。
- 来源是仓库内 fixture 与生成脚本，**不是** external capture acquisition。

## 3. 本裁决明确不做的事

- **不修改** `CAPTURE-CORPUS-CONTRACT.md` 对 external corpus population 的定义。
- **不**把 redistribution / provenance 义务加到这 14 个自生成 fixture。
- **不**把这 14 个文件声明为 tracked corpus。
- **不影响** N3 external corpus（Vulkan / D3D12 真实应用 capture，另有独立
  provenance 记录）。
- **不**由 `CAPTURE-CORPUS-CONTRACT.md` §6 推出它们必须被 track。

## 4. 已授权但未实施：确定性与完整性

**授权范围**：可以为该 fixture population 定义确定性 / 完整性规则。
**尚未实施** —— 作为独立验证项保留，见 §6。

## 5. 未裁决：门禁消费的 capture 输入身份

### 5.1 证据问题（已界定）

> 在不改变现有 fixture population 定义和门禁语义的前提下，确定如何保证门禁
> 实际消费的 `.rdc` **只能来自已声明的 fixture population**，而不能被目录中的
> 任意未声明 `.rdc`（或指向别处的路径）注入改变。

### 5.2 实测的消费者拓扑 —— 风险落在哪一条

三种消费者取输入的方式不同，**只有第一种影响门禁裁决**：

| 消费者 | 取输入方式 | 是否影响门禁裁决 |
| --- | --- | --- |
| `integration` 门禁 | env `RDEBUG_INTEGRATION_CAPTURE` **单条路径**；`release_gate.check_requires` 只校验 `os.path.isfile` | **是** |
| readiness 探针 | glob `tests/workload/corpus/*.rdc`（`_probe_corpus`） | 否 —— `capability only, nothing executed; not a gate verdict` |
| workload suite | glob，且**空则自动调用** `scripts/workload_corpus.py` 生成（`workload_run.py:18-22`） | 否 —— workload 纳入 gate 已 RULED AGAINST |

因此对**门禁裁决**的注入面是 env 提供的**单条路径**：其成员资格与内容**均无约束**，
且路径可指向 corpus 目录之外。14 文件 glob 影响的是 readiness 报告与 workload 运行，
不是门禁裁决。**约束必须区分这两条面，否则会修错对象。**

### 5.3 约束（本轮不实现、不选择）

1. **不得修改** `CAPTURE-CORPUS-CONTRACT` 的 external corpus 定义。
2. **不得**把 14 个 fixture 转成 tracked corpus。
3. **不得**改变四状态裁决或 release-gate 优先级。
4. **不得**通过删除或禁用门禁来消除问题。
5. **不得**接受「文件存在即可」作为身份验证。
6. 必须区分四件事：fixture **是否存在**；fixture **是否属于声明 population**；
   fixture **内容是否与声明身份一致**；**缺失 / 替换 / 额外 `.rdc`** 时门禁应如何裁决。
7. 候选实现可以比较，但**本轮不选、不改代码**：固定 filename + SHA-256；
   fixture manifest；生成脚本作为唯一 producer；discovery 只接受 producer 声明的集合；
   producer-side identity check。
8. 必须覆盖至少三个**负向**情况：删除一个声明 fixture；替换一个 fixture；
   增加一个未声明 `.rdc`。
9. 需要一个**正向控制**：当前合法 14-file population 必须继续被正确发现。
10. 若某方案改变了「缺 capture 时是 `UNKNOWN` / `INFRA` / 其他」的门禁语义，
    **必须拆成另一个治理决策**，不得偷偷包含在 identity 修复里。

### 5.4 后续顺序

证据问题 / 约束清单（本节）→ 方案比较 → 明确授权 → 最小实现 → 负向 / 正向控制
→ real pipeline 验证 → milestone refresh / freeze。

当前**不需要**重跑 pipeline。

## 6. 方案比较（两层拆分；不选、不实现）

### 6.1 五个问题的当前答案

| 问题 | 当前可陈述的答案 |
| --- | --- |
| **1 Membership** —— 14 个 fixture 的声明集合由什么定义？ | **目前没有任何定义**。`check_requires` 只做 `os.path.isfile`；producer 的声明与其写出的名字不一致（§6.5）。候选来源见 §6.3 |
| **2 Content identity** —— 是否要求内容级身份？ | **未裁决**。若要，只能是 SHA-256 / size / 其他 fingerprint，或**明确裁决不做内容验证** |
| **3 Determinism dependency** —— 哪些方案必须先完成确定性验证？ | 只有进入 Layer B 的方案（filename+SHA-256、含hash 的 manifest）。**Layer A 的方案不需要** |
| **4 Failure semantics** —— 缺失 / 替换 / 额外 capture 分别是什么证据状态？ | **未裁决**，且**必须拆出**（§6.6） |
| **5 Integration boundary** —— 最终约束落在哪个消费者？ | **`RDEBUG_INTEGRATION_CAPTURE → check_requires → isfile` 这条单路径**。readiness 的 glob 与 workload 的 glob+auto-generate **不是** gate identity enforcement 的入口，只能作旁路一致性检查 |

### 6.2 两层拆分

- **Layer A —— 成员资格**：哪些路径/文件**有资格**成为 integration gate 的 capture。
  候选：producer 声明的 14 档 DRAWS；固定 filename 集合；manifest 中的路径集合；
  其他 producer-side declaration。**不一定需要先知道 SHA-256。**
- **Layer B —— 内容身份**：已声明的某个 fixture，其**实际内容**是否就是声明的 fixture。
  只有这一层进入 SHA-256 / size / 其他 fingerprint，或「不做内容身份验证」的明确裁决。

### 6.3 依赖矩阵（「能处理」仅表示技术覆盖能力，非优劣排名）

| 方案 | Layer A 成员资格 | Layer B 内容身份 | 依赖确定性验证 | 能处理替换 | 能处理额外文件 |
| --- | --- | --- | --- | --- | --- |
| producer declaration（`DRAWS`） | ✓ —— 缺陷已修，producer 现在是权威声明来源（§6.5-1） | ✗ | 否 | 部分 / 需定义 | ✓ |
| filename set | ✓ | ✗ | 否 | ✗ | ✓ |
| filename + SHA-256 | ✓ | ✓ | **是** | ✓ | ✓ |
| manifest | 取决于 manifest schema | 取决于是否含 hash | **若含 hash，则是** | 可 | 可 |
| producer-side check | 取决于具体实现 | 取决于具体实现 | 未定 | 未定 | 未定 |

Layer A 的三个方案都**不覆盖内容替换**，因此在约束 6 的四项区分下，它们最多满足
前两项（存在、属于声明 population），第三项（内容与声明一致）与第四项（替换时应如何
裁决）仍需 Layer B 或另行裁决。

### 6.4 依赖方向（只能单向）

```
fixture deterministic verification
  → （若选择 hash / content identity）
  → 才能冻结 content identity
```

**不能反推**：不能因为「某个方案需要 hash」就断定「确定性验证已被裁决」。
`fixture 确定性 / 完整性验证` 仍是独立 OPEN 项；**Layer A 的选择不依赖它**。

### 6.5 三项实测前置缺陷 —— 两项已修，一项仍开放

1. **producer 的声明与写出不一致 —— 已修。** `workload_corpus.py:61-62` 曾以
   `w{draws:05d}_frame11.rdc` 判存在，而 `:68` 写出 `w{draws:05d}.rdc`，
   docstring 亦写后者；**旧代码运行时会因文件已存在而全部跳过，输出
   `corpus ready: 14`，却从未产出其声明的名字**，故 producer 当时不是权威声明
   来源。现引入单一 `canonical_name(draws) = w{draws:05d}_frame11.rdc`，
   存在性检查、日志、计数与文档全部使用它；生成后若 canonical 文件未出现即
   `SystemExit`，不再以循环计数器冒充 population 数量。
   canonical 取带 `_frame11` 的名称，依据是该名称被 README、DESIGN_SPEC、
   D4-EVIDENCE、F12、GATE3 与多份 freeze 记录引用；app 接收
   `w00001.rdc` 作为 stem 后自行产出 `_frame11` 文件。
2. **producer 内部的宽前缀注入面 —— 已修。** 原 `:72` 的 `w{draws:05d}*.rdc`
   会把 `w00001_evil.rdc` 计为该档；现为精确文件名判断，并有负向控制覆盖。
   **注意这只消除了 producer 自身的错误成员发现，并不表示 drop-in gate 漏洞
   已解决** —— integration gate 消费的是 env 单路径，与 producer 是不同消费者。
3. **仓库内唯一的 sha256 验证覆盖的是另一个 population —— 仍开放，独立项。**
   `_probe_corpus` 统计 `tests/workload/corpus/*.rdc`，但其 `manifest_match`
   校验的是 `N3-05A-freeze-manifest.json` 中的 `n3-corpus/captures/*` 与 reports
   —— 即**门禁不消费的那批 capture**。本轮**未**修复或重定义该错位。

另有已记录但**不在本轮范围**的观察：`tests/workload/harness.py` 的
`discover_corpus()` 同样以 `glob("*.rdc")` 加 `w(\d+)` 正则匹配 stem，因此也接受
`w00001_evil.rdc`。它是 workload runner 的消费者，**不是门禁裁决入口**，本轮
未改动。

### 6.6 failure semantics 必须拆出

缺失 / 替换 / 额外 `.rdc` 各自对应什么证据状态，**不是 identity 修复的一部分**。
若任一方案会改变 `UNKNOWN` / `INFRASTRUCTURE_FAILURE` / `REGRESSION` 的归类，
按约束 10 **必须另立治理决策并单独授权**，不得隐含在 identity 修复内。

## 7. Layer A 可行性对比（producer 修复后；不选、不实现）

### 7.1 强制点的两个既有机制（实测）

权威 gate spec 是 **`release-gates.json`**（`ci-pipeline.json` 的
`environment_requirements` 只是描述性文档）。其中存在**两条**输入通道：

| 通道 | 机制 | 现状覆盖 |
| --- | --- | --- |
| **spec 声明通道** | `release-gates.json` 顶层 `captures`（gate id → capture 路径），由 `release_gate.py:146-150` 的 `_substitute_capture` 把命令中的字面占位符 **`CAPTURE_PLACEHOLDER`** 替换为该路径（无条目则返回 `None`） | **仅 `cold_warm_equivalence` 有条目**：`tests/workload/corpus/w00001_frame11.rdc`。`integration` **无条目**，且其命令不含该占位符 |
| **env 通道** | `RDEBUG_INTEGRATION_CAPTURE`，经 `check_requires` 的 `capture` 分支（`:123-126`）校验 `os.path.isfile` | `integration` 的**唯一**输入路径；`cold_warm` 的前置检查也读这个变量 |

两点实测结论：

- `requires.capture = true` 在两个门上都在，因此 **`isfile` 检查是活的**；不存在的
  路径会被判为缺失前置。
- `cold_warm` 的**前置检查**读 `RDEBUG_INTEGRATION_CAPTURE`，而它**实际执行**的
  命令用的是 spec `captures` 里那条路径。二者可以不一致。
- spec 里那条路径是 `w00001_frame11.rdc` —— **canonical 命名的独立旁证**。
- 两条通道的**机制不同**：`integration` 的命令是
  `python -m unittest discover -s tests/integration -t .`，不含占位符，其 capture
  由四个测试模块（`test_context_eid_contract`、`test_real_replay`、
  `test_reflection_reachability`、`test_runtime_isolation`）各自读
  `RDEBUG_INTEGRATION_CAPTURE`；`cold_warm_equivalence` 的命令是
  `python scripts/cold_warm_gate.py CAPTURE_PLACEHOLDER --json ...`，capture
  作为 argv 传入。
- `spec_captures` **只**用于 `_substitute_capture` 与其调用点，**没有任何地方**
  把 spec 的 capture 与 producer 的 population 交叉校验。

### 7.2 可行性对比（不选）

| 方案 | population source | 成员资格 | 内容一致性 | 依赖 deterministic verification | 需触及的机制 |
| --- | --- | --- | --- | --- | --- |
| **Producer declaration** | producer 声明的 14 个 canonical names（已权威，`§6.5-1`） | 精确名称 | **不解决** | 无 | 需把 producer 的声明引入强制点；gate 进程需能取到该集合 |
| **Filename set** | 冻结的 14 名称集合 | 精确名称集合 | **不解决** | 无 | 与上同，另需一份独立冻结副本（与 producer 存在漂移风险） |
| **Filename + SHA** | 名称 + 内容 identity | 名称与 hash 双重匹配 | **部分进入 Layer B** | **有** | 同上 + 内容校验 |
| **Manifest** | manifest 定义成员及 identity | manifest membership | 取决于 schema | 若含 hash，则有 | 新增 manifest 载体 + 强制点消费 |
| **Producer-side check** | producer 自证 population 完整 | producer assertion | **不解决** | 取决于证明内容 | producer 输出需被 gate 信任并传递 |

按约束 6 的四项区分：Layer A 各方案最多满足**存在**与**属于声明 population**，
**不得**被表述为满足「内容与声明一致」。

### 7.3 关键可行性结论：Layer A 无法完全脱离 failure semantics

每个方案一旦在强制点实施，都会遇到同一个岔路口：**当提供的路径不属于声明
population 时，门禁应如何裁决**。无论把它记作缺失前置（→ 现有语义给出
`INFRASTRUCTURE_FAILURE`）还是新增一种前置种类，**都是在改变可观测的裁决
行为**。按约束 10，这必须拆成独立治理决策。

因此可分离的范围是：

- **正向情形**（提供的是声明内的 canonical fixture）：任何 Layer A 方案都**不需要**
  语义变更即可通过。
- **负向情形**（额外、替换、非 population 路径）：**必然**触及 failure semantics，
  必须另行授权，不得隐含在 identity 修复内。

### 7.4 两个门的可行性不对称

`cold_warm_equivalence` 已有 spec 声明通道，其条目是**单个硬编码路径**——它选中
population 的一个成员，却**没有断言成员资格或 population 完整性**。`integration`
则完全没有声明通道，输入只能来自 env。

因此「用哪一种 population source」对两个门不是同一个问题；若只对
`integration` 实施，`cold_warm` 的声明仍是单点选择而非 population 定义。

### 7.5 本节不做的事

不选方案、不改代码、不改 `release_gate.py` / `check_requires`、不改 spec、不改四状态
语义与优先级、不动 `manifest_match`、不把 readiness / workload 的 glob 当作强制点。
`manifest_match` 的 population 错位仍是独立 OPEN 项，不在本节处理。

## 8. Step C —— 适用范围决策（decision-ready，不选、不改 gate 行为）

本节只回答一个问题：**Layer A 的 population governance 适用于哪些门。**
不选择 producer / SHA / manifest，不决定负向裁决，不改任何 gate 行为。

### 8.1 已确立的、不再重复的事实

- 权威 spec 是 `release-gates.json`；`ci-pipeline.json` 的
  `environment_requirements` 只是描述性文档。
- `cold_warm_equivalence` 有静态 capture 声明，但它只是**一个具体 fixture 路径**，
  **不是 population 声明**——它选中一个成员，未断言成员资格或 population 完整性。
- `integration` **没有** declaration channel，输入只能来自 `RDEBUG_INTEGRATION_CAPTURE`。
- 两者**不能**共享同一个「Layer A 已存在 / 未存在」的结论。
- `requires.capture = true` 的 `isfile` 前置检查**有效**；此前「不存在路径可能漏检」
  的疑虑**已关闭**。
- `cold_warm` 的前置检查路径与实际执行路径**可以不一致**。这是应保留的边界事实，
  **但不能据此推出必须修改**。

### 8.2 三个候选范围

**已裁决：C1 —— 仅 integration。** 理由：只有 integration 存在真实的外部输入
注入口（`RDEBUG_INTEGRATION_CAPTURE` → 测试模块 → gate）；`cold_warm` 的 capture
来自 spec 固定 argv，其「前置检查路径 ≠ 实际执行路径」的一致性问题**不是**当前
Layer A 要解决的外部 population 注入问题；C2 会把两种不同机制强行纳入同一
population governance；C3 会增加第二份 membership 定义并扩大已有分歧面。

**保留的已知缺口（不由 Layer A 顺带修复或重新定义）**：`cold_warm` 的 spec capture
仍是**单点选择**，其前置检查路径与实际执行路径可能不一致。

| 范围 | 做法 | 后果 |
| --- | --- | --- |
| **C1 仅 integration** | 只为 `integration` 建立 population 定义与成员资格 | 直接覆盖当前唯一真正存在的 env 注入入口。`cold_warm` 的单点声明保持原样，其「选一成员」性质**不被解决**，成为已记录的已知缺口 |
| **C2 两个门统一** | `integration` 与 `cold_warm` 纳入**同一** population 定义 | 定义唯一、一致；但两门**机制不同**（env vs `CAPTURE_PLACEHOLDER`），统一的是 population 而非输入机制；改动面同时覆盖两门，风险与授权范围都更大 |
| **C3 两个门分别治理** | 各自保留输入机制，membership 分别定义 | 尊重机制差异；但可能产生**两份 membership 定义**，而 `cold_warm` 的前置路径与执行路径已经可能不一致 —— 再加一份定义会扩大而非收敛分歧面 |

### 8.3 该决策不能单独决定什么

- **不能**决定 population source（producer declaration / filename set / manifest）——
  那是 Layer A 的下一步，且与范围决策正交。
- **不能**决定负向情形裁决。按 `§7.3`，这必然触及 failure semantics，属 **Step S**，
  须独立授权。
- **不能**借范围决策顺带修 `manifest_match` 错位或 `harness.discover_corpus` 的 glob。

### 8.4 与后续步骤的关系

```
C（适用范围，本节）
  → S（failure semantics 归属：extra / replacement / non-population path）
    → A（Layer A 实施）
```

顺序不可颠倒：先写 membership check 再被迫反向定义其 failure semantics，正是
需要避免的路径。

## 9. Step S —— 负向情形裁决归属（decision-ready，不选）

范围已定为 **integration only（Step C / C1）**。本节只决定：**当 integration
提供的 capture 不属于已声明 population 时，落在四状态中的哪一个裁决，以及该裁决
如何进入现有 precedence。** 不决定 producer / SHA / manifest / deterministic
verification。

### 9.1 已冻结的前提（不重复论证）

| 状态 | 定义（`release-gates.json` `classification`） | exit |
| --- | --- | ---: |
| `PASS` | checks executed and all of them passed | 0 |
| `REGRESSION` | checks executed and at least one found a content difference | 2 |
| `UNKNOWN` | the gate could not form a content conclusion; not a pass, needs a human | 4 |
| `INFRASTRUCTURE_FAILURE` | the gate itself could not execute; blocks, and is never reported as a regression | 3 |

precedence 实测为 `REGRESSION > INFRASTRUCTURE_FAILURE > UNKNOWN`
（`release_gate.py:523-528`）。缺失前置的既有路径是 `check_requires` →
`missing` → 记录 `executed=0, missing_prerequisites=[...]`（`:232,236`）→ 门禁不执行。

### 9.2 四类情形，及其真实可检测性

对 integration 而言，注入口是**路径选择**而非目录污染：它只消费一条 env 路径，
所以目录里多放 `.rdc` 对该门**无影响**（只影响 readiness / workload，二者非门禁
裁决）。

| 情形 | 现有行为 | Layer A 能否检出 |
| --- | --- | --- |
| **declared canonical fixture** | 正常路径 | 正向，无需新裁决 |
| **missing** | env 未设 → `env:RDEBUG_INTEGRATION_CAPTURE`；设了但非文件 → `capture:RDEBUG_INTEGRATION_CAPTURE` → `INFRASTRUCTURE_FAILURE`，`executed=0` | 已覆盖，**无需新裁决**（沿用契约 §5：缺失在门禁运行前判定，绝不 → REGRESSION/PASS） |
| **non-population path** | **无任何检查** —— 只要求 `isfile` | **可检出**（需 Layer A） |
| **replacement**（拆两个子类） | 无检查 | R1 改名替换（原文件被换成非 canonical 名）→ 可检出为 missing + non-population；**R2 保留 canonical 名、内容换成另一 capture → Layer A 完全无法检出**，需 Layer B / deterministic verification |

> **诚实边界：在 Layer A 之下，R2 不可检出。** 任何声称「Layer A 解决了替换」的
> 表述都是错的。它只能检出「路径不属于声明集合」。

### 9.3 候选裁决（不选）

| 候选 | 做法 | 后果 |
| --- | --- | --- |
| **S1 归入缺失前置** | 新增一个 reason（如 `capture-not-in-population`），仍走 `INFRASTRUCTURE_FAILURE` | 不新增状态、不改 precedence，符合约束 3；门禁**不执行**，因此未验证的 capture 不会影响任何结果；代价是注入路径与「环境缺失」**同裁决**，只能靠 reason 区分 |
| **S2 判 `UNKNOWN`** | 作为「无法形成内容结论」 | 符合该状态定义，且 exit 4 需人工；但 `INFRA` 优先级更高，而**今天 integration 已是 `INFRA`**（teardown），所以身份信号在 `overall` 里会被掩盖，仅留在门禁行 |
| **S3 判 `REGRESSION`** | 视为强失败 | 与定义冲突（`REGRESSION` 指内容差异，身份违规不是内容差异）；且会因优先级最高而**改变整体裁决效果**；建议排除，但列出以示已考虑 |
| **S4 新增第五状态** | 专用 identity 违规状态 | **违反约束 3**（不得改变四状态裁决与 precedence）；排除 |

### 9.4 判定时点也会影响结果

- **运行前（作为 prerequisite）**：门禁不对未验证的 capture 执行。这与契约 §5
  「缺失在门禁运行前判定」一致，且避免注入的 capture 参与任何判定。
- **运行中（门禁内）**：门禁先对未验证输入执行再报身份问题，等于让被注入的
  capture 实际参与了判定。

该选择与 9.3 正交，但同样属于 Step S。

### 9.5 与约束的兼容性小结

约束 3（不改四状态与 precedence）已排除 S4，并在效果上排除 S3。**S1 与 S2 均在
约束内**，差别在于：是否接受「注入 = 缺失」同裁决，以及是否接受身份信号在当前
`INFRA` 环境下被 `overall` 掩盖。

## 10. Step S —— 冻结裁决

**S1 + 运行前判定。COMPLETE / DECIDED / FROZEN。**

- **S1**：非声明成员路径归入现有 `missing_prerequisites`，最终为
  `INFRASTRUCTURE_FAILURE`。不新增状态、不改变 precedence，也不把身份不合法
  错误定义为内容 `REGRESSION`。
- **运行前判定**：membership 必须在 gate 执行前完成。**非成员 capture 不得进入
  replay / content comparison** —— 否则身份约束只是事后报告，不能保护 gate verdict。
- **reason 字段区分原因**：verdict 统一为 `INFRA`，但 reason 必须能区分
  「环境/文件不存在」与「capture 不属于声明 population」。诊断信息不丢失。
- **S2 排除**：`UNKNOWN` 语义虽可解释「未形成内容结论」，但此处已存在可验证的
  prerequisite 条件；且当前 precedence 下 integration 已有 `INFRA`，`UNKNOWN` 在
  overall verdict 中会被遮蔽。
- **S3 / S4 排除**：S3 会把身份问题错误提升为内容 regression；S4 违反四状态 Contract。

### 10.1 冻结后的边界

| 情形 | Layer A / S1 |
| --- | --- |
| canonical member，内容正常 | 进入 gate |
| canonical member 缺失 | 现有 prerequisite → `INFRA` |
| **非声明成员路径** | **运行前 prerequisite → `INFRA`** |
| canonical 名存在但内容被替换（R2） | **Layer A 无法检测 → OPEN，留给 Layer B** |
| 目录额外 `.rdc` | 对 integration **无影响** |

**S1 不关闭 R2。** 即使 Step A 完成，「保留 canonical 名而替换内容」仍然敞开。

## 11. Step A 前置：population source 决策（decision-ready，不选）

Step A 的实施对象是 integration-only Layer A，但**声明本身的来源尚未裁决**。
实施前必须先选定 source。S1 只决定裁决归属，不决定声明从哪来。

### 11.1 已确立的可行性事实

- `scripts/workload_corpus.py` **可无副作用导入**（实测：导入后 `population()` 返回
  14 个 canonical 路径，无生成动作），因此 producer declaration 在强制点技术上可行。
- 权威 spec `release-gates.json` 当前 `schema = rdebug-release-gates/6`，
  `schema_history` 记录 `/1`–`/6`，且**有活跃控制强制其历史一致性**
  （`tests/unit/test_report_schema.py`，此前正是它发现 release-gates 到了 `/6`
  却只记录到 `/5`）。**因此把声明写进 spec 需要 schema bump + 历史条目。**

### 11.2 候选与两个正交维度

|候选 source | 声明落在哪里 | 与 producer 的漂移风险 | 需触及 spec |
| --- | --- | --- | --- |
| **Producer declaration** | 强制点运行时从 producer 导入 | 无 —— 单一真源 | 否 |
| **Filename set（冻结副本）** | 需另存一份 14 名称 | **有** —— producer 改 `DRAWS` 而副本未改则静默分歧 | 否 |
| **Manifest** | 新增 manifest 载体 | 取决于是否由 producer 生成 | 否（或仅描述性登记） |
| **Producer-side check** | producer 输出被 gate 信任并传递 | 取决于证明内容 | 可能 |

第二维度是**判定强度**：所有 Layer A 方案只覆盖「存在」与「属于声明 population」，
**均不覆盖内容替换（R2）**；后者只由 Layer B / deterministic verification 覆盖。
任何方案都不得被表述为解决 R2。

### 11.3 本节不决定

不决定 source、不实施、不碰 `release_gate.py` / `check_requires`、不改 spec、
不改四状态与 precedence、不碰 `manifest_match` 与 `harness`。R2 与 deterministic
verification 保持 OPEN。

## 12. Step A —— source 裁决、实施与验收

**source 裁决：Producer declaration**（Step A 前置已定）。理由：producer 已有唯一
canonical population，`population()` 可无副作用导入，其命名/成员逻辑刚经 7 项
defect controls、revert-only 与真实 corpus 验证；冻结副本反而需要额外的一致性证明，
否则会与 producer 静默分叉；manifest 会额外引入载体与生命周期问题。

### 12.1 实施范围（严格按冻结边界）

**已做：**

1. `release_gate.check_requires` 的 capture 分支对 `integration` 增加成员判断。
2. `_declared_population()` 从 producer 的 `population()` 取 canonical 名称集合
   （**只算名字，不触碰文件系统**，因此 clean clone 上仍可读）。
3. `_capture_in_declared_population()` 为精确路径判断（`normcase` + `abspath`）。
4. 非成员 → 既有 `INFRASTRUCTURE_FAILURE`，独立 reason
   `capture-not-in-population:RDEBUG_INTEGRATION_CAPTURE`。
5. **生成路径绝不触碰**：producer 经 `_PRODUCER` 只读取用 `population()`，由 tripwire
   控制钉住——门禁不得因前置检查而生成 capture。

**未做（逐条守住）：** 未改四状态与 precedence；未改 `check_requires` 的其他语义；
未改 `cold_warm`；未引入 SHA / manifest / content identity；**未做 R2 检测**；
未做 deterministic verification；未改 `harness` glob；未改 `CAPTURE-CORPUS`；
未改 release blocking。

**额外的 fail-closed 分支**：若声明本身不可读（producer 无法加载），不静默放行，
而是产生独立 reason `capture-population-unavailable:...`，裁决仍为既有
`INFRASTRUCTURE_FAILURE`，未新增状态。

### 12.2 控制与变异

- **11 项控制**，defect-version 下 **8 项先失败**；既有语义类 3 项修复前后均通过。
- **revert-only 3 项变异全部被捕获**：范围扩大到 `cold_warm`、非成员改用既有 absence
  reason、membership 判定恒真。

### 12.3 真实集成验收（两次真实 pipeline 运行）

| 运行 | capture | integration | overall |
| --- | --- | --- | --- |
| 非成员 | `N3-05A1.rdc`（真实文件、population 外） | `INFRASTRUCTURE_FAILURE`、`executed=0`、`missing_prerequisites = ["capture-not-in-population:RDEBUG_INTEGRATION_CAPTURE"]` | `BLOCKED_INFRA / exit 3`；**`cold_warm` 仍 PASS**（未被波及） |
| canonical member | `w00016_frame11.rdc` | `executed=63`、`tests_failed=0`、`OK`、`process_exit_code=3221225477`、`missing_prerequisites` 为空 | `BLOCKED_INFRA / exit 3`、`accounting_consistent=True` |

unit 在带环境下 `PASS 496`。

### 12.4 Step A 关闭了什么、没有关闭什么

**已关闭**：integration 通过 env 路径注入一个非声明 capture 的通道。门禁不再对该
capture 执行。

**仍未关闭**：

- **R2**（保留 canonical 名、内容换成另一 capture）——**Layer A 无法检出**，OPEN，
  留给 Layer B / deterministic verification。
- `cold_warm` 的单点声明与「前置路径 ≠ 执行路径」——记录在案的缺口。
- `manifest_match` 的 population 错位、`harness.discover_corpus` 的 glob —— 独立项。

## 13. 本 population 的未决项

见 `docs/OPEN-DECISIONS.md`：

- fixture 确定性 / 完整性验证 —— 已授权，未实施
- discovery / drop-in 输入身份完整性 —— 目标已定，实现未授权