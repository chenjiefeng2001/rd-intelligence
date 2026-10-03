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

## 6. 本 population 的未决项

见 `docs/OPEN-DECISIONS.md`：

- fixture 确定性 / 完整性验证 —— 已授权，未实施
- discovery / drop-in 输入身份完整性 —— 目标已定，实现未授权