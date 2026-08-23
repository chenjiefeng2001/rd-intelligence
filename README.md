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
```

所有命令向 stdout 输出严格 JSON（NaN/Inf 已字符串化），错误走 stderr 的 `{"error": ...}` 并返回非零退出码，便于脚本与未来的 AI Agent 直接消费。

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
     "evidence": {"eventId": 1234, "primitives": [3], "postMod": {"float": [0,0,0,1]}}},
    {"from": "shader:1234:ResourceId(7)", "to": "resource:ResourceId(42)", "label": "reads"}
  ],
  "summary": {"modificationCount": 2, "finalValue": {"float": [0,0,0,1]}, "truncatedDraws": false}
}
```

每个节点/边都携带 eventId 级别的 evidence 引用——这是"Evidence-first"原则：任何结论都必须能指回原始数据。

## 作为库使用

```python
from rdebug.adapter.core import CaptureSession
from rdebug.analysis.pixel_trace import trace_pixel

with CaptureSession("capture.rdc") as s:
    graph = trace_pixel(s, x=824, y=391)
```

## 测试与质量

```bash
python -m unittest discover -s tests
python -m ruff check src tests   # 可选
```

## Roadmap

- [x] Phase 1a：Adapter（info/events/draws/resources/pipeline/pixel-history/usage）
- [x] Phase 1b：Lazy Graph（trace-pixel 局部图，JSON 证据输出）
- [ ] Phase 2a：Shader debug 步进封装（DebugPixel → 变量级 trace）
- [ ] Phase 2b：多帧 diff、资源生命周期摘要（仍为查询时计算）
- [ ] Phase 2c：旁路 capture index（`*.rdc.idx`，仅在性能实测需要时引入）
- [ ] Phase 3：AI Provider 外部适配层（消费 JSON 证据，绝不反向污染 Layer 0/1）

## 许可证

MIT。RenderDoc 本体为其自身的 MIT 许可证；两者通过稳定 API 解耦，许可证边界即架构边界。
