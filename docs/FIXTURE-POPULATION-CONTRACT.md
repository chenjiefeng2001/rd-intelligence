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

## 5. 未裁决：发现通道的输入身份

`tests/workload/corpus/` 目前按 `*.rdc` glob 被发现（`_probe_corpus` 与 workload
harness），而 `workload_corpus.py` 的 docstring 写明 XL 档可「place any `*.rdc`
into the corpus directory and it will be discovered automatically」。

即：**一个自生成 fixture 目录接受任意 `.rdc` 并自动进入门禁 population。**
目标是禁止未声明 capture 通过目录注入改变门禁 population；**实现方式未授权**。

## 6. 本 population 的未决项

见 `docs/OPEN-DECISIONS.md`：

- fixture 确定性 / 完整性验证 —— 已授权，未实施
- discovery / drop-in 输入身份完整性 —— 目标已定，实现未授权