# C4 Subresource / Region / Coverage 能力核查（2026-11-19）

## 1. 结论先行

`GetUsage` 本身不暴露 subresource（`EventUsage` 只有 `eventId` 与 `usage`），
但 replay controller 的 `GetDescriptorAccess()` + `GetDescriptors()` 能提供
绑定视图的 mip/layer/byte 范围与真实资源引用。因此 subresource/region
**可以建立真实能力**，无需继续把它全部标为 unknown；alias 与内容传播仍
保持 unknown。

## 2. 实现与受控面

- 新增 `src/rdebug/adapter/descriptors.py`，在同一 Layer 1 包内读取
  descriptor access，并结构化输出 `resource/view/firstMip/numMips/
  firstSlice/numSlices/byteOffset/byteSize/stage/type`。
- `src/rdebug/analysis/subresource.py` 负责把 descriptor 行挂到对应读访问、
  计算覆盖分类、比较 mip/layer/byte 范围。
- **`adapter/core.py` 未修改**：通过相邻模块复用 session 的 replay controller，
  Gate 4 受控面与 `archived_at_commit` 保持不变，不触发重归档。

## 3. 真实证据

对已登记 `a-d3d11-fixture.rdc` 的 `ResourceId::47`、事件 11 与 12 运行
`scripts/subresource_probe.py`（原始数据 `c4-subresource-probe-2026-11-19.json`）：

```
event 11: resource=ResourceId::47 view=ResourceId::48
          firstMip=0/1  firstSlice=0/1  byteOffset=0 byteSize=0
event 12: 同上
coverage: accessEventCount=2, analyzedEventCount=2,
          unobservedEventCount=0, missingInputEventCount=0, status=complete
```

这是真实 replay 返回的绑定视图范围，不是从事件顺序推断出来的。
byte 字段为 0 表示纹理视图没有字节范围语义，不得解读为「读到了 0 字节」。

## 4. 仍保持 unknown 的项

- **Alias**：资源 ID 相同不证明底层分配复用；descriptor 不提供物理分配身份。
- **内容传播**：subresource 范围相同只说明绑定视图一致，不证明写入内容被该次
  读取消费；依赖边仍为 `inferred_from_order`。
- **Coverage**：只对 descriptor-backed 读事件成立；非 shader-bound 访问、
  GetUsage-only 事件和缺输入行分别归入 `unobserved` / `missingInput`，
  三类互斥，不允许合计超过总事件数。

## 5. 控制

7 项 C4 单测覆盖：匹配资源挂载、缺事件显式 unknown、覆盖三类互斥、
空输入 unknown、范围比较、unknown 不产生正向匹配、缺字段 unknown。
真实探针只在有 replay 的本地环境运行，不进入 unit 门。

## 6. 结论

C4 把 subresource/region 从「一律 unknown」推进到「有描述符证据时可解析、
无证据时仍显式 unknown」，并建立了可审计的 coverage 分类。alias 需要
独立身份证据，保持 NOT_ESTABLISHED，不因 ID 相同而合并生命周期。
