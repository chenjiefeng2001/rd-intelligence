# 性能基线（Validation 阶段报告）

日期：2026-08-24
环境：RTX 3070 Laptop / Python 3.13 / 自建 `renderdoc.pyd`（v1.x fork tip）
工具：`scripts/bench.py`（cold = 进程内首次查询，warm = 同查询重复执行的最好值）

## 捕获档位

| 档位 | 来源 | 大小 | events | draws | 说明 |
| --- | --- | --- | --- | --- | --- |
| Small | fixture（1 draw/帧） | 396 KB | 3 | 1 | `triangle_frame11.rdc` |
| Medium | fixture（400 draws/帧，同像素高重叠） | 401 KB | 402 | 400 | `medium_frame11.rdc` |
| Large | （未测） | — | — | — | 真实游戏 capture；`bench.py` 可直接对其运行 |

## 结果总表（warm best，ms）

| 查询 | Small | Medium |
| --- | --- | --- |
| 打开会话（含首次 replay init） | 2988 (cold) | 1594 (cold) |
| 扁平化全部事件 | 0.01 | 1.25 |
| pipeline 快照 | 0.23 | 0.33 |
| pixel-history（同像素重复） | 5.97（2 mods） | **942.76（401 mods）** |
| trace-pixel（同像素重复） | 4.71 | 948.95（截断至 16 draws，419 nodes） |
| trace-pixel（不同像素） | 2.3–9.3 | 52 / 994 / 1949（取决于该像素的 mod 数） |
| debug-pixel | 118.7 | 1167–2162（含选 fragment 的 history） |
| trace-resource | 0.24（2 usages） | **17.45（401 usages）** |
| 分析期 Python 峰值内存 | 17 KB | 1.68 MB |

## 重复查询判定（`.rdc.idx` 决策依据）

| 模式 | 观察 | 结论 |
| --- | --- | --- |
| 同资源 trace-resource ×4 | 20.0 → 17.5 ms（≈无衰减） | GetUsage 无需缓存 |
| 同像素 trace-pixel ×4 | cold≈2×warm（943 vs 1931） | replay 内部有约 2× 缓存，但非数量级 |
| 事件规模扩展（3→402 events） | 扁平化 0.01→1.25 ms | **事件数量不是瓶颈** |
| 像素 mod 数扩展（2→401 mods） | pixel-history 6→943 ms | **真正的成本驱动：单像素修改数** |

**结论：不需要 `.rdc.idx`。**

- 事件/资源索引类查询（flatten、usage、pipeline）在 402 events 下全部 ≤20ms；
- 唯一的大头是 `PixelHistory` 在高重叠像素上的固有 replay 开销——这是按像素重放 GPU 工作，
  任何"event→resource"索引都无法消除它；
- `trace-resource`（Phase 2b 核心）warm 17ms，直接可用。

## 由此确定的后续设计约束

1. **Phase 2c 数据流串联时必须复用 pixel history**：`debug-pixel` 内部的 fragment 选择
   会再算一次 history（Medium 档 1.9s）。串联 `trace-pixel → trace-resource → debug`
   时应把已算好的 history 传下去，避免重复计算。这是下一个最划算的优化点。
2. `max_draws` 截断（默认 16）在高重叠场景下有效控制了图规模（419 nodes），
   且未误伤（被截断的 384 个 draw 在 summary 中如实标注 `truncatedDraws: true`）。
3. Large 档预期：事件数量级增长不影响上述索引类查询；若单像素 mod 数达到数千，
   应优先提供 `--max-mods` 类采样参数而不是引入持久化索引。

## 复现

```bat
set RDEBUG_RENDERDOC_PATH=<built pymodules dir>
C:\Python313\python.exe scripts\bench.py <capture.rdc> --x 320 --y 240 --repeats 4
```

Large 档：对任意真实游戏 `.rdc` 运行同一命令即可；harness 无需修改。
