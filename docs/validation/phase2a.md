# Phase 2a 真实 replay 验证报告

日期：2026-08-24
环境：Windows 11 / NVIDIA RTX 3070 Laptop / VS2022 (v143) / Python 3.13 / RenderDoc v1.x fork 自建（含 `renderdoc.pyd`）

## 结论

**Phase 2a 假设已被真实 capture 验证**：在不修改 RenderDoc、不建缓存、不依赖 GUI 的前提下，
薄 Adapter + 纯分析层可以通过程序可靠回答"这个像素是怎么产生的"，并直接步进产生它的 shader。

## 构建产物

- `renderdoc.pyd`：由 fork 源码构建（`msbuild pyrenderdoc_module.vcxproj /p:VSPythonOverridePath=C:\Python313`），
  输出于 `renderdoc/x64/Release/pymodules/`（fork 无任何 tracked 改动）。
- 测试 capture：`tests/integration/fixtures/triangle_app.cpp` 自编译自捕获
  （in-app API `RENDERDOC_GetAPI` → `TriggerCapture`，30 帧动画捕获第 10 帧，405KB，3 events / 1 draw）。

## 基准数据（scripts/bench_phase2a.py）

> ⚠️ **2026-09-29 核对**：`scripts/bench_phase2a.py` **在当前仓库中不存在**
> （`scripts/` 下只有 `bench.py`）。上文与第 84 行的复现命令均为历史记录，
> 按原样复现需先找回该脚本。

| 指标 | 值 |
| --- | --- |
| capture 大小 | 405,423 B |
| 打开+首次 replay | ~1.9–3.2 s（进程内仅一次） |
| 事件扁平化（全帧） | 0.02 ms |
| pipeline 快照 | 0.15 ms |
| trace-pixel（含 history+2 次 pipeline+建图） | **5.24 ms**（best of 3） |
| debug-pixel（DebugPixel+ContinueDebug 全程） | **152.96 ms** |
| shader 指令数 / max_steps 截断 | 3 / 否 |
| 分析期 Python 峰值内存 | 41 KB |
| trace-pixel 图规模 | 6 nodes / 5 edges |

小 capture 上 Replay API 直查完全够用，**不需要 `.rdc.idx`**；后续用中/大型 capture 复测后再定。

## 验证过程中发现并修复的真实问题

以下问题全部由本工具链自身的证据输出定位，反向证明了 Evidence-first 的价值：

1. **`ResourceId` 是不透明类型**（`resourceid.h`：无公开 int 构造）。
   → Adapter 改为经 `GetResources()` 建立会话级字符串→对象缓存解析。
   同时确认 `str(ResourceId)` 格式为 `ResourceId::NN`（冒号而非括号）。

2. **`InitialiseReplay`/`ShutdownReplay` 不可重入**（文档明确禁止 re-init）。
   → 同进程多会话必须共享生命周期。Adapter 增加进程级引用计数；
   `ShutdownReplay` 仅能通过显式 `CaptureSession.shutdown_replay()` 调用。
   （此前单测在集成测试后重开 session 触发原生层 AV。）

3. **fixture 无 viewport**：D3D11 未 `RSSetViewports` 时无任何 fragment 光栅化。
   pixel-history 全屏扫描 + SaveTexture 导出图均为纯 clear 色 → 定位。

4. **fixture 背面剔除**：D3D11 默认光栅化 `CullMode=BACK` 且顺时针为正面。
   pixel-history 输出 `backfaceCulled: true` → 交换顶点绕序修复。

## API 语义观察（用户要求清单）

| 项 | 观察 |
| --- | --- |
| fragment 自动选择 | 正确（跳过 clear/unboundPS/directWrite，取最后一个 passed） |
| `DebugPixelInputs` 匹配 | primitive=0 与 history 一致；sample/view 用 NoPreference(~0U) |
| `ContinueDebug` 异常长 trace | 本例 3 条指令；`max_steps`（默认 4096）保护存在且可配置，未误伤 |
| `FreeTrace` 可靠性 | 所有路径（成功/失败/异常）经 finally 释放 |
| PS 输入语义 | `v1=(0.348,0.311,0.341,1.0)` 为像素中心重心插值色，正确 |
| 枚举可读性 | `stage/type` 已映射为名称（如 `Pixel`/`Float`） |

## Evidence Contract 验证

`pixel-history → trace-pixel → debug-pixel` 三层输出的 evidence 均含
`capture/eventId/resourceId/subresource/location/operation/source/id`，
可稳定回链到 RenderDoc 原始事实；未引入 confidence/AI 字段（保持契约最小）。

## 复现步骤

```bat
:: 1. 构建 python 模块（一次性）
msbuild renderdoc\qrenderdoc\Code\pyrenderdoc\pyrenderdoc_module.vcxproj ^
  /p:SolutionDir=D:\renderdoc_no_mcp\renderdoc\ /p:Configuration=Release /p:Platform=x64 ^
  /p:VSPythonOverridePath=C:\Python313
:: 2. 生成测试 capture
cl /O2 /EHsc /I <renderdoc>\renderdoc\api\app triangle_app.cpp
triangle.exe 30 <out>\triangle.rdc <renderdoc>\x64\Release\renderdoc.dll
:: 3. 集成测试 + 基准
set RDEBUG_RENDERDOC_PATH=<renderdoc>\x64\Release\pymodules
set RDEBUG_INTEGRATION_CAPTURE=<out>\triangle_frame11.rdc
C:\Python313\python.exe -m unittest discover -s tests
C:\Python313\python.exe -m unittest discover -s tests_transport   :: 见下方注
C:\Python313\python.exe scripts\bench_phase2a.py %RDEBUG_INTEGRATION_CAPTURE%  :: 脚本已不存在
```

> ⚠️ **2026-09-29 核对（复现须知）**：
> 1. `scripts/bench_phase2a.py` **不存在**（`scripts/` 下只有 `bench.py`）——
>    本节原复现流程的最后一行无法直接执行。
> 2. `tests_transport/` **不在** `pyproject.toml` 的 `testpaths = ["tests"]` 内，
>    默认 `pytest` 会跳过它；上表已补上显式运行命令（31 tests）。
> 3. 路径分隔符在原文混用 `/` 与 `\`（如第 83 行），Windows 下可运行但不一致。
