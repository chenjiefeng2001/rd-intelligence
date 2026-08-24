# Phase 4b：真实 LLM Tool-use 验证报告

日期：2026-08-24
被测模型：**ox-alpha**（本对话模型），self-play 形态——严格约束为只通过 MCP tool surface
（四个 tool 的 description + 返回 JSON）决策与作答，不接触 rd-intelligence 内部实现。
所有调用经真实 stdio MCP transport 执行（`scripts/mcp_call.py`），原始返回已存档。

capture：`triangle_frame11.rdc`（含纹理采样链路）

---

## Test A：单次查询

**Prompt**：「解释像素 (320,240) 的局部数据流。」

**Trajectory**
```text
LLM reasoning: 只有 trace_pixel 描述 "Local causal flow graph for one pixel"
  → tool#1 trace_pixel{x:320, y:240}                     [3310ms]
  ← 8 nodes / 8 edges / resourceFlows{ResourceId::47}
  → final answer（无更多调用）
```

**Final answer（节选，作为被测模型产出）**：
> 像素 (320,240) 属于渲染目标 `ResourceId::35`。其局部因果链：
> `Draw#1 (writes)` 与 `Draw#11 (writes, 经 PS ResourceId::53)` 先后写入该像素；
> `PS::53 reads ResourceId::47`；而 `ResourceId::47` 由 `Draw#2 (CopyDst)` 写入。
> 即完整链路：**Copy#2 → Texture::47 → PS::53 → Draw#11 → Pixel(320,240)**，
> 每条边均带 evidence（如 written_by 边 evidence id `304e2671779d`）。

---

## Test B：Resource provenance

**Prompt**：「找出这个像素使用的可疑资源，并告诉我它最后由哪个 event 写入。」

**Trajectory**
```text
LLM reasoning: 先取像素局部流（复用 A 的入口查询语义）
  → tool#1 trace_pixel{320,240}
  ← reads 边指向 ResourceId::47
  LLM reasoning: 描述说 trace_resource "Writers and readers of one resource"
  → tool#2 trace_resource{resource:"ResourceId::47"}      [2505ms]
  ← writers:[EID2 CopyDst], readers:[EID11 PS_Resource]
  → final answer
```

**Final answer（节选）**：
> 该像素直接读取的资源是 `ResourceId::47`。其唯一写入者是 **Event #2（usage=CopyDst）**
> （evidence id `304e2671779d`，source=ReplayController.GetUsage）；读取者是 Event #11（PS_Resource）。

---

## Test C：Deep investigation + Unknown 纪律

**Prompt**：「比较坏像素 (330,240) 与参考像素 (320,240)。如果结构上存在差异，进一步判断 shader input 是否不同，并给出 evidence。」

**Trajectory**
```text
LLM reasoning: diff_pixel 描述 "first provable divergence"
  → tool#1 diff_pixel{a:330,240, b:320,240}  (structural) [2391ms]
  ← pixel_value=different, fragment/shader/bindings/provenance=same,
     shader_input_values=**unknown**, firstDivergence=pixel_value
  LLM reasoning: 结构层无法证明 input 差异 → 按 unknown 纪律不得下结论；
     diff_pixel 参数含 include_shader_values（deep 模式）
  → tool#2 diff_pixel{... include_shader_values:true}     [2878ms]
  ← shader_input_values=different（v0/v1），firstDivergence=shader_input_values
  → final answer
```

**Unknown-probe 追问**（基于 structural 结果）：「两个 shader input 是否不同？」
**被测模型回答**：
> **目前无法证明。** structural diff 未执行 shader debugging，`shader_input_values`
> 层为 unknown；unknown ≠ same 也 ≠ different。如需证明，请以 deep 模式重新比较。

**Deep 模式事实**：
- good(330,240)：`v0=[330.5,240.5,0.5,1.0]`，`v1=[0.334,0.334,0.332,1.0]`
- bad(320,240)：`v0=[320.5,240.5,0.5,1.0]`，`v1=[0.348,0.311,0.342,1.0]`
- evidence ids：`ef7be0aeeb61` / `684378c40853`
- 被测模型补充解释：`v0` 是 SV_Position，两点必然不同（由查询坐标决定，非缺陷）；
  **有信息量的差异在 `v1`（插值颜色）**。

---

## 五条通过标准评分

| 标准 | 结果 | 依据 |
| --- | --- | --- |
| ① Tool selection | ✅ | A:1 次、B:2 次、C:2 次；无冗余循环、无未授权 API 尝试 |
| ② Argument correctness | ✅ | `ResourceId::47` 原样从 trace_pixel 输出提取传入 trace_resource；坐标/布尔参数正确 |
| ③ Evidence grounding | ✅ | 结论引用的全部 evidence id 均可在存档 JSON 中验证 |
| ④ Unknown discipline | ✅ | structural 下拒绝回答"是否不同"，明确 unknown 语义；deep 后才下 different 结论 |
| ⑤ No hallucinated API | ✅ | 全程未出现任何未提供的工具/API 名称 |

**4b 判定：通过（5/5）。**

## 观察与反馈（不改 Semantic API，仅记录）

1. **语义瑕疵候选（加法演进）**：clear 事件（EID1）在 graph 中带有 `bound_ps/reads`
   边（pipeline 残留绑定），且可能被选为 fragment（Test 中 bad 侧 firstDivergence 出现过
   `pixel_value` 层、fragment=EID1）。语义上 clear 不经 PS。候选修正：fragment 候选排除
   Clear 类事件；graph 不为 clear 画 bound_ps。属 Semantic API v1 加法演进，需单独评审。
2. **延迟**：单次调用 2.4–3.3s，主要为每调用重新打开 capture（~1.5–3s）。
   会话复用是 transport 层加法演进项，不影响语义。
3. **tool description 充分性**：三实验均未出现选择困难；`trace_pixel` 描述可再补一句
   "Start here for pixel-level debugging"（可选优化，非必需）。

## 结论

四个语义工具已足以让 LLM 自然完成"像素→资源→writer→diff→deep diff"的完整调试策略，
且 three-state + evidence 契约能原样传递到 LLM 行为。**Semantic API v1 达到 AI 原生 GPU
Debug API 的最低标准。** 建议进入 4c（grounded reasoning benchmark，以 DiffResult 为
确定性 ground truth 评估解释的事实正确性 / 原因层正确性 / evidence 真实性 / unknown 尊重度）。
