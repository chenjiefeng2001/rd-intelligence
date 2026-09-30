# 冻结点：§2.1 Capture Acquisition Exception Contract

冻结日期：2026-09-29
裁决：**exception 模式（严格限定、可机械验证）**
授权边界：仅 §2.1 修订 + 对照 + 回退验证 + 机械验证 + 冻结

---

## 1. 冻结状态

| 项 | 状态 |
| --- | --- |
| §2.1 fork integrity | **COMPLIANT WITH DECLARED EXCEPTION** |
| §2.1 措辞与受控例外的对账 | **COMPLETE** |
| 机器可读声明 | `rd-intelligence/fork-exception.json` |
| 机械验证器（F1–F4） | `scripts/audit_fork_integrity.py`（exit 0 = PASS） |
| 回归对照 | `tests/unit/test_fork_integrity_audit.py`（**22 项**） |
| 真实 fork 机械验证 | **PASS**（1 tracked modification / 1 declared exception） |
| fork 是否已提交 patch | **未提交**（exception 模式不需要） |
| fork 是否已删除 patch | **未删除**（删除会与冻结 provenance 矛盾） |
| 14 frozen artifacts | **INTACT 14/14**（未改动） |
| N3-05A provenance | **`PASS_WITH_WAIVERS`** —— **不得**简写为 clean PASS |
| A2 §4 automation | **GAP / CONFIRMED WITH OBSERVED CONSEQUENCE**（不变） |
| CI configuration | **NOT AUTHORIZED**（不变） |

---

## 2. §2.1 的七条不可缺条件（全部落为机器可判定）

| # | 条件 | 机械落点 |
| --- | --- | --- |
| 1 | 仅限 capture acquisition tooling | 声明 `category` + `excluded_surfaces`；`_touches_excluded_surface` |
| 2 | 用途必须明确声明 | 声明 `purpose` + `mechanism`；`test_real_declaration_is_wellformed` |
| 3 | 作用面必须可验证 | `files[].allowed_symbols` / `allowed_file_scope`；`_classify_hunk` 按**结构**定位，**注释不构成合规依据** |
| 4 | provenance 必须绑定 | `provenance.metadata_globs` + patch 身份与实际存在性一致（**F3**） |
| 5 | verifier 必须强制 | **F1–F4** 四类一律 FAIL，非零退出码 |
| 6 | 不改变 replay Contract | 声明 `not_a_replay_change`；`excluded_surfaces` 含 replay/driver/serialise |
| 7 | scope 明确、不自动延续 | 声明 `scope_note`：新 patch 必须重新进入同一流程 |

### F1–F4 强制 FAIL 条件

| # | 情形 | 结果 |
| --- | --- | --- |
| F1 | 存在**未声明**的 tracked modification | **FAIL** |
| F2 | 声明存在但工作区**实际不存在**（幽灵声明） | **FAIL** |
| F3 | metadata 未记录 patch / 记录了别的 patch / `patch_recorded != true` / glob 匹配不到 | **FAIL** |
| F4 | 落在允许文件或作用域之外，或触及排除面 | **FAIL** |

---

## 3. 机械验证闭环

```
无 verifier（A1 原始状态）        22 项全部 error（强制不存在）
verifier 存在但 F1–F4 失效         14 项 FAIL ← 关键：证明对照检测的是「不强制」
修复后                            22 项 OK
真实 fork                         PASS, exit 0
```

第二次回退（**verifier 存在但永远 PASS**）比第一次更有价值：
它排除了「对照只是因为文件缺失才失败」的可能，
证明对照真正检测的是**强制力**。

---

## 4. 过程中被对照抓到的三个真实缺陷（全部为我自己的）

| # | 缺陷 | 发现方式 |
| --- | --- | --- |
| 1 | `_classify_hunk` 依赖 `git diff -U0` 的 hunk 上下文，但 **include hunk 的上下文为空** → F4 误判 | 真实 fork 上直接 FAIL |
| 2 | `CONTROL.match(line)` 作用于**未 strip 的行** → 缩进的 `if(` 被误当作 enclosing symbol | 合成 fixture 对照 |
| 3 | 声明的 `metadata_globs: *.json` **过宽** → 匹配到未使用 patch 的 N3-02/N3-03 | **F3 在真实 fork 上抓出** |

第 3 项尤其重要：**F3 不是形式检查，它在真实数据上抓到了我自己的过度声明**，
并已收窄为 `N3-05A*.json`（只有 N3-05A1/A2 使用了该 patch）。

另有 5 处**测试期望错误**被识别并纠正（未 tracked 的新文件不算 tracked
modification；clean tree + 启用声明应触发 F2 而非 SCHEMA；glob/schema override
用法错误等）。**未把错误的测试结论升级成代码缺陷。**

---

## 5. 明确不成立的主张

- ❌「fork 已干净」——**没有**。它有 1 处已声明的 tracked modification。
  `git status --porcelain` 仍**非空**。本冻结**不**宣称该命令为空。
- ❌「已提交 patch」/「已删除 patch」——**两者皆未执行**。
- ❌「删除 patch 是清理」——会与冻结产物的 provenance 声明矛盾。
- ❌「A1 已由 §4.1 解决」——§4.1 是裁决逻辑；A1 需要 §2.1 对账，本冻结即该对账。
- ❌「N3-05A 是 clean PASS」——是 **`PASS_WITH_WAIVERS`**。
- ❌「自动执行已解决」——F1–F4 只在**有人运行时**强制；
  §4 五门仍**无提交时自动执行**（A2 不变）。

### 一个必须说清的残留风险

本次交付的是**可运行的机械检查**，**不是**已接线的自动门禁。
若无人运行 `audit_fork_integrity.py`，它不会阻止任何事。
这与 A2 是**同一个缺口的两个面**：A2 是「§4 五门无自动执行者」，
本次是「新增的 §2.1 检查同样还没有自动执行者」。
**接线仍 NOT AUTHORIZED**，故该残留风险**明确保留、不宣称已解决**。

---

## 6. 本次未做

未提交 fork patch；未删除 patch；未重建 RenderDoc；未重采 capture；
未修改任何 provenance artifact（14/14 仍 MATCH）；未写 CI 配置；
未改 `rd-intelligence/src/**` 任何生产代码；未触碰 §2.9/§2.10/§2.11/§4.1。

取证与验证全程只读 fork（仅 `git status` / `git diff` / `git remote` / `git log`），
合成对照全部在临时目录内建 git 仓库完成。
