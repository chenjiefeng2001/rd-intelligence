# Benchmark 归档（Gate 4 / DESIGN_SPEC §4.4 存档）

日期：2026-10-16
代码基线：`732a0d0`（工作树 clean；`archived_at_commit` 的机器可读声明见
`benchmark-archive-manifest.json`）
环境：Windows 11 / RTX 3070 Laptop / Python 3.13.1 / 自建 `renderdoc.pyd`
（fork `b7f1554` + 双声明 patch；`pymodules/renderdoc.dll` = X2 `e1dce4d0…`）
工具：`scripts/bench.py`（`--repeats 4`，warm best = 重复执行的最好值；冷启 =
`CaptureSession` 首次打开含 replay init）
像素：(320, 240)，`max_draws=16`

## 为什么存在本归档

§4.4 的要求是「session/latency 数据变更需附 `docs/validation/` 存档」。
此前它是 PROCESS_ONLY 的过程要求；现在 Gate 4 可执行化
（`scripts/benchmark_archive_gate.py`），判定方式是**变更耦合**：清单声明
「测量所对应的代码提交」与「受监控的 session/latency 面」，门验证归档仍
覆盖当前代码。本归档是初始覆盖点：**在当前代码上实测采得**，不是沿用
2026-08-24 旧 `perf-baseline.md` 的数据充当新证据（那份保留为历史）。

## 结果总表（ms；cold = 首次，warmBest = repeats 内最好）

| 查询 | w00001（4 events / 1 draw） | w00512（515 events / 512 draws） |
| --- | --- | --- |
| 打开会话（含首次 replay init，cold） | 3077.2 | 2731.24 |
| flattenAllEvents | cold 0.48 / warm 0.03 | cold 4.99 / warm 4.04 |
| pipelineSnapshot@lastDraw | cold 0.86 / warm 0.21 | cold 4.90 / warm 0.42 |
| pixelHistory（同像素） | cold 13.15 / warm 4.44 | cold 2347.63 / warm 1559.29 |
| tracePixel（同像素，max_draws=16） | cold 6.49 / warm 5.83 | cold 2176.85 / warm 2088.02 |
| tracePixel（3 个不同像素） | 5.18 / 7.94 / 6.70 | 89.42 / 2598.53 / 3041.18 |
| debugPixel（max_steps=4096） | cold 212.65 / warm 184.85 | cold 4529.50 / warm 3587.60 |
| traceResource（输出目标） | cold 0.32 / warm 0.17 | cold 49.30 / warm 42.34 |

原始 JSON（本门清单所列、哈希登记）：
`benchmark-archive-2026-10-16-w00001.json`、
`benchmark-archive-2026-10-16-w00512.json`。

## 再归档的流程

1. 在受监控面（见清单 `monitored_paths`）变更后：运行 `scripts/bench.py`
   于代表性 capture（至少小/中两档），把原始 JSON 与本文件同目录存档；
2. 更新清单：新增 `archive_files` 条目（含 sha256），把 `archived_at_commit`
   推进到新的 HEAD；
3. 门即回到 PASS。归档文件被修改（哈希不符）或受控面有变更而无新归档，
   门判 REGRESSION——那是内容事实，不是基础设施问题。

## 已知边界

- 本归档不证明「无性能回归」——它只证明归档覆盖当前代码。回归检测属
  `cold_warm_equivalence`（语义等价）与 D6 类性能对照，均不属本门。
- w00512 的不同像素 trace 差异（89→3041ms）反映该像素被修改的次数，
  与 2026-08-24 基线观察到的形态一致。
