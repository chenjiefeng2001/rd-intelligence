# C1/C2 资源访问能力覆盖与正向关系验证（2026-11-19）

本记录解决 R6 遗留的能力判断问题：真实样本零边只能说明样本未观测到
writer→reader 关系，**不等于**分析器在真实工作负载上无法识别关系。
本轮使用已登记、哈希匹配的现有 capture，**不重复采集**，不修改门禁。

## 1. 样本来源与登记状态

| capture | 登记位置 | sha256（前 12） | 性质 |
| --- | --- | --- | --- |
| `a-d3d11-fixture.rdc` | `rdebug-validation/manifest.json`（W1-R1，role=primary） | `244c37645163` | 已登记的确定性 D3D11 fixture stand-in |
| `b-d3d11-fixture.rdc` | 同上 | `57da7653963c` | 同上 |
| `N3-02-d3d12-basic_frame120.rdc` | `n3-corpus/manifest.json`（acquired） | `94f932cc415d` | 外部 D3D12 capture |
| `N3-05A1.rdc` / `N3-05A2.rdc` | `n3-corpus/manifest.json`（provenance verified） | `8ddeb2a5e08c` / `7a76bf0c9e69` | 外部 Vulkan capture |
| `N3-03-execute-indirect_frame150.rdc` | `n3-corpus/manifest.json`（acquired） | `9f13ebdd8a54` | 已知 F-N3-1 回放崩溃，NOT_ESTABLISHED |

## 2. C1：现有 capture 的场景覆盖矩阵

| 目标场景 | 现有输入 | 覆盖状态 |
| --- | --- | --- |
| Copy → Sampling（写后读） | a/b-d3d11-fixture：`CopyDst@2` → `PS_Resource@11..` | **已覆盖（正向）** |
| Render Target 写入 → 后续纹理采样 | 现有样本未出现同一资源上的 RT→PS 组合 | NOT_ESTABLISHED |
| Compute UAV 写入 → SRV 读取 | 现有样本未出现 | NOT_ESTABLISHED |
| Depth 写入 → Depth 使用 | 现有样本未出现 | NOT_ESTABLISHED |
| Copy/Resolve → 后续读取 | Copy 已覆盖；Resolve 未出现 | 部分覆盖 |
| 多 Mip / Array Layer | `GetUsage` 不暴露 mip/layer/slice | NOT_ESTABLISHED |
| 无关系 / 负向场景 | N3-02（写资源 279、读资源 290 不同）；N3-05A1/A2（零边） | **已覆盖（负向）** |
| ExecuteIndirect | N3-03 回放崩溃（F-N3-1） | NOT_ESTABLISHED |

## 3. C2：正向关系实测

`a-d3d11-fixture.rdc` 的 `ResourceId::47`（2D Texture）：

```
writer: event 2  usage CopyDst        (1 个)
readers: events 11,12,...266  usage PS_Resource (256 个)
edges: 256 条，全部 supportLevel=inferred_from_order、status=inferred
每条边 evidenceRefs=2（writer + reader），可追溯到 GetUsage 原始事件
```

`b-d3d11-fixture.rdc` 的 `ResourceId::47` 给出同样形态：1 writer、128
readers、128 条边。原始输出见 `positive-copy-sample-*-2026-11-19.json`。

负向对照：N3-02 的 writer 在 `ResourceId::279`（Swapchain Image）、
reader 在 `ResourceId::290`（Buffer），跨资源不生成边；N3-05A1/A2 无
同资源 write→read 组合，边数为 0。这些零边样本保留为有效负向证据。

## 4. 证据纪律

- 边仍为 `inferred_from_order`：事件顺序可观测，**内容传播未被证明**。
- Copy 的源资源、copy 范围、mip/layer、coverage 均未在 `GetUsage` 中暴露，
  保持显式 unknown；不因为存在 CopyDst 就声称完整复制关系。
- a/b 是已登记的确定性 fixture stand-in，**不是真实游戏 capture**；
  这里证明的是「分析器能在真实 replay 事件上识别 Copy→Sampling 的
  writer→reader 关系」，不外推为所有真实图形工作负载已验证。
- N3-03 崩溃是可复现的已知缺陷，按 F-N3-1 保持 NOT_ESTABLISHED，
  不作回归判定，也不通过重试掩盖。

## 5. 结论与下一步

C1/C2 完成：现有输入已覆盖 Copy→Sampling 正向关系和三类负向/无关系场景。
未覆盖场景（RT→Sampling、Compute UAV→SRV、Depth、Resolve、Subresource）
需要通过后续 capture 或可控合成 fixture 补齐；C3 将扩展依赖类型语义，
C4 将评估 adapter/replay 是否能提供 mip/layer/offset/extent。
