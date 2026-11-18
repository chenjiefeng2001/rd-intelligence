# R6.4 按需查询下推优化（2026-11-18）

本批次由 R6.3 的分项数据触发：512 规模的主成本是整图 JSON 序列化
（519ms），而非候选匹配（0.08ms）或边生成（39ms）。因此优化目标是
**避免不必要的整图物化与序列化**，不是重写 writer×reader 枚举。

## 1. 实现

- `iter_writer_reader_edges` 接受 `resource_ids` 与 `from_event_min/max`、
  `to_event_min/max`，在构造关系对象**之前**下推过滤。
- `query_relations_stream` 暴露轻量流式查询（inclusive 范围语义，与 R5.3
  `query_relations` 的精确匹配语义明确区分）。
- `summarize_relations` / `summarize_query_relations` 只做 bisect 计数，
  不构造 relation 对象、不序列化。
- 截断语义不变：`stats["emitted"]`、`stats["omitted"]` 与 `max_edges`
  保持一致；筛选本身不计入 `omitted`。
- 所有筛选结果保留原 `supportLevel` / `status` / `unknown`，不改写确定结论。

## 2. 等价性与收益

工具 `scripts/bench_query_pushdown.py`，纯逻辑合成行，tracemalloc 关闭，
10 次重复，筛选条件 `toEventMax` 取输入中点。原始数据见
`query-pushdown-r64-2026-11-18.json`。

| 规模 | 全量构建+序列化+筛选 p50 | 下推流式 p50 | 结果边数 | 关系集合一致 |
| --- | --- | --- | --- | --- |
| 8 | 0.57ms | 0.038ms | 5 | 是 |
| 64 | 17.7ms | 0.33ms | 144 | 是 |
| 512 | **660ms** | **12.5ms** | 8,320 | 是 |

下推路径避免构造与序列化无关的 33,024-8,320 = 24,704 条边对象；
两条路径返回的 `(fromEventId, toEventId)` 集合完全相同。

## 3. 语义约束核对

- 完整关系结果仍等价：全量测试 34 项 + 查询/解释专项 13 项通过。
- `max_edges` 截断仍报 `truncated` / `omittedEdgeCount`，`analysisStatus=partial`。
- 筛选结果仍标 `partialBySelection`，上游 `truncatedSource` 可见。
- subresource / region / coverage / alias 仍为显式 unknown；推断关系仍为
  `inferred_FROM_order`，`canConcludeContentFlow` 恒 false。
- stable ID、旧 API 字段、MCP 签名、CI report schema 均未改变。

## 4. 边界

该收益针对查询/筛选场景与合成大图；R6.1 的真实 N3-05A1/A2 capture 均产生
0 条 writer→reader 边，因此本优化**不解决**真实样本中未出现的瓶颈，
也不被宣称已验证真实大图。远端 CI 仍为 `BLOCKED_INFRA`，本批次未触碰
其前置条件或门禁分类。
