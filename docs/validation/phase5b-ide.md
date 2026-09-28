# Phase 5b：IDE 极简原型

日期：2026-08-24 · 实现：`rdebug_ide`（`rdebug-ide` 入口，纯 Python 标准库 + 单页 vanilla JS，无构建链）

## 定位

**不是 RenderDoc GUI 2.0。** 只验证一件事：

> 一个前端仅消费 Stable Core（Semantic API v1 + CI gate），就能提供比
> "打开 RenderDoc GUI 手工点击几十次" 更直接的因果调试工作流。

## 工作流（已验证）

```text
CI regression（ci-check 基线）
  ↓ 点击 failure
pixel / pair 定位
  ↓
firstDivergence 层 + 六层状态
  ↓ 展开 Reads
Texture::47 ← written by Copy#2
  ↓
Evidence chips（点击可追溯）
  ↓
[Explain with AI] → 生成 grounded prompt（含全部 evidence 与 unknown 纪律指令，
                    供任意 LLM 消费；LLM 接线按架构留在 IDE 之外）
```

## 端点（全部为 Stable Core 直通，无分析逻辑）

`/api/info` `/api/ci` `/api/trace?x,y` `/api/diff?a,b,deep` `/api/resource?id` `/api/explain?a,b,deep`

## 冒烟结果（真实 replay）

```text
info: triangle_frame11.rdc
diff: different | first: input_bindings
trace reads: [resource:ResourceId::47]
resource writers: [(2, CopyDst)]
prompt: "You are explaining a GPU pixel diff. Use ONLY the facts below…"
evidence ids: 9
index.html: 8330 bytes served
IDE SMOKE OK
```

## 测试与质量

- `tests_transport/test_ide_app.py`：8 个 API 层测试（路由/三态/unknown/错误 400/
  grounded prompt 断言/会话复用），transport 套件 23/23、核心 74/74 全绿；
- SessionManager 提升为 `rdebug/session_cache.py` 共享基础设施（MCP 与 IDE 复用，
  行为不变，全部既有测试通过）；
- 坐标参数非法输入 → 400 JSON（不崩服务）。

> **2026-09-29 核对**：「transport 套件 23/23」为本报告撰写时的历史计数，
> 当前 `tests_transport/` 实为 **31 tests**（后续 commit 新增 `result_shape` 等测试）。
> 该目录无 `__init__.py` 且不在 `pyproject.toml` 的 `testpaths` 内，默认 pytest 不会运行它。

## 使用

```bash
pip install -e .
rdebug-ide capture.rdc --baseline golden.json [--port 8760]
# 打开 http://127.0.0.1:8760/
```

## 明确不做（本阶段）

- 实时 GPU viewer / 纹理预览
- LLM API 直接接线（prompt 组装在 IDE，调用在用户侧——transport 分离原则）
- 任何 Stable Core 之外的语义
