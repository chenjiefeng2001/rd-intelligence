# 冻结点：CI pipeline integration Phase 1

冻结日期：2026-09-29
冻结点 commit：`0d66fa6`（68 commits）
裁决：**暂不进入 release-blocking 接线**

## 冻结状态

| 项 | 状态 |
| --- | --- |
| CI verdict orchestration | **COMPLETE / VERIFIED** |
| G1 / G2 | **COMPLETE / VERIFIED** |
| Gate 3 | **IMPLEMENTED / VERIFIED / bounded coverage** |
| Pipeline Phase 1 | **COMPLETE / FROZEN** |
| Gate 4 | **PROCESS_ONLY / UNKNOWN** |
| release blocking | **NOT AUTHORIZED** |
| runner environment | **NOT ESTABLISHED** |
| capture distribution | **NOT ESTABLISHED** |

## 冻结时的实测状态

```
executable gates:
  unit                    PASS   executed=251
  transport               PASS   executed=58
  integration             PASS   executed=63
  boundary_audit          PASS
  cold_warm_equivalence   PASS
  fork_integrity          PASS

process-only:
  benchmark_archive       UNKNOWN  (PROCESS_ONLY, attempted=False, command=None)

overall:
  NEEDS_REVIEW / exit 4 / conclusion neutral
```

> **本阶段最重要的成果不是「CI 绿」，而是已经证明：
> CI 在不能验证时会诚实地拒绝给绿。**
> 该性质必须保持。

## 为什么 release blocking 现在无意义

不是因为 pipeline 未完成，而是**两个前置条件未满足**，它们会改变
「阻断是否有意义」：

### 1. 执行环境 Contract 未闭合

| 缺失项 | 后果 |
| --- | --- |
| 全新 clone 无 capture corpus（`tests/workload/corpus/` 被 gitignore，**仓库内 0 个 tracked `.rdc`**） | 两个 replay 门无法运行 |
| runner 无 GPU / 无 RenderDoc 模块 | 同上 |
| 无 sibling `../renderdoc` checkout | `fork_integrity` 无法运行 |
| —— 全部缺失时 | 正确状态是 **`INFRASTRUCTURE_FAILURE`** |

> 在此状态下开启 blocking，会把**「无法执行验证」**与
> **「验证发现问题」**混为同一个构建阻断原因。
> 这正是 G1/G2 刚建立、Phase 1 刚证明不可混淆的那条边界。

### 2. 没有可验证的 release boundary

- **仓库无 git remote**；
- 没有已定义的托管 runner 环境；
- `.github/workflows/ci.yml` 若现在加入，只能**声明一个未来环境**，
  而不是证明当前存在可运行的 release gate。

## 两个新发现（登记，不在本批处理）

### 发现 1 —— integration shutdown `0xC0000005` → **单独 defect / triage**

integration 套件在 **63 tests 全 OK 之后**，解释器 shutdown 时
`0xC0000005`（access violation），进程退出码非零。

- **在已提交状态上同样复现** → **既有问题，非本次引入**；
- **不得**通过修改 pipeline 去掩盖；
- 它是 pipeline 正确捕获边界之后的**新输入**：

> 一个「测试报告 PASS 但 process exit 非零」的情况**不能被当作 PASS**。

这是当前 pipeline 已证明的性质（`INFRASTRUCTURE` 判定覆盖了
「exit 与 verdict 不一致」）在真实套件上的具体体现。
**处置需单独授权的 triage workstream。**

### 发现 2 —— self-recursive pipeline invocation → **保持现状**

已具备防护，**不扩大**：

| 防护 | 内容 |
| --- | --- |
| 显式 opt-in | 端到端测试需 `RDEBUG_RUN_PIPELINE_E2E=1` |
| 环境隔离 | 居于 `tests/pipeline/`，**任何门都不发现** |
| 回退控制 | 编排器在 spawn **之前**设 `RDEBUG_GATE_RUN` |
| 结构性对照 | 「entry 不得指向自身」「标记必须在 spawn 之前设置」 |

> 两次同类失败（entry 自引用递归至超时；测试重入导致 0xC0000005）
> **外观完全一样：超时且无结果**。因此两条对照都保留。

## 下一个允许进入的方向（**均未授权**）

| 选项 | 内容 | 备注 |
| --- | --- | --- |
| **A. Pipeline Readiness Contract**（推荐） | runner 需要什么（GPU / RenderDoc / capture corpus / fork 位置 / Python runtime）；缺失时必须输出 `BLOCKED_INFRA` + **缺失资源列表**，且**不得**输出 regression。**不创建 workflow，不接 blocking** | 直接对应上面两个未闭合的前置条件 |
| **B. Gate 4 Contract** | 定义「什么叫 archive exists」「什么叫 benchmark executed」「benchmark 是否永远不作为 correctness gate」 | **不得**为得到 exit 0 而强行实现 |
| **C. Gate 3 剩余 coverage** | `max_draws` truncation、N3-03 ExecuteIndirect、F-N3-1、D7 | 属 coverage expansion，**不阻塞** pipeline readiness |
| **D. nested-action capture** | `context_eid` 真实 false-positive 对照证据 | 保持独立，**不与 CI 混合** |

## 本次冻结**不**授权

```
release blocking 接线            NOT AUTHORIZED
创建 / 启用任何 workflow         NOT AUTHORIZED
实现 Gate 4                       NOT AUTHORIZED
用 benchmark / process evidence 充当 Gate 4 的 PASS   NOT AUTHORIZED
补 Gate 3 coverage 以推进 CI     NOT AUTHORIZED（属 C，非阻塞项）
nested-action capture acquisition NOT AUTHORIZED
修改 pipeline 以掩盖 0xC0000005   NOT AUTHORIZED（须单独 triage）
扩大 self-recursion 防护范围      NOT AUTHORIZED
修改 §4.1 / §2.9 / §2.10 / §2.11  NOT AUTHORIZED
```

## Phase 1 交付物（冻结时在位）

| 组件 | 位置 |
| --- | --- |
| pipeline 声明 | `ci-pipeline.json`（forge-neutral，含环境要求与结论映射） |
| pipeline 适配器 | `scripts/ci_pipeline.py` |
| 门禁声明 | `release-gates.json`（schema /4） |
| 编排器 | `scripts/release_gate.py`（I1/I2 + G1/G2 + `verdict_json`） |
| Gate 3 检查 | `scripts/cold_warm_gate.py` |
| 对照 | `tests/unit/test_ci_pipeline.py`（26）、`test_release_gate.py`（44）、`test_cold_warm_gate.py`（29） |
| 端到端 | `tests/pipeline/test_pipeline_e2e.py`（opt-in，不被任何门发现） |
| 具体 workflow 声明 | `.github/workflows/ci.yml`（**可审计的声明，非可运行的 pipeline**） |

门禁（冻结时）：unit 251 / transport 58 / integration 63 /
boundary 18/18 + 1 deviation / fork audit PASS / ruff clean /
冻结物 14/14 MATCH / 工作树 clean。
