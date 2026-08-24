# rd-intelligence

RenderDoc 的**外部调试智能层**：RenderDoc 负责事实（capture / replay / pixel history），本项目负责理解事实（查询 / 局部依赖图 / 证据输出）。第一阶段不含 AI、不建数据库、不修改 RDC 格式。

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
tests/
├── unit/            # 不依赖 GPU / renderdoc 模块，CI 可全跑
│   ├── test_events_logic.py
│   ├── test_evidence.py
│   ├── test_pixel_trace_graph.py
│   ├── test_shader_trace_build.py
│   └── test_cli.py
└── integration/     # 通过环境变量开启，验证真实 replay 路径
    └── test_real_replay.py
```

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
- [ ] Phase 3b②：跨 capture diff —— **冻结，不做**（entity resolution 复杂度不划算）

## MCP Transport（Phase 4a）

```bash
pip install -e .[mcp]
rdebug-mcp          # stdio MCP server，四个 tool：trace_pixel / trace_resource / debug_pixel / diff_pixel
```

边界（由 `tests_transport/` 不变量锁定）：

- 不出现任何 RenderDoc API 标识（`ReplayController/PixelHistory/GetUsage/DebugPixel/...`）；
- 对 `rdebug.analysis` 的 import 仅限四个语义函数——**无编排、无分析逻辑**；
- 结果（含 evidence）原样 JSON 透传，不创建第二套 domain model；
- 运行期错误以 `{"error": ..., "tool": ...}` JSON 返回，不中断会话；
- 每次调用独立打开 capture（~1–3s 开销）；会话复用留作加法演进。

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
