# A1 处置 Contract：§2.1 fork integrity

日期：2026-09-29
范围：**仅处置 Contract 与事实矩阵**。**未修 A1，未做 CI 接线，未执行任何方案。**
状态修正依据：只读审计（`ed59113`）确认 A1 为**实际、当前存在**的规范违规。

---

## 1. 事实基线（全部为实测，非文档转述）

### 1.1 违规事实

```
renderdoc$ git status --porcelain --untracked-files=no
 M renderdoc/core/core.cpp            32 insertions(+), 0 deletions(-)
```

`DESIGN_SPEC.md` §2.1：**MUST NOT 任何 tracked modification（fork 永远保持零 diff）**；
条文明文给出的合规验证方式为 `git -C <fork> status --porcelain` **必须为空**。

§4 质量门第 5 条为同一事实。**该门无自动化** → 违规长期未被发现
（见 A2：automation gap **CONFIRMED WITH OBSERVED CONSEQUENCE**）。

### 1.2 fork 的 git 形态（决定「提交」选项的真实含义）

| 项 | 值 |
| --- | --- |
| `origin` | `https://github.com/chenjiefeng2001/renderdoc.git`（个人 fork） |
| `upstream` | `https://github.com/baldurk/renderdoc.git`（上游） |
| branch | `v1.x` |
| HEAD | `b7f1554fe` *Explicitly call parent copy-constructor* |
| commits | 17 267 |

→ 补丁是**上游 `v1.x` 之上的未提交工作区修改**，而非本仓库自有的代码。

### 1.3 补丁的精确作用面

| 项 | 值 |
| --- | --- |
| 文件 | `renderdoc/core/core.cpp`（+32 / -0） |
| 新增 include | `os/os_specific.h` |
| 唯一改动函数 | `RenderDoc::ShouldTriggerCapture` |
| 作用 | `RDOC_TRIGGER_FRAMES="a,b,..."` 在启动时排队 frame 编号采集 |
| 目的 | headless 自动采集，使**未修改的第三方应用**无需 GUI 即可被采集 |
| 是否触及 replay / driver / serialise | **否** —— `git diff --name-only` 未命中任何 replay/driver/serialise 路径 |
| 是否属 §2.1 第二条（禁 AI / 语义图 / MCP / 索引） | **不违反** —— 是采集触发工具，非语义侵入 |

### 1.4 该修改**并非未记录**——N3 采集计划已显式授予并记录

| 证据 | 内容 |
| --- | --- |
| `N3-05A-ACQUISITION-AUDIT.md:151-152` | plan 步骤 9 **明确允许** `core.cpp` 的 `RDOC_TRIGGER_FRAMES` **已声明的** working-tree 修改 |
| 同上 `:223` | `capture_method=renderdoccmd+RDOC_TRIGGER_FRAMES(local-patch)` |
| 同上 `:244-245` | 写入 `capture_rule` / `capture_mechanism` |
| 同上 `:269` | 步骤 9 同时**禁止**修改其他 tracked 文件（patch 是唯一例外） |
| `N3-CAPTURE-ACQUISITION-PLAN.md:136` | 最干净的目标是 `"modifications": []`（零修改），但本采集路径选择了记录例外 |

### 1.5 该修改**已被写入冻结产物内部**

`n3-corpus/metadata/N3-05A1.json`（SHA256 在 freeze manifest 内）：

```json
"capture_method": "renderdoccmd",
"capture_rule": { "trigger_env": "RDOC_TRIGGER_FRAMES=120", ... },
"capture_mechanism": { "type": "renderdoccmd",
                       "patch": "RDOC_TRIGGER_FRAMES",
                       "patch_recorded": true }
```

`n3-corpus/manifest.json:143-144` 声明的断言项包含：

```
"capture_mechanism block present"
"patch_recorded agrees with patch presence"
```

→ 存在 **provenance verifier**（`reports/n3/N3-provenance-verify.json`），
其断言把 **patch 的存在**与**记录**互相校验。

### 1.6 冻结产物构成

| 类别 | 数量 | 验证 |
| --- | --- | --- |
| capture-time `.rdc` | **2**（N3-05A1 / N3-05A2） | 14/14 **MATCH** |
| analysis-time 报告 / 元数据 | **12** | 14/14 **MATCH** |

### 1.7 对既有基线的一项精化（如实记录）

`N3-provenance-verify.json` 的 `gate` 字段并非干净 PASS，而是
**`PASS_WITH_WAIVERS`**，其自带 note 明确写道：

> gate=PASS_WITH_WAIVERS means no unresolved disk/metadata mismatch, but
> some requirements were **ACCEPTED AS GAPS rather than satisfied**.
> It is **not a clean PASS and must not be reported as one**.

（每 capture `passed: 24`、`verdict: "PASS"`，但整体 gate 带 waiver。）

---

## 2. 待裁决的 Contract 问题（**不代为决定**）

> **§2.1 的「zero tracked modification」是绝对 Contract，
> 还是允许「已声明、有界、留痕」的 exception？**

事实层面这已不是开放问题，而是**两份文档未对账**：

| 文档 | 立场 |
| --- | --- |
| `DESIGN_SPEC.md` §2.1 | MUST NOT，**无 exception 条款** |
| N3 采集计划 步骤 9 | **显式授予**该例外，且要求「已声明」 |
| 冻结产物 metadata | **已记录** `patch` 与 `patch_recorded: true` |
| provenance verifier | **机械校验** patch 存在性与记录一致性 |

即：**例外已被三方一致地记录与强制，唯独 §2.1 未被修订以容纳它。**
「A1 是违规」在 §2.1 逐字意义上成立；在**意图**层面它是**已声明的、有界的、
被冻结产物与校验器双重留痕的**采集例外。

**这需要你裁决，本文件不代选。**

---

## 3. 三方案事实矩阵

维度严格限定为你指定的 5 项。

### 方案 A：提交 patch（commit 到 `origin/v1.x`）

| 维度 | 结论 |
| --- | --- |
| 对 §2.1 的影响 | `git status --porcelain` **变为空 → 条文的机械检查通过**；但 fork 将**永久分叉于 `upstream`**，而 §2.1 措辞是「**零 diff**」。**满足字面、违反意图** |
| 对冻结 N3-05A 产物的影响 | 文件 hash 不受影响（14/14 仍 MATCH）。metadata 的 `local-patch` 记录变为与事实更一致 |
| 是否需要重新 capture | **否** |
| 是否改变 RenderDoc runtime binary | **否**（源码早已含该 patch，现有 binary 已包含；提交不触发重建） |
| 是否破坏 reproducibility / provenance | **是（微妙）**。冻结 `.rdc` 头部记录 `renderdoc_version = 1.46 b7f155`。提交后 HEAD ≠ `b7f155`，该记录**不再标识实际使用的源码**。当前「HEAD 恰为 b7f155」反而与 `.rdc` 一致，但代价是 patch 不在 git 中 |

### 方案 B：移除 patch / 改用现有采集机制

| 维度 | 结论 |
| --- | --- |
| 对 §2.1 的影响 | `git status` 空**且**真正零 diff 于 upstream → **字面与意图同时满足**，是唯一完全合规的选项 |
| 对冻结 N3-05A 产物的影响 | **与冻结产物直接矛盾**。metadata 声明 `patch_recorded: true`，`manifest` 断言「`patch_recorded` agrees with **patch presence**」。若移除 patch，该断言**无法成立**；且已物理产生的 2 个 `.rdc` 是 patched binary 的产物，宣告「patch 从未存在」即**证伪冻结产物的 provenance** |
| 是否需要重新 capture | **未来任何 N3 采集都需要**。无 patch 则 `RDOC_TRIGGER_FRAMES` 无效，D3D12 headless 采集路径丧失，需另寻机制。**已有 2 个 `.rdc` 不需重采** |
| 是否改变 RenderDoc runtime binary | **是**。移除 patch 需重建以保持源码/二进制一致；新二进制的 SHA256 将不同于 metadata 记录的 `capture_dll_sha256` |
| 是否破坏 reproducibility / provenance | **是，且是三个方案中最重的**。同时命中三处：冻结 metadata 的声明、verifier 的断言、二进制身份 |

### 方案 C：保留本地 patch，正式登记 exception

| 维度 | 结论 |
| --- | --- |
| 对 §2.1 的影响 | **不满足 §2.1 逐字**（MUST NOT 无 exception 条款）→ 需**修订 §2.1** 以容纳「有界、已声明、仅限采集」的例外。满足意图（无隐藏内容），需改条文以满足字面 |
| 对冻结 N3-05A 产物的影响 | **完全一致** —— 这是**唯一与冻结产物现有声明相符**的方案。**零矛盾** |
| 是否需要重新 capture | **否** |
| 是否改变 RenderDoc runtime binary | **否** |
| 是否破坏 reproducibility / provenance | **否**。patch 已在 N3 计划声明、在冻结 metadata 记录、由 verifier 机械校验 |

---

## 4. 三方案对照小结

| 维度 | A 提交 | B 移除 | C 登记例外 |
| --- | --- | --- | --- |
| §2.1 字面（`git status` 为空） | ✅ | ✅ | ❌ |
| §2.1 意图（真正零 diff 于 upstream） | ❌ | ✅ | ⚠️（需修条文） |
| 与冻结产物一致 | ⚠️ | ❌ **矛盾** | ✅ |
| 需重新 capture | 否 | **是**（未来） | 否 |
| 改 runtime binary | 否 | **是** | 否 |
| 破坏 provenance | **是**（HEAD≠b7f155） | **是（最重）** | 否 |
| 是否需要动代码 | 提交动作 | **改代码 + 重建** | 仅改规范 |

> **注**：方案 C 是**当前实际状态**——N3 侧已完成声明、记录与校验。
> 缺的只是 `DESIGN_SPEC.md` §2.1 未随之修订。
> 即：**A1 的实质是规范对账缺口，不是未受控的代码改动。**

### 你预警的典型错误在本例中**可被机械检出**

> 「为了让 `git status` 变绿，直接删除补丁，然后事后才发现 N3-05A 的冻结语料依赖的是另一个 runtime。」

本例中该错误**不会静默发生**：
冻结 metadata 记录了 `patch` 与 `patch_recorded`，`manifest` 声明
「`patch_recorded` agrees with **patch presence**」，且有 provenance verifier。
删除 patch 会与**冻结产物的哈希覆盖内容**直接冲突。

---

## 5. 状态修正（依裁决）

| 项 | 修正为 |
| --- | --- |
| §2.1 fork integrity | **VIOLATED (A1, observed)** —— 取代「fork intact」的笼统表述 |
| 14 frozen artifacts | **INTACT**（14/14 hash MATCH）—— **不因 A1 而改变** |
| A2 §4 automation gap | **GAP / CONFIRMED WITH OBSERVED CONSEQUENCE** |
| §4.1 CI 裁决 / CI configuration | **DEFINED / FROZEN** / **NOT AUTHORIZED**（不变） |

> **两个概念不得互相覆盖**：
> 「14 冻结物 INTACT」是**文件哈希**事实；
> 「fork 零 tracked diff」是**源码状态**事实，当前**不成立**。

---

## 6. 明确不成立的主张

- ❌ 「A1 是未受控的违规」—— 它由 N3 计划步骤 9 **显式授予并声明**，
  且写入冻结产物 + 由 verifier 机械校验。缺的是 §2.1 的对账。
- ❌ 「删除 patch 是安全清理」—— 会与冻结产物的 provenance 声明矛盾。
- ❌ 「提交 patch 即合规」—— 只满足 `git status` 字面，且永久分叉于 upstream，
  并使 `.rdc` 记录的 `b7f155` 不再标识实际源码。
- ❌ 「A1 可由已冻结的 §4.1 顺带解决」—— §4.1 是**裁决逻辑**，
  A1 需要的是 **§2.1 的规范对账**。

## 7. 本文件未做

未修改 `renderdoc/`；未修改 `rd-intelligence/src/**`；未提交 patch；
未移除 patch；未重建 binary；未改任何冻结产物；未重跑 capture；
未写 CI 配置；**未执行 §3 的任何方案**。

取证方式限于只读：`git status` / `git diff` / `git remote` / `git log`、
冻结 manifest 的 SHA256 校验、冻结 metadata 与 verifier 的 JSON 读取。
