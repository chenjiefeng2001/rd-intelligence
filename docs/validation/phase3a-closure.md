# Phase 3a Closure 验证（Medium 档插桩）

日期：2026-08-24 · 工具：`scripts/diff_closure.py` · 原始数据：`phase3a-closure.json`
对象：`medium_frame11.rdc`（402 events / 400 draws），`diff_pixel((320,240),(10,10))`

## 结论：无语义回归、无性能回归，Phase 3a 语义冻结

| 指标 | 值 | 判定 |
| --- | --- | --- |
| diff-pixel 总耗时 | **1221.81 ms**（rerun 1197.77 ms） | 基线建立 |
| pixel_history 调用 | **恰好 2 次**（每侧 1 次，1149 ms） | ✓ 复用无回归：`diff ≈ history(A)+history(B)+~72ms 分析` |
| usage（trace-resource）调用 | **2 次**（每侧展开 1 次，34.7 ms） | ✓ 无重复展开 |
| pipeline 调用 | 18 次 / 6.5 ms | 非瓶颈 |
| firstDivergence | fragment 层，rerun 完全一致 | ✓ 语义稳定 |
| unknown 分布 | 仅 `shader_input_values` 1 层（设计内） | ✓ 未扩散 |
| Evidence 数量 / payload | 21 条 / 12.4 KB | 规模合理 |

## Semantic API v1（自此冻结）

```python
from rdebug import trace_pixel, trace_resource, debug_pixel, diff_pixel
```

四个名字为稳定公共面：签名只做**加法演进**；底层 RenderDoc API 变化由 Adapter 吸收。
未来 MCP/AI 只暴露这四个语义查询，不暴露任何原始 RenderDoc API。

## Phase 3b①（Deep Diff，默认关闭）

`diff_pixel(..., include_shader_values=True)` / `rdebug diff-pixel --include-shader-values`：
对两侧各运行一次 shader debugger，比较插值 PS 输入（如 `v0=SV_Position`、`v1=COLOR`）。

- 基础 Diff 语义**完全不变**：`unknown → same/different` 仅发生在该层内部；
  整体判定规则（有 different → different；锚点 pixel_value same → same；否则 unknown）保持不变；
- 真实验证：两个三角形像素 structural 模式该层 unknown，deep 模式变 different
  （`v0=[320.5,240.5]` vs `[330.5,240.5]`，v1 插值色不同）→ firstDivergence 正确落到该层；
- 注意：`SV_Position` 类输入随坐标必然不同——这是可证明事实，解释权在消费者；
- 采样到的纹理内容（sample 值）提取仍属后续工作，与本层无关。

跨 capture resource matching：**冻结**，不做。
