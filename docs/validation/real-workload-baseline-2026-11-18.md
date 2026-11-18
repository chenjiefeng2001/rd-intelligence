# R6.1 真实工作负载基线（2026-11-18）

本记录使用 `rdebug-validation/n3-corpus/captures/` 下**已登记的外部冻结
capture**（N3-05A1 / N3-05A2，哈希与 N3-05A freeze manifest 一致），
不使用 `tests/workload/corpus/` 的 14 个仓库自生成 fixture。测量工具为
`scripts/real_workload_baseline.py`，本地 RenderDoc / GPU 环境，
`RDEBUG_RENDERDOC_PATH` 指向 X2 pymodules。工具不是门禁，不修改 capture。

## 1. 样本与来源

| capture | 来源 | 大小 | sha256（前 12） | 用途 |
| --- | --- | --- | --- | --- |
| N3-05A1.rdc | 外部 N3 corpus（冻结 manifest） | 34,111,570 B | `8ddeb2a5e08c` | 复杂真实应用帧 |
| N3-05A2.rdc | 外部 N3 corpus（冻结 manifest） | 1,335,110 B | `7a76bf0c9e69` | 轻量真实应用帧 |

原始逐资源数据：`real-workload-05a1-2026-11-18.json`、
`real-workload-05a2-2026-11-18.json`。

## 2. 实测规模与性能

| 指标 | N3-05A1（采样 40/60 资源） | N3-05A2（36/36 资源） |
| --- | --- | --- |
| 资源总数 | 60 | 36 |
| access 行数 | 47 | 372 |
| writer 访问 | 12 | 100 |
| reader 访问 | 5 | 245 |
| **writer→reader 边** | **0** | **0** |
| overwrite 关系 | 逐资源统计见 JSON | 逐资源统计见 JSON |
| 推断关系（inferred） | 0 | 0 |
| 直接关系（direct） | 0 | 0 |
| 分析峰值内存 | 66,456 B | 230,853 B |
| 总测量耗时 | 1,176ms | 1,141ms |

## 3. 结论与边界

- 两个真实 capture 的资源访问图中**没有** writer→reader 边：writer 与
  reader 出现在不同资源上，或访问被分类为 `other`。因此 R5 合成 512 行
  图的 33,024 条边与 661ms 耗时**不代表真实 capture 的输入分布**，
  不能外推为真实负载的性能保证。
- 真实样本的分析峰值内存为 66KB–231KB，远低于合成图的 29.6MB/5.5MB；
  当前瓶颈不在关系边生成，而在 replay 与资源枚举（总耗时约 1.1–1.2s）。
- `inferred / unknown 比例`：真实样本无 inferred 关系边（因无边），
  所有未观测字段仍在 `causal.unresolved` 中显式列出；生命周期状态为
  `unknown`（无显式 create/release 事件）。
- 以下指标为 **NOT_ESTABLISHED**：生命周期完整度（GetUsage 不暴露
  create/release）、内容流（只有事件顺序）、覆盖范围（full vs partial）。
- 本轮未修改任何 capture、manifest、runner 配置或门禁；远端 replay 门仍
  按契约报 `INFRASTRUCTURE_FAILURE`。
