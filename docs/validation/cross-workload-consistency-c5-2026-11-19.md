# C5 多真实工作负载一致性核查（2026-11-19）

数据来自已登记、哈希匹配的现有 capture；原始数据
`c5-cross-workload-check-2026-11-19.json`。本记录不新增采集，不改门禁。

## 1. 跨工作负载结果

| 工作负载 | 资源/access | writer/reader | 边/依赖 | 生命周期 | analysisStatus |
| --- | --- | --- | --- | --- | --- |
| a-d3d11-fixture | 12 / 779 | 258 / 513 | 256 | unknown | partial |
| b-d3d11-fixture | 12 / 395 | 130 / 257 | 128 | unknown | partial |
| N3-02（D3D12） | 13 / 16 | 2 / 1 | 0 | unknown | partial |
| N3-05A1（Vulkan） | 60 / 47 | 12 / 5 | 0 | unknown | partial / unknown |
| N3-05A2（Vulkan） | 36 / 372 | 100 / 245 | 0 | unknown | partial / unknown |

正向样本的依赖明细：a 为 256 条 raw、全部 `via=copy`；b 为 128 条 raw、
全部 `via=copy`；两者 `truncated=false`、`supportLevel` 集合仅为
`inferred_from_order`，没有 direct 关系。

## 2. 一致性结论

- **正负场景分离稳定**：有同资源 CopyDst→PS_Resource 的 fixture 产生正向边；
  写/读落在不同资源的 N3-02 与无组合的 N3-05A1/A2 保持零边。零边样本未被
  改写为正向，正向样本未因顺序过滤丢失关系。
- **生命周期一致为 unknown**：所有工作负载都没有显式 create/release 事件，
  `build_lifetime` 一致给出端点 unknown + reason，没有用首末访问冒充边界。
- **证据边界一致**：所有依赖边都是 `inferred_from_order`；内容传播、
  subresource（在 C4 探针之前）、alias 均未升级为 observed。
- **已知不可执行输入**：N3-03-execute-indirect 回放崩溃（F-N3-1），
  保持 NOT_ESTABLISHED，不纳入一致性 PASS 的计数。

## 3. 覆盖缺口（仍开放）

- RT 写入→采样、Compute UAV→SRV、Depth 写入→使用、Resolve→读取：
  现有已登记 capture 未覆盖，需后续输入或可控 fixture。
- 多 Mip / Array Layer 的 writer→reader 子资源匹配：C4 已证明 descriptor
  可提供绑定视图范围，但尚未在多 mip/layer 的真实 capture 上验证。

## 4. 结论

C5 完成：依赖与生命周期语义在 5 个真实工作负载上表现一致，正负场景分离
可复核。剩余缺口是输入覆盖而非分析器自洽性，下一步由具体输入或需求驱动，
不以新增字段或 CI 收口代替。
