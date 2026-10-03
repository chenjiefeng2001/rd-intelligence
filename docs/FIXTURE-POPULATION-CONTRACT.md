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
| producer declaration（`DRAWS`） | ✓ **但当前声明不成立**（§6.5） | ✗ | 否 | 部分 / 需定义 | ✓ |
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

### 6.5 三项实测前置缺陷（会影响方案可行性）

1. **producer 的声明与写出不一致。** `workload_corpus.py:61-62` 以
   `w{draws:05d}_frame11.rdc` 判存在（与磁盘一致），`:68` 却写出
   `w{draws:05d}.rdc`（无 `_frame11`），docstring 亦写 `w00001.rdc … w20000.rdc`。
   **今天运行它会因文件已存在而全部跳过，输出 `corpus ready: 14`，却从未产出其
   声明的名字。** 故producer 目前**不是**权威声明来源，任何 producer-declaration
   方案都需先修此项。
2. **producer 内部有更弱的注入面。** `:72` 的 `w{draws:05d}*.rdc` 前缀 glob 会把
   `w00001_evil.rdc` 也计为该档capture。
3. **仓库内唯一的 sha256 验证覆盖的是另一个 population。**
   `_probe_corpus` 统计 `tests/workload/corpus/*.rdc`，但其 `manifest_match` 校验的
   是 `N3-05A-freeze-manifest.json` 中的 `n3-corpus/captures/*` 与 reports —— 即
   **门禁不消费的那批 capture**。现有内容验证机制与门禁实际输入不对齐。

### 6.6 failure semantics 必须拆出

缺失 / 替换 / 额外 `.rdc` 各自对应什么证据状态，**不是 identity 修复的一部分**。
若任一方案会改变 `UNKNOWN` / `INFRASTRUCTURE_FAILURE` / `REGRESSION` 的归类，
按约束 10 **必须另立治理决策并单独授权**，不得隐含在 identity 修复内。

## 7. 本 population 的未决项

见 `docs/OPEN-DECISIONS.md`：

- fixture 确定性 / 完整性验证 —— 已授权，未实施
- discovery / drop-in 输入身份完整性 —— 目标已定，实现未授权