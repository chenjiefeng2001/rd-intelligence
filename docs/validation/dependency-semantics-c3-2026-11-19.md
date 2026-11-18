# C3 依赖类型语义（2026-11-19）

`analysis/resource_dependency.py` 在同一资源的已排序访问上建立带类型的
依赖关系。它是纯分析层能力，不改变 MCP 协议、CI report schema 或旧 API。

## 1. 规则与证据边界

| 依赖类型 | 构建规则 | supportLevel | 能得出的结论 |
| --- | --- | --- | --- |
| `raw` | 写事件先于读事件（含 `via=copy` / `via=resolve`） | `inferred_from_order` | 事件顺序成立；内容传播未证明 |
| `war` | 读事件先于写事件 | `inferred_from_order` | 顺序成立；不声称值依赖 |
| `waw` | 相邻两次写事件 | `inferred_from_order` | 顺序成立；覆盖范围未知 |
| `copy` / `resolve` | 通过 writer 的 `accessType` 作为 `via` 标注，不单列因果类型 | 同上 | 源资源/范围未观测 |
| `subresource` | GetUsage 不暴露 mip/layer/slice | `unknown` | 显式 unresolved + reason |
| `alias` | 相同资源 ID 不证明物理别名 | `unknown` | 显式 unresolved + reason |

每条依赖携带稳定 `dependencyId`、两端事件 ID 与两条 GetUsage 证据引用。
`max_edges` 截断时具名 `truncated` / `omittedDependencyCount`，status 为
`partial`，不静默丢弃。

## 2. 真实证据

对已登记 `a-d3d11-fixture.rdc` 的 `ResourceId::47`（CopyDst@2 → 256×
PS_Resource@11..266）构建依赖索引：

```
dependencyCount = 256
byType = {raw: 256, war: 0, waw: 0, copy: 0, resolve: 0}
viaCopy = 256
supportLevels = [inferred_from_order]
truncated = false
unresolved = [subresource: unknown, alias: unknown]
```

原始数据见 `c3-real-dependency-index-2026-11-19.json`；输入来自 C2 归档的
真实 trace-resource 输出，不是合成构造。

## 3. 负向与变异控制

- 跨资源不产生依赖：N3-02 的 writer 在 `ResourceId::279`、reader 在
  `ResourceId::290`，零边（C1 归档）。
- 顺序反转产生 `war` 而非 `raw`。
- `waw` 仅按相邻写事件生成，不推断覆盖范围。
- 截断控制：限制 2 条时 `omittedDependencyCount` 等于完整数量减 2。
- 9 项 C3 单测通过（含真实样本读取测试）。

## 4. 结论

C3 建立了可检查的依赖类型规则，并在真实 Copy→Sampling 样本上得到
256 条带证据的正向 `raw(via=copy)` 依赖。内容传播、subresource 与 alias
仍严格保持 unknown，未把事件顺序升级为数据流事实。
