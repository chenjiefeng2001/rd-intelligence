# rd-intelligence

RenderDoc 的**外部调试智能层**：RenderDoc 负责事实（capture / replay / pixel history），本项目负责理解事实（查询 / 局部依赖图 / 证据输出）。第一阶段不含 AI、不建数据库、不修改 RDC 格式。

> **当前状态（2026-09-29 核对并修复）**
> - Phase 1a → 5d 全部完成，每阶段有 `docs/validation/` 下的验证报告与原始数据。
> - **唯一开放的 roadmap 项是 Real-world Validation（A/B/C），尚未开始**，且其前置条件（≥1 周真实负载遥测）尚不满足。
> - 系统性排查「失败被伪装成结果」类缺陷，**共修复 20 项**并全部提交入库。
>   其中最严重的一项（`GetAllUsedDescriptors` 失败被当成空列表 → `diff-pixel`
>   报 **`same`**）此前一路通过 15 项机械审计——已补上针对该类缺陷的
>   §2.5 / §2.6 审计。详见 `../STATUS.md` §2.3。
> - ⚠️ **§2.9 唯一未满足的 MUST**：MCP/IDE 仍走遗留进程内 `SessionManager`。
> - 跨仓库完成情况总报告见 `../STATUS.md`。

## 架构边界

```
        AI / IDE / 其他消费者（未来，全部在本项目之外或最外层）
                        │
             ┌──────────▼──────────┐
             │   Layer 2: rdebug   │   Query + Lazy Graph + Analysis
             │   （本仓库主体）      │   纯 JSON 证据输出
             └──────────┬──────────┘
                        │
             ┌──────────▼──────────┐
             │  Layer 1: adapter   │   把 renderdoc 模块包装成稳定查询接口
             └──────────┬──────────┘
                        │  renderdoc.pyd / renderdoc.so
             ┌──────────▼──────────┐
             │      RenderDoc      │   Layer 0：保持原样，不做任何修改
             │  Capture/Replay/RDC │   github.com/baldurk/renderdoc (MIT)
             └─────────────────────┘
```

设计红线：

| 原则 | 说明 |
| --- | --- |
| 不修改 RenderDoc 本体 | fork 仅用于跟踪 upstream 与未来少量可上游的补丁 |
| 不修改 RDC 格式 | 无 `.rdc` v2；如需索引一律旁路 `*.rdc.idx` |
| Lazy Graph | 图是**查询结果**，不是常驻状态；`trace-pixel` 只构建局部小图 |
| 第一阶段无 DB | 所有结果直接来自 replay API 的即时查询 |
| AI 不进入核心 | 未来 AI Provider 通过外部适配器接入本项目输出的 JSON 证据 |

## 运行前提

`renderdoc` Python 模块**不在官方安装包中**，需要自行构建（二进制必须与你运行本工具的解释器 CPython 版本一致）：

1. 按 RenderDoc 源码中 `docs/python_api/python_module.rst` 的说明构建；
2. Windows 下构建产物为 `pymodules/<平台>/<配置>/renderdoc.pyd`（同目录含 `renderdoc.dll`）；
3. 让本工具找到它，任选其一：
   - 设置环境变量 `RDEBUG_RENDERDOC_PATH=<该目录>`
   - 命令行传 `--rd-path <该目录>`

纯逻辑部分（events 过滤、lazy graph 组装、CLI）不依赖该模块即可测试。

## 安装

```bash
pip install -e .
```

## 使用

```bash
rdebug info capture.rdc
rdebug events capture.rdc --min-eid 1000 --max-eid 2000 --limit 50
rdebug draws capture.rdc --name shadow
rdebug pipeline capture.rdc --eid 1234
rdebug usage capture.rdc --resource 91
rdebug pixel-history capture.rdc --target 91 --x 824 --y 391
rdebug trace-pixel capture.rdc --x 824 --y 391
rdebug trace-resource capture.rdc --resource ResourceId::91   # Phase 2b: writers/readers
rdebug debug-pixel capture.rdc --x 824 --y 391            # 自动从 pixel history 选 fragment
rdebug debug-pixel capture.rdc --x 824 --y 391 --primitive 3 --sample 0
rdebug diff-pixel capture.rdc --a 320,240 --b 10,10       # Phase 3: first divergence
```

所有命令向 stdout 输出严格 JSON（NaN/Inf 已字符串化），错误走 stderr 的 `{"error": ...}` 并返回非零退出码，便于脚本与未来的 AI Agent 直接消费。

## Evidence Contract

所有分析结果必须能追溯到一个统一的证据结构：

```json
{
  "id": "a1b2c3d4e5f6",
  "capture": "capture.rdc",
  "eventId": 1821,
  "resourceId": "ResourceId(91)",
  "subresource": {"mip": 0, "slice": 0, "sample": 0},
  "location": {"x": 824, "y": 391},
  "operation": "writes",
  "source": "ReplayController.PixelHistory",
  "data": {}
}
```

规则：

- `id` 由除 `data` 外的字段内容哈希生成，稳定可引用；
- `data` 携带附加负载，不参与身份计算；
- 任何结论（图上的边、shader trace、未来的 diff/AI 结论）只能通过 evidence 引用回原始查询；
- 未来新增分析（resource flow、diff、AI）一律复用 `rdebug.evidence.make`，不得自造格式。

## 使用

`trace-pixel` 输出形如：

```json
{
  "nodes": [
    {"id": "pixel:824,391", "kind": "pixel", "attrs": {"x": 824, "y": 391}},
    {"id": "target:ResourceId(91)", "kind": "target", "attrs": {"resource": "ResourceId(91)"}},
    {"id": "draw:1234", "kind": "draw", "attrs": {"eventId": 1234, "primitives": [3], "passed": 1, "failed": 0}},
    {"id": "shader:1234:ResourceId(7)", "kind": "shader", "attrs": {"stage": "Pixel"}},
    {"id": "resource:ResourceId(42)", "kind": "resource", "attrs": {}}
  ],
  "edges": [
    {"from": "draw:1234", "to": "target:ResourceId(91)", "label": "writes",
     "evidence": [{"id": "...", "eventId": 1234, "operation": "writes",
                    "data": {"primitives": [3], "postMod": {"float": [0,0,0,1]}}}]},
    {"from": "shader:1234:ResourceId(7)", "to": "resource:ResourceId(42)", "label": "reads"}
  ],
  "summary": {"modificationCount": 2, "finalValue": {"float": [0,0,0,1]}, "truncatedDraws": false}
}
```

每个节点/边都携带 eventId 级别的 evidence 引用——这是"Evidence-first"原则：任何结论都必须能指回原始数据。

## Shader Debug（Phase 2a）

```bash
rdebug debug-pixel capture.rdc --x 824 --y 391
```

流程：自动选输出目标 → pixel history 找到最后一个通过且非 unboundPS 的 fragment → `SetFrameEvent` → `DebugPixel` → `ContinueDebug` 循环 → 结构化 trace。输出形如：

```json
{
  "eventId": 1821,
  "pixel": {"x": 824, "y": 391},
  "primitive": 3,
  "shader": {"stage": "Pixel", "entryPoint": "PSMain", "resource": "ResourceId(7)"},
  "inputs": [{"name": "input.color", "type": "Float", "rows": 1, "columns": 4}],
  "outputs": {},
  "steps": [
    {"stepIndex": 5, "nextInstruction": 12,
     "source": {"fileIndex": 0, "line": 42, "disassemblyLine": 17},
     "disassemblyText": "mov o0.xyzw, r0.xyzw",
     "sourceFile": "ps.hlsl",
     "changes": [{"before": {...}, "after": {...}}]}
  ],
  "stepCount": 87,
  "truncated": false,
  "evidence": [{"id": "...", "operation": "shader_debug"}]
}
```

说明：

- `inputs`/`constantBlocks` 来自 `ShaderDebugTrace` 的原生变量树；`outputs` 目前为占位（跨 API 提取输出寄存器留到后续）；
- `--no-disassembly` 可省略反汇编文本，只保留行号映射；
- shader 不可调试时（`debugInfo.debuggable == false`）返回带 `debugStatus` 的明确错误，而不是猜测。

## 作为库使用

```python
from rdebug.adapter.core import CaptureSession
from rdebug.analysis.pixel_trace import trace_pixel
from rdebug.analysis.shader_trace import debug_pixel

with CaptureSession("capture.rdc") as s:
    graph = trace_pixel(s, x=824, y=391)
    trace = debug_pixel(s, x=824, y=391)   # 自动选 fragment 并步进 shader
```

## 测试与质量

```bash
python -m unittest discover -s tests          # 纯逻辑单元测试，无需 renderdoc 模块
python -m ruff check src tests                # 可选

# 集成测试：需要真实模块 + capture，缺省自动跳过
set RDEBUG_RENDERDOC_PATH=C:\path\to\built\pymodules
set RDEBUG_INTEGRATION_CAPTURE=D:\captures\test.rdc
python -m unittest discover -s tests
```

目录结构：

```
tests/                            # 核心：74 tests（unit 65 + integration 9）
├── unit/                         # 不依赖 GPU / renderdoc 模块，CI 可全跑
│   ├── test_ci_gate.py
│   ├── test_clear_semantics.py
│   ├── test_cli.py
│   ├── test_dataflow_phase2c.py
│   ├── test_events_logic.py
│   ├── test_evidence.py
│   ├── test_pixel_diff.py
│   ├── test_pixel_trace_graph.py
│   ├── test_resource_flow.py
│   └── test_shader_trace_build.py
├── integration/                  # 通过环境变量开启，验证真实 replay 路径
│   └── test_real_replay.py
└── workload/                     # 10 tests；需 corpus + RDEBUG_RENDERDOC_PATH
    └── ...

tests_transport/                  # 31 tests；MCP/IDE 传输层不变量，与核心完全隔离
├── test_transport.py
├── test_session_manager.py
├── test_observability.py
└── test_ide_app.py
```

> ⚠️ `tests_transport/` 没有 `__init__.py`，且不在 `pyproject.toml` 的
> `testpaths = ["tests"]` 之内——默认 `pytest` 会**静默跳过**这 31 个测试。
> 需显式运行：`python -m unittest discover -s tests_transport`。

## Roadmap

- [x] Phase 1a：Adapter（info/events/draws/resources/pipeline/pixel-history/usage）
- [x] Phase 1b：Lazy Graph（trace-pixel 局部图，JSON 证据输出）
- [x] Phase 2a：Shader Debug Adapter（debug-pixel → 结构化 ShaderTrace）+ Evidence Contract
- [x] Phase 2a 验证：真实 `renderdoc.pyd` + 真实 `.rdc` 端到端（见 `docs/validation/phase2a.md`）
- [x] Validation：性能基线（Small/Medium 档、重复查询曲线）→ **判定暂不需要 `.rdc.idx`**（见 `docs/validation/perf-baseline.md`）
- [x] Phase 2b：`trace-resource`（writer/reader 分类 + evidence，基于 `GetUsage`）
- [x] Phase 2c：Pixel→Shader→Resource→Writer 局部数据流（`PixelHistoryResult` 一等共享、
  reads 一层展开、history 复用回归 ≈省一半以上，见 `docs/validation/perf-baseline.md`）
- [x] Phase 3（第一版）：`diff-pixel` 同 capture 两像素局部因果链 diff——
  六层比较（pixel_value/fragment/shader/input_bindings/shader_input_values/resource_provenance）、
  same|different|unknown 三态（无相似度）、最深因果层为 firstDivergence、全链 evidence 回链；
  跨 capture identity 语义与采样值提取留待后续（当前 `shader_input_values` 默认 unknown）
- [x] Phase 3a closure：Medium 档插桩验证（history 恰好 2 次、无重复展开、语义稳定，
  见 `docs/validation/phase3a-closure.md`）+ **Semantic API v1 冻结**
- [x] Phase 3b①：Deep Diff（`--include-shader-values`，默认关闭，基础语义不变）
- [x] Phase 4a：Thin MCP Transport（`rdebug-mcp`，仅四个 tool，无编排/无分析/无 RenderDoc API；
  协议级冒烟通过，transport 测试与核心测试完全隔离）
- [x] Phase 4b：真实 LLM tool-use 验证（被测模型 ox-alpha，self-play 经真实 MCP transport；
  三实验 5/5 通过：tool selection / argument correctness / evidence grounding /
  unknown discipline / no hallucinated API，见 `docs/validation/phase4b-trajectory.md`）
- [x] Clear 语义修正：`fragment_candidate` 谓词（clear 保留 pixel 事实、永不成为 fragment
  候选、不携带 shader evidence）
- [x] Phase 4c：Grounded reasoning benchmark（5 指标 × 4 case 全通过；首轮即抓出 diff 层
  evidence 缺口并修复，见 `docs/validation/phase4c-reasoning.md`）
- [x] Phase 4d：Transport session reuse（SessionManager：路径隔离/LRU/健康探测/失效恢复；
  稳态 trajectory **184.5ms vs cold 6993.5ms（≈38×）**，语义等价 4/4，
  见 `docs/validation/phase4d-session-reuse.md`）
- [x] **v1 Architecture Freeze**（`c060ba2`）：Stable Core = Semantic API v1 + Evidence Model；
  所有前端（MCP/CLI/IDE/CI）只经 Stable Core 消费，禁止直连 RenderDoc API
- [x] Phase 5a：CI 回归试点（`ci-record`/`ci-check` 确定性门禁：基线指纹 + evidence 回链 +
  机器可读 verdict，AI 仅作解释器，见 `docs/validation/phase5a-ci.md`）
- [x] Phase 5b：IDE 极简原型（`rdebug-ide`：CI failure → pixel → firstDivergence →
  provenance → evidence → grounded AI prompt，仅消费 Stable Core，
  见 `docs/validation/phase5b-ide.md`）
- [x] Phase 5c（重定义）：Production Observation——opt-in JSONL 遥测
  （`RDEBUG_TELEMETRY`），transport 层记录 session/query 生命周期与延迟；
  **并发层冻结**：除非真实数据证明瓶颈，且届时优先进程隔离
  （见 `docs/validation/phase5c-observability.md`）
- [x] **v1 Design Spec 冻结**：`docs/DESIGN_SPEC.md`（五层边界 MUST/MUST-NOT +
  数据驱动决策规则 + 质量门）+ `scripts/audit_boundaries.py` 机械合规审计（8/8）
- [x] Phase 5d：Workload Test v1（14-capture S/M/L 语料；确定性 / 冷热 / evidence /
  三态 / 隔离 / LRU / 错误注入 / MCP 契约 / 压测九个套件，共 10 tests）。
  Round 1 GATE FAIL 暴露 WLF-1（LRU 逐出路径原生 AV），Round 2（2026-08-25）
  **GATE PASS**：2193 queries、correctness 11/11、0 violation，见
  `docs/validation/phase5d-workload.md`）
- [ ] Runtime Isolation（§2.9 WorkerManager 模型）—— **代码已写但未提交、未接线、
  无测试覆盖**。详见下方「Runtime Isolation 实现状态」。

### Runtime Isolation 实现状态（2026-09-29 核对并修复）

`DESIGN_SPEC.md` §2.9 冻结了「一 worker 进程 = 一 replay runtime = 一 capture」的
架构事实，证据链来自 W1-R1→W1-R3（记录在仓库外 `rdebug-validation/docs/`）。
本轮已修复下列缺陷，并用真实 RenderDoc 运行时做了端到端验证。

**已修复**

| 缺陷 | 位置 | 影响 |
| --- | --- | --- |
| 内存基线初始化写在 `return` 之后（不可达死代码） | `worker_manager.py` `_death_message()` | `mem_baseline` 恒为 `None` → `max_private_memory_delta` 触发器**永不生效**，`production_default()` 的 Δ128MB 形同虚设。已移入 `_spawn()` 成功路径 |
| `psutil` 未声明为依赖 | `pyproject.toml` | 干净安装下 private bytes 不可读，内存门禁静默失效。已加入 `dependencies` |
| `psutil` 缺失时静默降级 | `worker_manager.py` | 现显式置 `None` 并上报 `memory_metric: "unavailable"`，**不回退到 RSS 当门禁**（§2.9 禁止） |
| 字段名违反 §2.9 命名 MUST | `worker_info()` / `recycle_events` | 曾以 `rss_baseline` / `mem_baseline_mb` 承载 private bytes。改为 `private_memory_baseline_bytes` / `private_memory_baseline_mb` |
| 崩溃恢复靠错误串子串匹配 | `WorkerManager.query()` | 消息含 "dead" 的查询错误会被误判为进程死亡并触发整进程回收。改为结构化 `WorkerError.transient` |
| 启动失败遗留孤儿进程 | `_Worker._spawn()` | worker 起来但 ping 失败时进程不被终止，仍持有 replay runtime。已补 `kill()` |
| 子进程管道句柄泄漏 | `_Worker.kill()` | stdout/stderr 从不关闭，长驻 transport 每次回收泄漏一组句柄。已关闭三路管道 |
| `pixel_diff.py` 函数重复定义 | `_interpolated_inputs` | 两个逐字相同的定义，后者遮蔽前者。已删其一 |

**端到端验证（真实 RenderDoc，2026-09-29）**

在 `tests/workload/corpus/w01024_frame11.rdc` 上实测：

- spawn 后 `mem_baseline = 198.88 MB`（修复前恒为 `None`）；
- 私有内存增长实测 **~800 KB/查询**（w00016 约 170 KB/查询），
  与 W1 的 230–500 KB/query 观测同量级；
- `max_private_memory_delta` 触发器**实际触发**：6 个 worker 代次、5 次回收，
  `recycle_events` 记录 `reason: "max_private_memory_delta"`；
- **§2.9「语义结果不依赖 worker 生命周期」实测成立**：跨 6 代次
  语义 payload 逐字节一致（该性质在修复前无法验证——因为从不发生回收）。

**仍存在的差距**

| 状态 | 项 |
| --- | --- |
| ⚠️ 未接线 | `rdebug_mcp/server.py:34` 与 `rdebug_ide/app.py:39` 仍实例化遗留的进程内 `SessionManager`。W1-R1 的 F-1/F-2 正是发生在该路径上。`audit_boundaries.py` 现将其登记为 DEVIATION（不判失败，但会持续显示）——这是 §2.9 唯一未满足的 MUST |
| ⚠️ 无 CI | 仓库无 `.github/workflows`。上述测试与边界审计需手工执行 |

### 语义层「失败不得冒充观测」（2026-09-29 第二轮修复）

`DESIGN_SPEC` §2.5 要求 `unknown` 既非 `same` 也非 `different`，任何层不得把
unknown 升级为确定结论。多个路径曾把「查不到」转成空值，于是空值与另一个空值
相等，被读成「一致」：

| 缺陷 | 后果 |
| --- | --- |
| `GetAllUsedDescriptors` 失败 → `used = []` | **最严重**：`build_graph` 不产 `reads` 边 → `diff-pixel` 比 `[]` vs `[]` → `input_bindings`/`resource_provenance` 报 **`same`**。单边失败则报 `different` 且值为空，等于断言另一侧「不读任何资源」。**该结论直达 CI 判定器** |
| `DisassembleShader` 失败 → `disasm = ""` | 空串成为语义结果，`disassemblyText` 在每个 step 静默缺失，失败不可归因 |
| `GetAPIProperties` 失败 → 键缺失 | `rdebug info` 返回 200 但静默少两个字段 |

修复方式：`core.py` 报告 `descriptorsError` / `disassemblyError` /
`apiPropertiesError`；`build_graph` 传播 `summary.readsEnumerable`；
`_extract_flow` 在不可枚举时返回 `None` 而非 `[]`（`compare_scalar` 已把
`None` 映射为 `unknown`）。**诚实的「无描述符」仍是 `same`**——空观测仍是观测。

教训已固化：这两类缺陷此前能一路通过 15 项机械审计，因为审计对异常处理
零覆盖。现补 **§2.5**（语义层禁止用空值冒充失败查询，AST 结构匹配）与
**§2.6**（transport 必须把参数错误转成响应体）两条检查。
两条检查在写成后都**实测抓不到自己的目标 bug**（一版正则被无关 handler 骗过，
一版全文件扫描被 3 个函数外的 `except ValueError` 骗过），改为结构化匹配后才
真正生效——详见 `../STATUS.md` §2.3。

**后续新增机械检查的纪律：先回退被修的缺陷、确认检查会 FAIL，再恢复。**

测试：`tests/unit/test_worker_manager.py`（34）+ `test_unknown_discipline.py`（13），
`tests_transport/` 37。核心 112、transport 34、integration 9、workload 10
（需真实 capture）。边界审计 17/17 + 1 deviation，`ruff check` 全绿。

- [ ] **Real-world Validation**（唯一开放的 roadmap 项，NOT STARTED）：
  A. 真实项目试点（非 fixture capture 走完整链路）→
  B. 数据驱动优化（只解决 telemetry 证明的问题）→
  C. v1.1 决策（仅由真实需求触发；跨 capture matching 继续冻结）

  `docs/REAL_WORLD_VALIDATION.md` 的 5 项检查全部未勾选。前置条件尚未满足：
  磁盘上仅有 **1h51m** 遥测（2026-08-25 04:45–06:37，710 事件），
  不构成 `REAL_WORLD_VALIDATION.md:53` 要求的「≥1 周真实负载归档」。
  该文档同时写明「从此刻起，『不开发』是默认正确的工程动作」。

  跨机器确定性（D7 / N1）为 OPEN 证据缺口——B/C 机器 `unavailable`，
  不作跨机器声明；且 N3 侧的 D7 缺口**不能靠替换渲染器关闭**。

## Stable Core（冻结）

```text
RenderDoc (zero modifications)
      │
rd-intelligence Stable Core
  ├─ Semantic API v1: trace_pixel / trace_resource / debug_pixel / diff_pixel
  └─ Evidence Model: 稳定 id + eventId/resourceId/operation 回链
      │
Transports: MCP ｜ CLI ｜ CI ｜ IDE（均只消费 Stable Core）
```

分层定位：`RenderDoc = Replay Engine`，`rd-intelligence = Debug Semantics`，
`MCP = AI Transport`，`CI gate = 确定性判定`，`LLM = 解释器（非裁判）`。

## MCP Transport（Phase 4a）

```bash
pip install -e .[mcp]
rdebug-mcp          # stdio MCP server，四个 tool：trace_pixel / trace_resource / debug_pixel / diff_pixel
```

边界（由 `tests_transport/` 不变量锁定）：

- 不出现任何 RenderDoc API 标识（`ReplayController/PixelHistory/GetUsage/DebugPixel/...`）；
- 对 `rdebug.analysis` 的 import 仅限四个语义函数——**无编排、无分析逻辑**；
- 结果（含 evidence）原样 JSON 透传，不创建第二套 domain model；
- 运行期错误以 `{"error": ..., "tool": "..."}` JSON 返回，不中断会话；
- 会话复用已实现（Phase 4d `SessionManager`：路径隔离 / LRU / 健康探测 /
  失效恢复），稳态 **184.5ms vs cold 6993.5ms（≈38×）**，语义等价 4/4。
  ⚠️ 但 `server.py:34` 当前仍实例化**遗留的进程内** `SessionManager`，
  未迁移到 §2.9 的 WorkerManager 模型；W1-R1 的 F-1/F-2（多 controller 共存导致
  静默值污染 / 原生挂起 / 0xC0000005）正发生在该路径上。
  缓解：Agent/IDE 切换 capture 即重建 transport。见 `DESIGN_SPEC.md` §2.9。

客户端配置示例（Claude Desktop / 任意 MCP client）：

```json
{
  "mcpServers": {
    "rdebug": {
      "command": "rdebug-mcp",
      "env": { "RDEBUG_RENDERDOC_PATH": "C:\\path\\to\\pymodules" }
    }
  }
}
```

协议冒烟：`python scripts/mcp_smoke.py <capture.rdc>`（list_tools + 四 tool 实调）。

## Semantic API v1（冻结）

```python
from rdebug import trace_pixel, trace_resource, debug_pixel, diff_pixel
```

这四个概念是稳定公共面：签名只做加法演进，RenderDoc API 变化由 Adapter 吸收。
分层职责：`RenderDoc = Replay Engine`，`rd-intelligence = Debug Semantics`，
`MCP = AI Transport`，`LLM = Reasoning/Explanation`——AI 只消费 evidence、
解释证据、排序假设、规划下一步查询，不操作底层 API。

## 设计原则（由真实验证固化）

- **ResourceId 是不透明引用**：Layer 2 一律使用 `rdebug.model.ResourceRef`，禁止 `int` 假设；
  `ResourceId::NN` 字符串形式只是 adapter 边界格式。
- **每条 data-flow 边必须携带 evidence**，可回链 `eventId/resourceId/operation` → RenderDoc 原始事实。
- **fixture 负责确定性回归，真实游戏 capture 负责真实行为**，两者不可互相替代。

## 许可证

MIT。RenderDoc 本体为其自身的 MIT 许可证；两者通过稳定 API 解耦，许可证边界即架构边界。
