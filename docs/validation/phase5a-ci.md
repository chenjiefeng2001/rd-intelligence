# Phase 5a：CI 回归试点

日期：2026-08-24 · 实现：`rdebug/ci.py` + CLI `ci-record` / `ci-check`
试点对象：`triangle_frame11.rdc`（2 像素断言 + 1 pair 断言）

## 设计

**判定者是确定性语义，AI 只是解释器。** known-good 以"基线文件"形式存在
（golden JSON sidecar，不触碰 RDC），从而完全绕开冻结的跨 capture matching：

```text
ci-record: capture + spec → golden baseline（确定性指纹）
ci-check : capture + baseline → {status, failures[{kind,path,expected,actual,evidenceIds}]}
exit code: 0=pass  1=regression  2=error
```

断言指纹（全部 id 无关，可跨构建存活）：

- 像素：`finalValue.float`（带容差）+ `fragmentEventId`
- pair：`comparison` + `firstDivergence` 层 + 六层 `layerStatuses`
- 门禁：capture SHA-256 匹配（`--ignore-capture-hash` 可豁免）

## 试点结果

| 步骤 | 结果 |
| --- | --- |
| `ci-record` | 2 pixels + 1 pair 写入 golden.json |
| `ci-check`（原样） | **pass**，5/5 checks，hashMatch=true，exit 0 |
| `ci-check`（基线 R 通道被篡改 0.349→0.123） | **regression**，exit 1 |

回归输出样例（机器可读，可直接作为 AI 解释器的输入）：

```json
{
  "status": "regression",
  "failures": [{
    "kind": "pixel_value",
    "path": "pixel(320,240).finalValue.float",
    "expected": [0.123, 0.243, 0.216, 1.0],
    "actual":   [0.349, 0.243, 0.216, 1.0],
    "evidenceIds": ["684378c40853"]
  }]
}
```

## 测试

- 单测 5 个（roundtrip pass / 值回归+evidence / 容差吸收 / pair 回归 / hash 门禁+豁免），
  核心套件 74/74、transport 15/15 全绿。

## CI 使用样例（GitHub Jobs 伪码）

```yaml
- run: triangle.exe 30 out.rdc <renderdoc.dll>
- run: rdebug ci-check out.rdc --baseline golden.json --rd-path <pymodules>
```

## 后续（P5b/P5c，均未开工）

- P5b IDE 原型：消费同一 Semantic API（树视图 = 局部数据流；AI 面板 = 解释 divergence）
- P5c 并发策略：等真实 CI 多 job 场景出现后再设计（当前 LRU=4 已覆盖单用户多捕获）

> **2026-09-29 核对（历史状态已过时）**：P5b 与 P5c **均已完成**——
> 分别见 `docs/validation/phase5b-ide.md`（IDE SMOKE OK）与
> `docs/validation/phase5c-observability.md`（重定义为 opt-in JSONL 遥测；
> 并发层冻结，除非真实数据证明瓶颈）。上文保留为历史记录。
