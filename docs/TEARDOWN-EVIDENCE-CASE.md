# TEARDOWN-CASE：RenderDoc replay 退出期访问违例（Reference Case）

> **本文件是不可变的证据案例（reference case）。**
> 它记录一次完整事故的**事实层**、**判别层**与**未建立层**，用于作为后续 replay 取证与
> 治理工作的模板。**不再对本事故追加分析。**

| | |
| --- | --- |
| 案例 ID | `TEARDOWN-CASE` |
| 事故模块 | `pymodules\renderdoc.dll` |
| 事故 PE timestamp | `0x6A8B9BA9` |
| 源码 base commit | `b7f1554feb0d7d7120f2b9280364b98972ec37d3` |
| 修复 commit | `f4b3d4fac` |
| 验证产物 SHA256 | `e1dce4d09db4c396470d90404e243edcce5fac7991393201930275f17ccdbacb` |
| 证据主文档 | `PDB-ATTRIBUTION-RESULT.md` §12–§24 |
| 状态 | **CLOSED — 阶段性闭环** |

---

## 层级一：事实（FACTS，全部为直接观测）

### F1 故障形状

| 观测 | 值 |
| --- | --- |
| RVA | `0x4A0A4E` |
| 指令 | `48 8b 18` = `mov rbx, qword ptr [rax]` |
| ExceptionCode | `c0000005`（ACCESS_VIOLATION） |
| 读地址 | `0x0` |
| `RAX` | `0x0` |
| `RBX` | 非空 |
| 源码位置 | `renderdoc/driver/shaders/spirv/glslang_compile.cpp:57`，函数 `rdcspv::Shutdown()` |
| 全局 | `glslang_inited` @ `0x171F7DC`；`allocatedPrograms` @ `0x1719780`；`allocatedShaders` @ `0x1719798`（故障构建 `.data`） |

### F2 归属过程（可复核）

| 步 | 动作 | 结果 |
| --- | --- | --- |
| 1 | 判定 `0x4A0A4E` 地址语义 | **RVA**（非文件偏移），映射 `.text` 偏移 `0x49FE4E` |
| 2 | 48 字节窗口在另一构建中搜索 | **唯一命中** RVA `0x4A0BEE` |
| 3 | 前向 46 字节比对 | 操作码与长度**完全一致**；差异仅位移立即数 |
| 4 | 行表查询 | 该地址为 `line 57` 条目的**起始地址** |
| 5 | 反汇编确认 | `cmpb`(守卫) → `je` → `mov rax,[全局]` → `mov rbx,[rax]` |

### F3 运行时判别观测（决定性）

```
tests_run         : 63    errors 0    failures 0    skipped 0
initialise_epoch  : 2
initialised       : True
sessions          : 0
shutdown_error    : <ABSENT>       ← 该键从未被插入
process exit      : -1073741819 (0xC0000005)
```

### F4 修复产物与行为对照

| | 未修复（`pymodules`） | 修复后（X2 `e1dce4d0…`） |
| --- | --- | --- |
| tests / errors / failures / skipped | 63 / 0 / 0 / 0 | **63 / 0 / 0 / 0** |
| `initialise_epoch` | 2 | **2**（触发条件复现） |
| `shutdown_error` | `<ABSENT>` | `<ABSENT>` |
| 运行中 DLL 自报 commit | — | **`f4b3d4fac3412e35f472036e1a5d344c3a7e60a1`** |
| **process exit** | **`0xC0000005`** | **`0`** |

### F5 修复改动（`glslang_compile.cpp`）

- `Init()`：早返回 → `InitializeProcess()` → 分配两容器 → **最后**置位 `glslang_inited`；第二个 `new` 包 `try/catch(...)`，失败时回滚并 `throw`
- `Shutdown()`：在 `SAFE_DELETE` 与 `FinalizeProcess()` **之后**以 `glslang_inited = false;` 收尾
- 改动限于该文件该两函数；`core.cpp` 的 N3 delta（32 行）未触碰

---

## 层级二：判别结论（DISCRIMINATING CONCLUSIONS）

### C1 根因（P-b′）

> 第一次 `rdcspv::Shutdown()` 把两个容器指针置 NULL 却**未复位** `glslang_inited`；
> 重新 `InitialiseReplay()` 时 `rdcspv::Init()` 因该标志仍为 true 而**静默跳过重新分配**；
> 进程退出时 `atexit` 路径再次执行 `rdcspv::Shutdown()`，对 NULL 解引用。

**机械链条**：`epoch==2` → 第二次初始化受 `if not initialised` 守卫 → `initialised` 置 False **只**在 `shutdown_replay()` 成功路径 → `ShutdownReplay()` 正常返回 → `clear()` 执行 → driver 重建并重新注册 → `Init()` 静默跳过 → exit-time 分发见 `0/0/1` → `0x4A0A4E`

### C2 fault identity

integration 门禁的 `0xC0000005` 与历史 teardown 崩溃为**同一故障实例**（同模块、同 RVA、同指令、同读地址、同 `RAX`）。

### C3 被排除的假说（全部保留，不抹除）

| 假说 | 裁定 | 依据 |
| --- | --- | --- |
| 「第 47 行 `new` 抛异常」 | **DISPROVEN** | 全进程仅 1 次到达顶层的异常、无 `bad_alloc`；若抛出必传播进 Python 使测试 ERROR，而实测 63/63 OK |
| **P-c** 注册表未清空 | **REFUTED** | `shutdown_error` 缺失 ⇒ `ShutdownReplay()` 未抛出 ⇒ `clear()` 必执行 |
| **P-d** driver 初始化捕获 `bad_alloc` | **EXCLUDED** | `vk_core.cpp` / `gl_driver.cpp` / `renderdoc/replay/**` 中 `catch` 命中数均为 **0** |

### C4 早期错误结论（已 superseded，保留）

`ff 50` 虚调用、vtable 为零、`0x4A0A4D` 为指令起点 —— 均 **SUPERSEDED**。
「PDB 与故障映像时间戳差 86 秒 ⇒ 错配」—— **无效**（`renderdoc.pdb` 匹配的是 `renderdoc.pyd`，两者本就是不同二进制）。

### C5 修复定性

> **结果正确、理由错误。**
> Scheme C 的原理由（`Init()` 异常安全）已被现场证据否证；但其 `Shutdown()` 复位
> `glslang_inited` **恰好切断 C1 链条第 7 步**。

**不得**回写为「方案 C 一开始就被证明正确」。

---

## 层级三：未建立（NOT ESTABLISHED）

| 项 | 状态 | 性质 |
| --- | --- | --- |
| Acceptance 3（`allocatedPrograms != NULL`） | **NOT_DIRECTLY_OBSERVED** | **工具能力缺口** |
| Acceptance 4（`allocatedShaders != NULL` / `glslang_inited` 正确） | **NOT_DIRECTLY_OBSERVED** | **工具能力缺口** |
| **verified repair** | **NOT_YET_ESTABLISHED** | 承上 |
| `pymodules\renderdoc.dll` 的生产者 | **UNKNOWN** | 仓库内无部署链可追溯 |
| MSBuild generation | **UNKNOWN** | Q1 已 `UNKNOWN / FROZEN` |

**缺口的正式性质**

> **Acceptance 3/4 direct observation blocked by debugger addressing capability.**
> X2 DLL 已由**模块范围**与**自报 commit** 两条独立证据识别；但可用 CDB 形式无法提供
> 可信的 **DLL 限定**内存读取（详见 `OBSERVABILITY-CAPABILITY-MATRIX.md`）。
> **未从歧义地址推断任何全局值。** 这是直接观测能力缺口，**非标准放宽、非实验失败、
> 非修复失败**。

> **`NOT_YET_ESTABLISHED` 不等于「修复可疑」。**
> **修复是否表现出预期行为**与**修复内部状态是否被直接观察**是两个独立命题；
> 前者已实测通过，后者因工具边界未取证。

---

## 案例方法论（本案例最具复用价值的部分）

| 阶段 | 内容 |
| --- | --- |
| 定位 | 无 PDB、无重建、无执行，用**字节等价**把 RVA 落到源码行 |
| 观测 | 读**已存在于进程、但无人读取**的字段（`initialise_epoch` / `shutdown_error`） |
| 判别 | 选择**能产生可区分结果**的观测，而非选择「听起来最像」的解释 |
| 否证 | 现场证据推翻了自己先前的根因结论，并**保留**该纠偏 |
| 验收 | 同一触发条件下 before/after 对照，而非「跑一次没崩就算过」 |

### 本案中被证伪的方法

| 方法 | 失败次数 | 原因 |
| --- | --- | --- |
| 用源码结构反推 target 名 | 1 | `pymodules` 是输出目录，不是 target |
| 把符号相对偏移当模块 RVA | 1 | `+0x6b88a0` 是相对被误符号化的导出符号 |
| 结构指纹定位函数 | 2 | 猜错栈调整量、guard 位置；误命中字符串比较与池分配器 |
| EH / `.pdata` 元数据定位 | 1 | 判据不可满足；候选不可消歧 |

> **共 5 次。** 结论：**在无 PDB 的产物上，用结构或元数据反推特定函数不可靠。**
> 本案的决定性突破来自**运行时状态**，而非任何新的静态或注入技术。

---

## 复用指引

当后续 replay 事故与本案例形态相似（退出期访问违例、跨阶段遥测缺口、需要区分竞争假说）时：

1. 先确认故障形状（模块 / RVA / 指令 / 寄存器 / 读地址），并**supersede** 旧结论而非并列
2. **不要**在没有符号时尝试结构反推；先确认是否存在匹配的 PDB 或可符号化构建
3. 优先**读已有运行时状态**，而不是设计新的探针
4. 为每个候选假说**预先声明可区分它的观测**，再执行
5. 验收必须 before/after 同条件对照；**「没有崩」不等于「内部状态正确」**
6. 不可区分时**保持并列**，不要选边

冻结点：`b89797d`。
