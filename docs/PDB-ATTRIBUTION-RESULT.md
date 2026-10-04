# RenderDoc PDB / Source Attribution — Phase 1 Result

Date: 2026-10-01
State: **PARTIAL — function and source attribution NOT_ESTABLISHED**
Predecessor: `f579b6d` (fault location), `afbd3fa` (freeze boundary).

Scope: attribution only. **No production code changed, no RenderDoc change, no
fix attempted.** The question of whether modifying upstream RenderDoc is in
scope remains unanswered and was not needed to reach this result.

---

## 1. Stop condition reached

The authorization was explicit:

> If step 1 proves the PDB does not cover that address, stop immediately at
> **NOT_ESTABLISHED** and do not keep inferring from a nearby address.

Step 1 proved the local PDB does not yield a function or source identity for the
faulting address. Stopping there.

## 2. What the PDB search actually established

The module's own debug directory is unambiguous and points at a PDB that exists
on disk:

```
CODEVIEW  RSDS - GUID: {50E88A80-9646-42CB-AD98-05A8D01C46CE}
          Age: 1
          Pdb: D:\renderdoc_no_mcp\renderdoc\x64\Release\pymodules\renderdoc.pdb
```

`renderdoc.pdb` (4.03 MB) is present in that exact directory, and the `.dll`
(24.29 MB) is beside it. GUID and age match, so this is the right file for the
right binary.

`ld renderdoc` then reported **`Symbols loaded for renderdoc`** — and yet every
address resolution still came back as a **nearest export**:

```
ln rip → renderdoc_7ffb0aab0000!RENDERDOC_EndProfileRegion+0x2a6eee
```

`lm` shows the module as **`(export symbols)`**, not `(pdb)`. cdb emitted
`Unable to verify checksum` for both renderdoc images; the PE optional header
carries `CheckSum: 0`.

**Conclusion: the PDB is present and correctly identified, but no private
symbol resolves at the faulting offset.** No function name, no source line, no
`uf`, no `lni`. A nearest export is not function identity and is not used here.

## 3. A correction to the earlier frozen record

`f579b6d` recorded the faulting module as "renderdoc" and this investigation
first read that as the Python extension. It is not.

`lm` in the crashing process shows **two** modules:

```
00007ffb`0aab0000 00007ffb`0c32d000  renderdoc_7ffb0aab0000  (export symbols)  ...\pymodules\renderdoc.dll
00007ffb`a47c0000 00007ffb`a4df6000  renderdoc              (deferred)        ...\pymodules\renderdoc.pyd
```

The faulting frame, `renderdoc_7ffb0aab0000!…+0x2a6eee` at `0x7ffb0af50a4e`,
lies inside the **first** range — so the fault is in **`renderdoc.dll`**, span
`0x87D000`, not in `renderdoc.pyd` (span `0x636000`).

This also explains a false result I nearly accepted. An earlier `ln
renderdoc+0x4A0A4E` resolved against a *different* base and disassembled to
ASCII garbage (`ge_fill`, `in meth`) — string data, not code. The unqualified
name `renderdoc` was bound to the wrong image. Had that been read as the fault
site, the attribution would have been nonsense built on a string table. The
offset `0x4A0A4E` is consistent; the module identity needed pinning to
`renderdoc.dll` for it to mean anything.

## 4. What is established, at instruction level

From cdb's own exception context, which is authoritative regardless of symbol
availability:

```
renderdoc_7ffb0aab0000!RENDERDOC_EndProfileRegion+0x2a6eee:
00007ffb`0af50a4e 488b18   mov  rbx,qword ptr [rax]
00007ffb`0af50a51 4885db   test rbx,rbx
00007ffb`0af50a54 7428     je   renderdoc_7ffb0aab0000!…+0x2a6f1e
```

with `rax = 0x0000000000000000` and `ExceptionCode: c0000005`,
`Attempt to read from address 0`.

So the faulting instruction is a **`mov` of a qword through a null `rax`**, and
the very next two instructions are a **null test on the loaded value** — a guard
that checks the wrong level. Whatever this code intends to inspect, it dereferences
before it establishes that the thing it is dereferencing through exists.

That is a statement about the instruction sequence, which is measured. It is
**not** a statement about which object `rax` was meant to hold, why it was null,
or which subsystem owns it.

## 5. Explicitly not established

- **Which function.** No private symbol. `RENDERDOC_EndProfileRegion` is a
  nearest export and is very probably wrong for an image-teardown path; it is
  recorded as an unresolved address, not a name.
- **Which source statement.** Requires symbols.
- **Which static, and whether it belongs to the replay subsystem.** The earlier
  stack showed CRT `execute_onexit_table` → C++ static destructors, which
  establishes *phase*, not *owner*. This phase adds no ownership evidence.
- **What `rax` should have pointed at.** Unknowable without symbols or source.
- **Whether upstream RenderDoc is at fault.** Nothing here says so. A null
  `rax` during module teardown may originate in RenderDoc, in a driver, or in
  state our own usage left behind.

## 6. What it would take to go further, and why it is not done here

The missing piece is private symbol coverage, not more debugger work. Options,
none attempted:

1. A full (non-reduced) PDB for the exact `renderdoc.dll` build
   (`Time Stamp 6a8b9bfe`, `2026-08-24`), which requires rebuilding RenderDoc
   with complete debug info.
2. A RenderDoc source build consulted at the offset, once the enclosing function
   is known — which is exactly what is unknown.

Both are outside this repository and outside the current authorization.

## 7. Non-goals observed

No production code changed. No RenderDoc source or binary modified. No
destructor "fix", no exit-path workaround, no `os._exit`, no wrapper, no
exit-code masking. Teardown root cause remains **OPEN / NOT_EXPLAINED**. The
accounting Contract and the frozen `f579b6d` accounting are untouched; this
document corrects the module identity recorded there without altering its
conclusions. No mechanism inferred from the nearest export name.

## 4. 指令记录与磁盘字节不符（2026-10 由只读反汇编发现）

> **本节结论已被运行时直接测量推翻。权威记录见
> `docs/TEARDOWN-CRASH-INVESTIGATION.md` §13。** 以下静态解码结果**不再作为
> 事实**，保留仅作为错误记录。

曾对 `renderdoc.dll` 静态读取并解码故障偏移附近的机器码，得到：

```
0x4A0A42: 48 8b 03        mov rax, qword ptr [rbx]
0x4A0A45: 48 8b cb        mov rcx, rbx
0x4A0A48: 83 fa 01        cmp edx, 1
0x4A0A4B: 75 20           jne 0x4A0A6D
0x4A0A4D: ff 50           call qword ptr [rax+0x0]
```

**运行时实测（权威，`.exr` + `db` + `u` 于 AV 停点）**：

```
0x4A0A3E: 8b 05 3c 8d 27 01   mov     eax, dword ptr [rip+...]
0x4A0A44: 48 89 5c 24 30      mov     qword ptr [rsp+30h], rbx
0x4A0A49: 48 89 7c 24 20      mov     qword ptr [rsp+20h], rdi
0x4A0A4E: 48 8b 18            mov     rbx, qword ptr [rax]     <== 故障指令
0x4A0A51: 48 85 db            test    rbx, rbx
0x4A0A54: 74 28               je      +0x28
```

### 4.1 三处不符（均以运行时实测为准）

1. **`48 8b 18` 并非在 ±96 字节内出现 0 次** —— 实测该三字节就在故障地址
   `0x4A0A4E`。
2. **故障指令首字节是 `0x4A0A4E`，不是 `0x4A0A4D`** —— `0x4A0A4E` **就是**
   故障指令地址，且该处字节为 `48 8b 18`。`0x4A0A4D` 是 `0x4A0A49` 处
   `mov qword ptr [rsp+20h], rdi` 的末位立即数字节，**不是指令起点**。
3. **故障不是经 vtable 的虚调用** —— 故障指令是 `mov rbx, qword ptr [rax]`，
   即从 `rax` 读取。故障时刻 `rax == 0`，而被解引用的是 `rax`。

`renderdoc.dll` 的 mtime 为 **2026-08-24**，早于全部崩溃记录（2026-09/10），
期间未被替换；静态解码与运行时实测不一致时，以**从实际加载映像取得的运行时
字节**为准。

### 4.2 故障形状（修正后）

故障形状与本文件**最初**记录的一致：`mov rbx, qword ptr [rax]`，且
`rax == 0`。运行时寄存器读数：

```
RAX = 0000000000000000     (空 —— 故障解引用源)
RBX = 00007ffb`0c1edc80    (非空，有效栈地址)
[RBX] = 00000000`00000001  (可读，值为 1，非零)
RIP = image offset 0x4A0A4E
```

因此 **`rbx` 与 `[rbx]` 均不是故障源**；先前「`rax == 0` 意味着 `[rbx] == 0`，
即对象首 qword 为空」的推断**不成立** —— 实测 `[rbx]` 为 1。

空检查（`test`/`je`）位于解引用**之后**，允许 NULL 抵达读取；这是指令序列的
可测属性，非归因。

`0x4A0A3E` 处的 `mov eax, dword ptr [rip+...]` 是 **32 位**写入，执行后
`RAX` 高 32 位被清零 —— 这是**反汇编观察与寄存器状态的直接事实**。
`[rip+...]` 对应哪个符号、哪个对象、哪个 static，以及其值为零的原因，
**均未确立**，属下一层归因，需独立授权。

### 4.3 这不改变什么

function attribution 仍为 **NOT_ESTABLISHED**。`ln @rip` 在本地 PDB 与符号
服务器路径下仍只给出最近导出符号（`RENDERDOC_EndProfileRegion+0x2a6eee`），
无私有符号解析；导出名不得读作函数身份。把 `0x4A0A4E` 映射到具体函数与源码
仍需符号表，属未授权的后续独立授权项。`ROOT CAUSE` 仍为 **OPEN**。

按 scope decision，**未修改 RenderDoc、未启用 WER、未采集 dump**。本节为
只读观测结果。

## 5. 本地 PDB 覆盖性：已测定为否（2026-10，只读）

§10.2 曾把「本地 PDB 是否覆盖故障偏移」记为 **untested**。现已测定，结论是
**否**，且原因明确。

方法：真实 cdb 运行，符号路径**只指向**本地目录
`D:\renderdoc_no_mcp\renderdoc\x64\Release\pymodules`（不接入符号服务器），
执行 `.reload /f` 后读 `lm m renderdoc` 与 `ln @rip`。

实测：

```
00007ffe`22200000 00007ffe`23a7d000  renderdoc_...  C (export symbols)
    Image path: ...\pymodules\renderdoc.dll
    Timestamp:  Mon Aug 24 09:17:29 2026 (6A8B9BA9)
00007ffe`b7f00000 00007ffe`b8536000  renderdoc      (deferred)
    Image path: ...\pymodules\renderdoc.pyd
    Timestamp:  Mon Aug 24 09:18:54 2026 (6A8B9BFE)
```

`ln @rip` 仍只解析到最近导出符号
（`RENDERDOC_EndProfileRegion+0x2a6eee`），**无私有符号解析**。

**原因（决定性）**：故障模块是 `renderdoc.dll`，时间戳 **`6A8B9BA9`**；而同目录
的 `renderdoc.pdb` 与 `renderdoc.pyd` 属**另一个构建**（**`6A8B9BFE`**，时间相差
约 86 秒）。因此该 PDB **不匹配**故障映像，调试器把它关联到 `.pyd` 而不是 `.dll`。
先前 §11.4 记录的 CODEVIEW GUID 与此一致：那份符号属于 `.pyd`，不是故障映像。

**因此**：函数级与源码级归因在当前材料下**无法达成**，且不再是「未测试」而是
**已测定不可行**。缺口不是「缺一份符号包」，而是**缺与 `6A8B9BA9` 构建匹配的
PDB / 可符号化构建**。§11.5 的结论与停止边界**不变且已被加强**。

不得由「同目录存在一个 PDB」推断符号覆盖 —— 这正是本节推翻的推断形态。

未修改任何代码、RendDoc、gate 或 CI accounting；未安装或下载任何符号包。

## 6. 事故构建的源码 delta 已固化为可审计 artifact（2026-10，只读取证后续）

§5 确立了事故映像的 **base commit**。本节固化该 commit 之上、**事故构建实际包含
的本地 delta**，因为它是唯一现存副本。

### 6.1 artifact 与身份绑定

| 项 | 值 |
| --- | --- |
| artifact | `fork-provenance/core-cpp-n3-headless-capture-trigger.patch`（1540 字节） |
| SHA256 | `76389727458c9a4e129ae910b5f800541dbb8e8a33a7c3a525a756999bfddd12` |
| base / source identity | `b7f1554feb0d7d7120f2b9280364b98972ec37d3`（DLL 自内嵌完整 hash，与 checkout `HEAD` `b7f1554fe` 一致） |
| exception | `n3-headless-capture-trigger`（`fork-exception.json`，schema `rdebug-fork-exception/1`） |
| scope | `renderdoc/core/core.cpp`，仅 `RenderDoc::ShouldTriggerCapture`，`include_block` 范围 |
| delta 规模 | +32 行，1 file changed |

摘要算法（可复现）：`git -C <fork> diff -- renderdoc/core/core.cpp` 的输出按 **LF**
连接、**UTF-8 无 BOM**、**无尾换行**编码后取 SHA256。

### 6.2 这**不是**什么

- **不是**新构建，**不是**修复授权，**不是**归因结果。
- **不能** retroactively 证明完整 provenance chain 曾经存在。
- **不能**宣称事故 DLL 可由当前 checkout 无条件重建。
- 未运行 `cmake`、未编译、未修改 `core.cpp` 行为、未改动 fork exception 的允许范围、
  未改动 `fork_integrity` 规则、未补写 N3 capture 历史上缺失的 provenance 文件。

### 6.3 已声明 provenance 的断裂（保持可见）

`fork-exception.json` 的 `provenance.mechanism_path = capture_mechanism.patch` 与
`recorded_path = capture_mechanism.patch_recorded`（root `../rdebug-validation`）
**在其声明位置均不存在**。因此该 delta 的声明 provenance 记录缺失，其内容此前
**只存在于未跟踪的工作树**。本节 artifact 把「唯一工作树副本」转为可审计保存物，
**但没有、也不能修复那段历史记录的缺失**。

### 6.4 与未来自编译构建的区分（必须保持）

| | 事故构建的已保存 delta | 未来自编译构建的源码 |
| --- | --- | --- |
| 来源 | 已固化的 artifact，SHA256 已记录 | 未来一次构建的输入 |
| 身份 | base commit + 本 artifact，两段均可审计 | 需**单独记录**其 base commit、delta 与构建环境 |
| 可否混同 | **不可**。二者是不同的源码状态，不得互相引用为「同一份」 | — |

若将来执行自编译，必须**另行记录**该次构建的 base commit、delta 摘要与构建环境，
**不得**引用本 artifact 作为其来源证明。

### 6.5 状态：构建可行性已测定（CMake 路径 BLOCKED）

原为 `BUILD_PREREQUISITE_UNKNOWN`。经授权的 **configure 探针**（仅 configure /
generation，**不编译任何 target**）后：

> **`BUILD_BLOCKED`（针对 CMake 路线），且真实构建机制已被识别为 Visual Studio
> 解决方案。**

**直接失败原因**（项目自身明确拒绝，非环境缺失）：

```
CMake Error at CMakeLists.txt:254 (message):
  CMake is not needed on Windows, just open and build renderdoc.sln
```

`CMakeLists.txt:253-255` 在 `WIN32` 分支上 `message(FATAL_ERROR ...)`。因此
**CMake 在 Windows 上不是本项目的构建方式**，configure 失败不代表环境缺依赖。

### 6.6 探针记录（probe record）

| 项 | 值 |
| --- | --- |
| checkout / base commit | `D:\renderdoc_no_mcp\renderdoc`，`b7f1554feb0d7d7120f2b9280364b98972ec37d3`（`HEAD` `b7f1554fe`，branch `v1.x`） |
| generator | `Visual Studio 17 2022`，`-A x64` |
| toolset / 编译器 | MSVC **19.44.35228.0**（工具集 `14.44.35207`，`cl.exe` 已定位） |
| Windows SDK | CMake 选用 **10.0.28000.0**，target `10.0.29680` |
| CMake | **3.30.3**（项目要求 ≥ 3.23.0） |
| Python（探针前核实） | 3.13.1，`include/Python.h` 与 `libs/python313.lib` 均存在 |
| 结果 | **失败**，exit 1，`Configuring incomplete, errors occurred!` |
| 直接错误 | `CMakeLists.txt:254` 的 `FATAL_ERROR`（见 §6.5） |
| 生成目录 | `C:\Users\14977\AppData\Local\Temp\opencode\rdcfg`（43 文件 / 0.26 MB，含 `CMakeCache.txt`） |

**生成目录刻意置于两个仓库之外**，因此探针未写入 fork 树：configure 前后
`git status --porcelain` 均为 `M renderdoc/core/core.cpp` + 未跟踪的
`docs/code_completion_report.md`（2 项，未变），`audit_fork_integrity` 仍
**PASS / 1 tracked / 1 declared / F1–F4 全 not present**，固化 delta 的
SHA256 亦未变。

### 6.7 真实构建机制（探针的副产品）

`renderdoc.sln` 与 `renderdoc.sln.filters` **存在**，仓库含 **26 个 `.vcxproj`**。
即 Windows 上的构建路径是 Visual Studio / MSBuild 解决方案。

**该路径的可行性仍为 `UNKNOWN`**，因为验证它需要配置或生成解决方案，而那属于
下一道门（实际编译授权），本轮未授权。**不得**由「CMake 被拒绝」推断
「解决方案构建必然可行」，也不得反向推断。

### 6.8 边界（明确未宣称）

未编译任何 target；未修改 RenderDoc 源码；未改动 fork exception、
`release-gates.json`、四状态或任何门禁语义；未安装依赖、未切换工具链、
未为促成 `FEASIBLE` 而做任何调整；未启动事故复现；未进入 attribution。

configure 成功也不会自动获得实际编译的授权——**下一道门仍是「是否授权实际编译」**。

## 7. MSBuild 生成探针：G1 / G2 / G3 结果（2026-10，只生成不编译）

探针授权范围：仅 solution 加载、项目求值与生成类 target；**不编译任何 target**；
输出重定向到两个仓库之外。

### 7.1 原始结果

| target | 范围 | exit | 耗时 | 结果 |
| --- | --- | ---: | ---: | --- |
| **G1** `ValidateSolutionConfiguration` | `renderdoc.sln` | **0** | 2.9 s | sln 解析成功、configuration 名合法 |
| **G2** `PrepareForBuild` | `renderdoc.vcxproj`，`Release\|x64` | **0** | 6.7 s | `Build succeeded`，0 error，1 warning |
| **G3** `DesignTimeBuild` | `renderdoc.vcxproj` | **1** | 4.6 s | `error MSB4057: The target "DesignTimeBuild" does not exist in the project.` |

G2 的成功同时证明：`Microsoft.Cpp.props/targets` 可加载、`$(VCTargetsPath)` 解析
正确、项目自定义的 `util\WindowsSDKTarget.props` 与 `util\WindowsSDKFix.props`
均可解析、SDK 与工具集求值通过。

**G3 无效（探针设计错误，非项目缺陷）**：该 target 属 SDK 风格项目，classic
`.vcxproj` 不提供。未替换 target 重跑以追求绿灯，故 **G3 不提供任何证据**。

### 7.2 四重「未编译」证据

| 证据 | 结果 |
| --- | --- |
| **A. binlog 编译痕迹** | G1/G2/G3 中 `LINK` = 0、`/c ` = 0；`cl.exe` 全路径仅 1 次且为**工具路径定义**，`ClCompile` 8 次为**项类型**引用。`CommandLine` 3 条经查为 `CommandLineForReferenceDependsOn`、`ResolveReferences`、`GetClCommandLineForReferenceSupported`——**均为 MSBuild 内部任务名，非编译器命令行** |
| **B. fork 产物清单差异** | `x64\Release` 基线 672 → 672，**新增 0 / 缺失 0**；`.obj` 仍为原有 391 |
| **C. 探针目录产物** | `.obj` / `.lib` / `.dll` 均为 **0**；14 个文件全为 **`.dxbc`**（着色器字节码，由项目自身 shader 预编译 task 生成） |
| **D. 时间/体积** | G2 全程 6.7 s、产物 KB 级；编译 800+ 编译单元在此时间内物理上不可能 |

**结论：未发生 C++ 编译。** 同时也**获得 shader precompile / evaluation path 的正面证据**。

### 7.3 基线三项（探针前后一致）

fork `git status --porcelain` = **2 项未变**；`audit_fork_integrity` =
**PASS / 1 tracked / 1 declared**；固化 delta SHA256 =
`76389727458c9a4e129ae910b5f800541dbb8e8a33a7c3a525a756999bfddd12` 未变。

### 7.4 取证方法的纠正（重要）

初版硬门「`cl.exe` 进程观测」**不可用**：空闲期 20/20 样本均命中 `cl` 进程（本机
有 3–10 个与本工作流无关的编译进程在运行），该指标统计的是环境噪音而非本次
msbuild 的编译器调用。

可归因的证据是 **binlog task 清单 + 产物清单差异**。任何后续探针必须以该二者为
准，不得再用进程名观测。

### 7.5 探针自身的环境差异（不得记为项目缺陷）

`MSB8029`（Intermediate/Output 位于 TEMP 可能影响增量构建）源于本次把
`OutDir`/`IntDir` 重定向到仓库之外，是**探针产物**。它同时意味着本次求值路径与
真实构建路径存在该差异。

### 7.6 冻结状态阶梯

```
CMake 路线                      = BUILD_BLOCKED（项目在 WIN32 上 FATAL_ERROR 拒绝）
MSBuild solution loading        = PASS
MSBuild project evaluation      = PASS
shader precompile / evaluation  = PASS（正面证据）
MSBuild generation              = UNKNOWN（G3 无效，无证据）
actual build                    = NOT AUTHORIZED
reproduction                    = NOT AUTHORIZED
attribution                     = NOT AUTHORIZED
```

**判定：`BUILD_GENERATION_UNKNOWN`。** G1/G2 的成功**不得**升级为完整 generation；
G3 的无效 target **不得**记为项目失败。这既不是失败，也不是需要凑绿的地方。

方案 B 的状态：**source relation 已建立，provenance delta 已固化，构建路线已从
CMake 收敛到 MSBuild，加载与求值已验证，完整 generation 仍 UNKNOWN。**

### 7.7 继续的前置条件

**不授权**继续寻找 target。若要推进，须先提出一份**新的探针定义**，回答：

> classic `.vcxproj` 在此 RenderDoc checkout 中，什么机制能够证明完整 generation
> 而不进入 C++ compilation？

并重新定义验收条件，而非把原 G3 替换掉继续跑。其中
`/p:DesignTimeBuild=true` 配合 `Build` 是否真的不编译，**需要独立证明，不得预先
假定**。

该新探针定义已冻结为 `docs/BUILD-GENERATION-PROBE.md`（P0–P4）。**P0 尚未授权、
尚未执行**；本节 §7 的实测结果不因该定义而改变。

当前**不实际编译 RenderDoc**，**不进入事故复现**，**不进入 attribution**。

## 8. P0 结果：PARTIALLY ESTABLISHED（只读，未执行任何 target）

### 8.1 产出

| 项 | 状态 |
| --- | --- |
| Target 清单（`/pp` 求值面） | **320** |
| `compilation_boundary_candidates` | `ClCompile`（→`SelectClCompile`）、`Link`（→`ComputeLinkSwitches`）、`Lib`、`ResourceCompile` |
| `generation_entry_candidates` | 完整清单 |
| `design_time_conditions` | `DesignTimeBuild` 是**属性条件**而非 target |
| `generation_dependency_chain` | **部分** —— 可达 15 个 generation 侧 target，在 `BuildCompile` 下层 property 边界停止 |
| `generation_output_candidates` | **P0 结构性不可交付**（见 §8.4） |

### 8.2 property indirection 是可观测的

`-getProperty` 对 38 个 `*DependsOn` 属性求值成功（exit 0）。关键读数：

```
BuildDependsOn          = SetTelemetryEnvironmentVariables; _PrepareForBuild;
                           ResolveReferences; PrepareForBuild; InitializeBuildStatus;
                           BuildGenerateSources; BuildCompile; …
PrepareForBuildDependsOn = _CheckWindowsSDKInstalled; GetFrameworkPaths;
                           GetReferenceAssemblyPaths; AssignLinkMetadata; …
ResolveReferencesDependsOn = _PrepareForReferenceResolution; ComputeCrtSDKReference;
                           BeforeResolveReferences; AssignProjectConfiguration; …
```

四层分离成立：top-level property expansion → effective target 序列 →
generation 侧 → compilation boundary。

### 8.3 G3 的直接证据

`/pp` 的 320-target 求值面中**不存在名为 `DesignTimeBuild` 的 target**（仅有
`DesignTimeXamlMarkupCompilation`）；`DesignTimeBuild` 实际是**属性/条件**。
故原 G3 的 `/t:DesignTimeBuild` invocation 分类为 **`INVALID_PROBE`** —— 现在由
`/pp` 直接证据支撑，而非推断。`INVALID_PROBE` 不计入项目失败。

### 8.4 方法论边界：`generation_output_candidates` 属于 P4，不属于 P0

`/pp` 保留 target **定义**，但**不保留 target 内部实际执行的 task / output
序列**。因此 generation 产物无法由只读求值得出。

> **这是 P0 的结构性不可交付项，不是探针遗漏，也不是实现缺陷。**

按 `BUILD-GENERATION-PROBE.md` §8，output closure 只能由**实际执行后的产物差异**
确定，即 **P4**。把 P0 的能力边界误记为实现缺陷，会导致后续错误地「补齐」P0。

### 8.5 探针实现缺陷（3 次，不转嫁为项目缺陷）

1. import 遍历与 target 解析复用同一 `seen` 集合 → 42 个导入全被跳过，Target 数 0
2. `os.path.relpath` 跨盘符（`D:` → `C:`）抛 `ValueError`
3. `DependsOnTargets` 中的字面量 `$(Prop)` 引用未被解析 → 链长停在 2

修正后可达 target 数由 2 升至 15。三者均为**探针实现缺陷**，与项目无关。

### 8.6 未做的事

未执行任何 target（无 `/t:Build`、`/t:ClCompile`、`/t:Link`）；未做
`DesignTimeBuild` 执行实验；未向仓库生成文件；未编译；未修改 `.vcxproj` / props /
targets；未替换 target；未进入 P1 / P2 / P3 / P4；未修改 checkout。

`BuildCompile` 下层 property 的可观测性属于**新的探针机制**，需新授权与新验收
定义，**不由当前 P0 授权自然延伸**。

### 8.7 冻结后的状态

| 项目 | 状态 |
| --- | --- |
| source relation | ESTABLISHED |
| delta provenance | SOLIDIFIED |
| CMake | BUILD_BLOCKED |
| MSBuild solution loading | PASS |
| MSBuild project evaluation | PASS |
| shader precompile / evaluation | PASS |
| **P0** | **PARTIALLY ESTABLISHED** |
| **MSBuild generation** | **UNKNOWN** |
| actual build | NOT AUTHORIZED |
| reproduction | NOT AUTHORIZED |
| attribution | NOT AUTHORIZED |

## 9. 探针主工件已固化（2026-10）

§7 / §8 引用的主工件原先只存在于 `%TEMP%\opencode\rdgen\`，临时目录会被清空。现已
固化到 `build-probe/`，并由 `build-probe/MANIFEST.sha256` 逐文件登记 SHA256。

### 9.1 工件与其证明力

| 工件 | 字节 | 它直接证明什么 |
| --- | ---: | --- |
| `renderdoc_pp.xml` | 1,339,424 | MSBuild 对 `renderdoc.vcxproj`（`Release\|x64`）的求值展开结果：**320 个 `<Target>`**；且**不存在名为 `DesignTimeBuild` 的 target** |
| `props.out` | 6,442 | `-getProperty` 对 **38 个 `*DependsOn` 属性**的求值结果（JSON） |
| `G1.binlog` | 36,560 | G1 执行的 task 清单；`LINK`/`/c ` 均 0 |
| `G2.binlog` | 300,698 | 同上；`cl.exe` 仅 1 次且为工具路径**定义**，`ClCompile` 8 次为**项类型** |
| `G3.binlog` | 287,833 | 同上 |
| `G1/G2/G3.out.txt` | 2 / 6,990 / 1,887 | exit 依据、`Build succeeded`、`MSB4057` 原文、`MSB8029` 警告原文 |
| `pp.out` / `pp.err` / `*.err.txt` | 0 | 空；`/pp` 的成功由工件本身与 exit 0 体现 |

### 9.2 边界：这是**探针工件**，不是事故构建 provenance

- 绑定 base commit `b7f1554feb0d7d7120f2b9280364b98972ec37d3`。
- 它们记录的是 **MSBuild 求值与生成探针的输出**，**不是**事故构建的输入。
- **不得**被引用为任何未来自编译构建的 provenance；未来构建须**单独记录**其
  base commit、delta 摘要、工具链与构建环境。
- 生成它们**未编译、未执行 `ClCompile`/`Link`、未修改 checkout**（见 §8.6）。

### 9.3 完整性控制

`tests/unit/test_build_probe_artifacts.py` 校验：manifest 覆盖目录内每个文件、
每个 SHA256 相符、**不存在未登记文件**，并从工件**重新推导**两项关键结论——
`renderdoc_pp.xml` 的 target 数为 320 且无 `DesignTimeBuild` target；
`props.out` 可解析且 `BuildDependsOn` 含 `BuildCompile`。

因此 §8.1 / §8.3 的数字不再只有一次性出处。

## 10. Q1 property 可观测性续探：结论为 UNKNOWN

**验收问题**：MSBuild 17.14 的 evaluation-only 能力，是否足以把
`Build → BuildCompile → ClCompile` 之间的 property indirection 完整展开成可追溯
chain？

**执行（零 target execution）**：从 `/pp` 文本枚举 `$(XDependsOn)` 属性名作为
**查询规划**（不用于构建 target 图），得到 **93 个候选**；`-getProperty` 对
**93 个全部求值成功**（exit 0）。chain 仅由 MSBuild 求值结果与 `/pp` 的
`DependsOnTargets` 构成。

**结果 —— 未达成成功判据：**

| 判据 | 结果 |
| --- | --- |
| ① 每级 property 可追溯 | ❌ chain 使用的 6 个 property 中 **3 个在 `/pp` 中无可定位定义**（`TlogCleanupDependsOn`、`_CheckWindowsSDKInstalledDependsOn`、`AddExternalIncludDirectoriesToPathsDependsOn`，求值均为空） |
| ② 展开后顺序可解释 | ⚠️ 部分。`BuildDependsOn` 的求值值**明确列出** `ResolveReferences`、`BuildGenerateSources`、`BuildCompile`，但展开结果中**三者均未出现** |
| ③ 能定位 compilation boundary | ❌ 可达 15 个 target，**未抵达** `ClCompile` / `Link` |
| ④ 零 target execution | ✅ 仅 `/pp` 与 `-getProperty` |
| ⑤ 无编译/输出副作用 | ✅ 未编译、未向仓库写文件、未改 checkout |

**结论**：即使 93 个 `*DependsOn` 属性全部求值，evaluation-only 表面**仍不足以**
把 `Build` 到 compilation boundary 的链条完整展开。判据 ①②③ 均未满足。

> **因此按授权以 `UNKNOWN` 收尾，不再设计第五种静态解析器。**

**未解释的观察（如实记录，不掩盖）**：展开在 `AddExternalIncludDirectoriesToPaths`
处终止，而 `BuildDependsOn` 中明列的 `ResolveReferences` / `BuildGenerateSources` /
`BuildCompile` 未被纳入可达集。本轮**未定位**该不一致的确切成因（可能是
`DependsOnTargets` 条目中 `$(...)` 与字面 target 混合时的展开丢失，也可能是
求值条件导致），因此**不宣称**已解释。可追溯的结论只有：**该机制不足以支撑完整
chain**。

**状态不变**：`MSBuild generation = UNKNOWN`；actual build / reproduction /
attribution = `NOT AUTHORIZED`。

### 10.1 Q1 工件已固化（probe evidence，字节级一致）

| 工件 | 字节 | SHA256（前 16） | 内容 |
| --- | ---: | --- | --- |
| `build-probe/Q1_getproperty_93.out` | 12,758 | `d4b533bb504dd7be` | `-getProperty` 对 **93 个** `*DependsOn` 属性的求值结果（JSON），**本轮原始输出，未重新执行刷新** |
| `build-probe/Q1_chain_expansion.py.txt` | 3,197 | `5e60038a24e4844c` | Q1 展开脚本本体（可达集计算与 property 可追溯性标注）。**以 `.txt` 存储**：内容与执行时**字节一致**（SHA256 未变），但避免其作为 `.py` 进入 ruff 门禁范围——修它的 lint 会破坏字节一致性 |

**身份与上下文**

| 项 | 值 |
| --- | --- |
| checkout / base commit | `D:\renderdoc_no_mcp\renderdoc`，`b7f1554feb0d7d7120f2b9280364b98972ec37d3`（`HEAD b7f155fe`，`v1.x`） |
| MSBuild | **17.14.40.60911**（commit `3e744208875e56e4bf0bc22c40a1c431fb150987`） |
| MSVC toolset | `14.44.35207`，`cl` `19.44.35228.0` |
| evaluation context | `Release\|x64`，`-p:SolutionDir=<fork>\` |
| 命令 | `msbuild renderdoc\renderdoc.vcxproj -getProperty:<93 项> -p:Configuration=Release -p:Platform=x64 -p:SolutionDir=<fork>\ -nologo` → **exit 0** |
| 未执行 | 无任何 target；无 `/p:DesignTimeBuild=true` 执行；未修改 `.vcxproj`/props/targets；未编译；未改 checkout |

**标记：probe evidence，不是 RenderDoc accident-build provenance。**
两者不得互相引用为来源证明；未来任何自编译构建仍须**单独记录**其 base commit、
delta 摘要、toolchain 与环境。

**Q1 的三条失败判据原样保留**：① property 定义无法全部追溯；② property 展开顺序
无法完整解释；③ 无法抵达 compilation boundary。

**未重新打开 Q1**：`ResolveReferences` / `BuildGenerateSources` / `BuildCompile`
为何未进入可达集，仍是**未解释事实**，本次固化**不解释**它。
完整性由既有 `tests/unit/test_build_probe_artifacts.py` 覆盖：manifest 校验每个
文件 SHA256，且目录内不得存在 manifest 未覆盖的文件。

## 11. PDB 身份只读核验：结论不变，但依据被替换

**授权范围**：只读读取本机 PDB 内嵌身份。不执行 RenderDoc、不编译、不改被观测对象。
**工具**：`llvm-pdbutil`（LLVM **19.1.5**，MSVC `Llvm\x64\bin`）。本机无 x64 版
`cvdump.exe`，故未使用。

### 11.1 本机实际存在的两个构建

| 产物 | 大小 | mtime | PE TimeStamp / PDB Signature |
| --- | ---: | --- | --- |
| `pymodules\renderdoc.dll`（**故障映像**） | 25,465,344 | 08-24 09:17 | PE `0x6A8B9BA9` |
| `pymodules\renderdoc.pdb` | 4,222,976 | 08-24 09:18 | PDB `0x6A8B9BFE`，age 1，GUID `{50E88A80-9646-42CB-AD98-05A8D01C46CE}` |
| `renderdoc.dll`（另一构建） | 25,465,856 | 08-28 21:42 | PE `0x6A91903B` |
| `renderdoc.pdb` | 153,432,064 | 08-28 21:42 | PDB `0x6A91903F` |

故障映像 `sha256 = 97cad315d1af01d7bc07bb8e09c080ffa31feecdc0c1857a42a3aa0dd9435f6e`，
machine `0x8664`，**CodeView 目录为空（无 RSDS 记录）**。

### 11.2 覆盖性判定（阳性证据）

| PDB | streams | 模块数 | 含 `core.obj` | 能描述 core 故障代码？ |
| --- | ---: | ---: | --- | --- |
| `pymodules\renderdoc.pdb` | 79 | **63** | 否——仅 `pyrenderdoc_stub.obj` / `renderdoc_module_python.obj` / `python313.dll` | **否** |
| `renderdoc.pdb` | 502 | **484** | 是——`obj\renderdoc\core.obj` | 是，但属**另一个** DLL |

### 11.3 结论

`attribution = BLOCKED_BY_EXTERNAL_INPUT` **维持**，但依据由「时间戳相差约 86 秒」
替换为**阳性证据**：本机两个 PDB 中，窄 PDB 从未覆盖 `core.obj`，全量 PDB 属于另一
个 DLL（`0x6A91903B`）。**没有任何本机 PDB 覆盖故障映像的 core 代码。**

### 11.4 方法论订正（重要）

**PE `TimeDateStamp` 与 PDB `Signature` 之差不是匹配判据。** 证据：另一构建自身的
配对为 PE `0x6A91903B` 对 PDB `0x6A91903F`，相差 **4 秒**——链接开始时写 PE 时间戳、
结束时定稿 PDB signature，**健康配对本就有正向差值**。

**正确的匹配判据是 CodeView RSDS 的 GUID + age。** 而故障映像**没有 RSDS 记录**，
该判据**无法施加**。因此原先以时间戳差推定错配在方法上不成立；结论正确属于巧合，
必须以 §11.2 的阳性证据为准。

### 11.5 一个已证伪的假设（如实记录）

本轮曾提出假设：「匹配的 PDB 或许已在本机，只是被后续链接覆盖」。**该假设被证伪。**
旁侧 4.2 MB PDB 虽与故障映像同目录、mtime 相隔 1 分钟，但它是 **narrow PDB**，
只含 pymodules 包装层，从未包含 `core.obj`。时间上的接近是巧合，不是同一次链接。

### 11.6 对 Stage 1 的直接影响

Stage 1 中「寻回 `0x6A8B9BA9` 匹配的 PDB」**无法通过索取既有文件达成**——该文件在
本机不存在。可行路径只有两条，且**都需要新授权**：

1. 从 base commit `b7f1554feb0d7d7120f2b9280364b98972ec37d3` + toolchain
   `14.44.35207` / `cl 19.44.35228.0` **重新链接一个带 RSDS 的映像**（属 actual build）；
2. 从构建过 `0x6A8B9BA9` 的外部构建机取回其归档 PDB。

**当前状态不变**：无本机 PDB 覆盖故障映像，attribution 仍被外部输入阻塞。

## 12. 归属推进：故障点已定位到源码行（零构建、零执行）

**授权范围**：以破坏性最小的方式推进。**未构建、未执行 RenderDoc、未改动任何被观测对象**；全部为只读静态分析（PE 字节读取 + PDB 查询 + 反汇编）。

### 12.1 方法链（每步可复核）

| 步 | 动作 | 工具 | 结果 |
| --- | --- | --- | --- |
| 1 | 确认 `0x4A0A4E` 的地址语义 | 自写 PE 解析 | 是 **RVA**（非文件偏移）；映射 `.text` 偏移 `0x49FE4E`，字节 `48 8b 18` = `mov rbx,[rax]` |
| 2 | 在另一构建中定位同一段代码 | 字节搜索 | **48 字节窗口唯一命中** → 新构建 RVA `0x4A0BEE`（与故障 RVA 相差 `0xA0`） |
| 3 | 前向 46 字节比对 | 字节比较 | 指令操作码与长度**完全一致**；差异仅在位移立即数（`6a→ca`、`a5→25`、`3c→bc`），与两构建数据布局相差 512 字节一致 |
| 4 | 行号解析 | `llvm-pdbutil dump -l`（LLVM 19.1.5） | 该地址为 `line/addr` 条目 `57 0049FBEE` 的**起始地址** |
| 5 | 源文件归属 | 同上 | 归属模块的路径行为 `renderdoc\driver\shaders\spirv\glslang_compile.cpp` |
| 6 | 指令级确认 | `llvm-objdump -d -l` | `1804a0bee: movq (%rax), %rbx`，其前为 `cmpb $0x0`（守卫）+ `je` + `movq ...(%rip),%rax` |

### 12.2 已确立：故障点

**`renderdoc/driver/shaders/spirv/glslang_compile.cpp:57`，函数 `rdcspv::Shutdown()` 内部。**

```cpp
52: void rdcspv::Shutdown()
54:   if(glslang_inited)
57:     for(glslang::TProgram *program : *allocatedPrograms)   ← RAX = allocatedPrograms = NULL
66:     SAFE_DELETE(allocatedPrograms);
```

反汇编与源码逐条对应（含全局地址）：

| 全局 | 地址 | 用途 |
| --- | --- | --- |
| `glslang_inited` | `0x18171f7fc` | `cmpb $0x0` 读（`if` 守卫）；`movb $0x1` 写（`Init()` 内） |
| `allocatedPrograms` | `0x1817197a0` | `movq ...(%rip),%rax` 载入 → `movq (%rax),%rbx` 解引用 |

### 12.3 已确立：静态缺陷（不依赖运行时）

`glslang_inited` 全部出现位置仅 4 处（36 声明、42 读、45 写 `true`、54 读），
**无任何位置将其复位为 `false`**。而 `Shutdown()` 在 66–67 行以 `SAFE_DELETE`
把 `allocatedPrograms` / `allocatedShaders` 置为 `NULL`。

因此不变式 `glslang_inited == true ⟹ allocatedPrograms != NULL` 在 `Shutdown()`
之后**必然被破坏**：其后的 `Init()` 因 `if(!glslang_inited)` 为假而成为**静默空操作**，
指针保持 `NULL`；再一次 `Shutdown()` 即可通过守卫并在第 57 行解引用 `NULL`。

### 12.4 已证伪的假设（如实记录）

**「重复注册导致 `Shutdown()` 被调用两次」——证伪。**
`RenderDoc::RegisterShutdownFunction`（core.cpp:1030-1034）用 `std::lower_bound`
去重，仅在不存在时插入，故 `&rdcspv::Shutdown` 只会被登记一次。
`~RenderDoc()`（core.cpp:765-767）与 `ShutdownReplay()`（core.cpp:1025-1027）
均遍历后 `clear()`，二者不会叠加调用。

### 12.5 尚未确立（不得越界）

- **运行时究竟经历了哪条序列**（是否发生 `Shutdown()` → `Init()` → `Shutdown()`，
  或 `new` 抛异常留下窗口）——需 reproduction 授权，**当前 `NOT_AUTHORIZED`**。
- 故障映像与新构建的源码同一性：已确立 base commit 为 `b7f1554fe…`，且 48 字节
  唯一匹配；但两个 PE 并非同一文件，**行号归属依赖上述字节等价性**，已如实记录其前提。

### 12.6 状态变更

| 项 | 原状态 | 新状态 |
| --- | --- | --- |
| 故障点归属 | `NOT_ESTABLISHED` | **ESTABLISHED**（文件 + 行 + 函数 + 全局地址） |
| `attribution` 阻塞原因 | `BLOCKED_BY_EXTERNAL_INPUT`（缺匹配 PDB） | **不再需要外部 PDB 即可定位故障点**；根因确认仍需 reproduction |
| 根因 | `ROOT CAUSE OPEN` | 仍 `OPEN`，但已有具体静态缺陷（§12.3）与已证伪假设（§12.4） |

**未执行**：任何 target、编译、RenderDoc 运行、复现、改动 `.vcxproj`/props/targets、
改动 `core.cpp` 或 delta。**不提出修复方案**——修复需在根因经 reproduction 确认后另行授权。

## 13. 二进制层面确认与第二个 NULL 风险点

承接 §12。仍为**只读静态分析**：未构建、未执行、未改动被观测对象。

### 13.1 `Shutdown()` 全函数反汇编（二进制级证明）

函数域 `RVA 0x4A0BC0`–`0x4A0CFA`（83 条指令），关键序列：

```
1804a0bc0: subq  $0x28, %rsp
1804a0bd0: cmpb  $0x0, 0x127ec25(%rip)      # 0x18171f7fc   ← glslang_inited，函数内唯一引用
1804a0bd7: je    0x1804a0cf6                 ← 守卫为假即返回
1804a0bdd: movq  0x1278bbc(%rip), %rax       # 0x1817197a0   ← 载入 allocatedPrograms
1804a0bee: movq  (%rax), %rbx                ← ★ 故障点
1804a0bf1: testq %rbx, %rbx                  ← 检查的是数组 begin，不是容器指针
...
1804a0cad: movq  %rdi, 0x1278aec(%rip)       # allocatedPrograms = NULL
1804a0ce0: movq  %rdi, 0x1278ab1(%rip)       # allocatedShaders  = NULL
1804a0ce7: callq 0x18043ede0                 ← glslang::FinalizeProcess()
1804a0cfa: retq
```

**两条二进制级事实：**

1. **`glslang_inited`（`0x18171f7fc`）在整个 `Shutdown()` 内只被读一次，从未被写。**
   §12.3 的静态缺陷由此从源码级升为**二进制级已证**。
2. **`allocatedPrograms` 在被解引用之前没有任何空检查。** `testq %rbx,%rbx`
   检查的是从 `*allocatedPrograms` 载入的 begin 指针，发生在解引用**之后**。

### 13.2 第二个 NULL 风险点（同一根因的另一面）

```cpp
93:   allocatedShaders->push_back(shader);      ← 无守卫
119:  allocatedPrograms->push_back(program);    ← 无守卫
```

由于 `rdcspv::Init()` 以 `glslang_inited` 为守卫，而该标志在 `Shutdown()` 后**不被复位**，
「`Shutdown()` → `Init()`（空操作）→ 再次使用」会使 93 / 119 行同样解引用 NULL。
即同一缺陷既可表现为 §12 的 `Shutdown()` 内崩溃，也可表现为**使用点**崩溃。

### 13.3 一段既有实测声明，其工件已缺失

`src/rdebug/adapter/core.py:199-222` 的注释声明：

```
Vulkan, 一次 InitialiseReplay → 0/60 崩溃
Vulkan, 两次 InitialiseReplay → 23/60 崩溃 (p~1e-8)
D3D11/D3D12, 两种情况         → 0/40 崩溃
崩溃位于 cap.OpenCapture() 内，构建 Vulkan replay driver 时，0xC0000005
```

**该声明所引用的 `reports/n3/N3-native-open-probe-*.json` 与 `reports/` 目录在本机
均不存在**，因此上述数字目前**无工件支撑**，与缺失的 `capture_mechanism.patch`
属同类证据缺口。

**因此不得据此断言 integration 的 `0xC0000005` 与本节的 `Shutdown()` 崩溃同源。**
两者同属访问违例族，但发生位置不同（一处在 shutdown，一处在 driver 构建期），
且故障地址未知。**是否同源尚未确立。**

### 13.4 状态

| 项 | 状态 |
| --- | --- |
| 故障点归属 | **ESTABLISHED**（§12，`glslang_compile.cpp:57`） |
| 缺陷本身 | **ESTABLISHED（二进制级）**：守卫变量与指针状态脱钩 |
| 根因 | **仍 OPEN**：实际运行时序列未确立 |
| 与 integration `0xC0000005` 是否同源 | **NOT_ESTABLISHED**，且既有支撑工件缺失 |
| 修复方案 | **未提出**（需先确立根因） |

## 14. C 阶段（纯静态收敛）：确立调用链，并证伪本项目自己的下一步预测

承接 §13。仍为**只读静态分析**：未构建、未执行、未改动被观测对象。

### 14.1 确立：`rdcspv::Init()` 位于 driver 构造函数内

`renderdoc/driver/vulkan/vk_core.cpp:194-195`，位于 **`WrappedVulkan::WrappedVulkan()`**：

```cpp
174: WrappedVulkan::WrappedVulkan()
...
194:   rdcspv::Init();
195:   RenderDoc::Inst().RegisterShutdownFunction(&rdcspv::Shutdown);
```

故**每一次 Vulkan driver 创建都会调用 `rdcspv::Init()`**。

### 14.2 由 14.1 机械推出的因果链

```
1  InitialiseReplay #1 → WrappedVulkan() → rdcspv::Init() → 分配，glslang_inited=true
2  ShutdownReplay()    → rdcspv::Shutdown() → 指针置 NULL，glslang_inited 仍为 true
3  InitialiseReplay #2 → WrappedVulkan() → rdcspv::Init() → 静默空操作（指针仍为 NULL）
4  再次 ShutdownReplay() 或使用点 → 解引用 NULL
```

该链条与 `src/rdebug/adapter/core.py` 的 `initialise_epoch`（同进程多次
`InitialiseReplay()` 计数）所建模的场景一致。

### 14.3 独立佐证：D3D 不崩的原因已静态解释

`rdcspv::Init()` 的调用点仅存在于 **Vulkan 与 GL**：`vk_core.cpp`(1)、
`gl_driver.cpp`(1)、`gl_emulated.cpp`(2)。**D3D11 / D3D12 既不调用
`rdcspv::Init()`，也不调用 `CompileShaderForReflection`。**

这静态解释了既有实测声明中的「D3D11 / D3D12 两种情况均 0/40 崩溃」。

### 14.4 证伪本项目自己的预测（重要）

§13 之后曾提出预测：integration 的 `0xC0000005` 应落在
`CompileShaderForReflection` 第 93 行（`allocatedShaders->push_back`），
其故障指令应为 `movq 0x10(%rdi),%rbx`（RDI=0，新构建 RVA `0x4A0DE4`）。

**该预测被静态证据推翻：**

1. `CompileShaderForReflection` 的调用点只有 **GL**（`gl_emulated.cpp:4239/4376/4377`、
   `gl_shader_funcs.cpp:209`）。Vulkan 捕获自带 SPIR-V，replay 期不做 GLSL→SPIR-V
   编译，故**第 93 / 119 行在 Vulkan 路径不可达**。
2. `spirv_reflect.cpp:2527` 的 `rdcspv::Init()` + `RegisterShutdownFunction`
   位于 **`TEST_CASE("Validate SPIR-V reflection")`** 内，属**测试代码**，非 replay 路径。

~~**结论：glslang 指针缺陷解释 teardown 故障，但不足以解释 integration 的
`0xC0000005`。两者不应被假定同源。**~~

> **本节的 source-separation inference 已撤回（见 §15）。**
> L93 预测的否证**成立**；但由此推出「本缺陷不解释 integration 故障」是**错误的**。
> A1 已证明 integration 故障与历史 teardown 故障落在**同一 RVA、同一指令、同一寄存器
> 状态**，即同一 fault 实例。「否证一个预测」与「两个故障不同源」是两个不同命题，
> 本节把前者当成了后者。§13.3 当时的保留是对的，撤回的是本节的过度推论。

### 14.5 旁证：故障偏移语义得到独立确认

`docs/AUDIT-2026-10-02.md:85` 独立记录「`renderdoc.dll+0x4A0A4E`，`lm` 显示
`(export symbols)` 而非 `(pdb)`」，与 §12.1 判定 `0x4A0A4E` 为 **RVA** 一致。

### 14.6 状态

| 项 | 状态 |
| --- | --- |
| teardown 故障点 | **ESTABLISHED**（`glslang_compile.cpp:57`） |
| 守卫缺陷 | **ESTABLISHED（二进制级）** |
| integration `0xC0000005` | **ESTABLISHED = 与历史 teardown 同一 fault**（§15；本行原写的「已排除由本缺陷解释」已撤回） |
| 两者是否同源 | **SAME FAULT**（同模块、同 RVA `0x4A0A4E`、同指令 `48 8b 18`、同 `RAX=0`） |
| 下一步 | **需分支决策**（见 §14.4：原预测已被自身证据推翻） |

## 15. A1 复现成功：integration failure 与历史 teardown 是同一 fault

### 15.1 实验记录（三次运行，全部保留，不抹除）

| 运行 | 配置 | 结果 | 判定 |
| --- | --- | --- | --- |
| run 1 | 仅设 `RDEBUG_RENDERDOC_PATH` | 63 项全 skip，模块表**无** `renderdoc.pyd`/`.dll`，`g` 停在非异常事件 | **INVALID**——漏设 `RDEBUG_ISOLATION_CAPTURE_DIR`，未加载被观测对象 |
| run 2 | 三项环境变量齐备 | 进程 exit 1，未加载 RenderDoc，63 项失败 | **PERTURBED**——cdb 在首现异常处断下，破坏了运行 |
| run 3 | 同上 + `sxd *; sxe av`（屏蔽首现异常，仅在访问违例断下） | **捕获故障** | **VALID / DECISIVE** |

run 1 与 run 2 **不构成反证**，仅为实验记录；run 3 是唯一有效证据。

### 15.2 捕获结果（cdb 10.0.28000.2114 AMD64）

```
ExceptionAddress : 00007ffed2fb0a4e
module           : pymodules\renderdoc.dll  base 0x7ffed2b10000
RVA              = 0x7ffed2fb0a4e − 0x7ffed2b10000 = 0x4A0A4E
instruction      : 488b18        mov rbx,qword ptr [rax]
ExceptionCode    : c0000005      Parameter[0]=0  Parameter[1]=0
                 → Attempt to read from address 0x0
rax = 0000000000000000        rbx = 00007ffed424dc80（非空）
```

故障前序列与 §13 反汇编逐条一致：

```
d2fb0a20  sub  rsp,28h
d2fb0a30  cmp  byte ptr [...+0x6be8fc],0      ← glslang_inited 守卫
d2fb0a37  je   +0x2a6ff6                       ← 守卫为假即返回
d2fb0a3d  mov  rax,qword ptr [...+0x6b88a0]    ← 载入 allocatedPrograms
d2fb0a4e  mov  rbx,qword ptr [rax]             ← ★ NULL 解引用
```

运行中的模块**就是**故障映像：`0x4A0A3D` 处字节 `48 8b 05 3c 8d 27 01` 与故障 PE
完全吻合。RenderDoc 自报 `v1.46 ... (b7f1554feb0d7d7120f2b9280364b98972ec37d3)`，
与已确立的源码身份一致。

### 15.3 fault identity（同一故障实例）

| 特征 | A1 integration | 历史 teardown | 判定 |
| --- | --- | --- | --- |
| 模块 | `pymodules\renderdoc.dll` | 同 | 相同 |
| RVA | `0x4A0A4E` | `0x4A0A4E` | 相同 |
| 指令 | `48 8b 18` | `48 8b 18` | 相同 |
| 读地址 | `0x0` | `0x0` | 相同 |
| RAX | `0` | `0` | 相同 |
| RBX | 非空 | 非空 | 相同 |
| 上下文 | guard → load → dereference | 同 | 相同 |

> **integration failure == teardown failure**（同一 fault 实例，非「同类」）

### 15.4 触发路径

栈（自底向上）：

```
python → ucrtbase!exit → ExitProcess → RtlExitUserProcess
       → ntdll!LdrShutdownProcess              ← 进程退出 / DLL_PROCESS_DETACH
       → ucrtbase!execute_onexit_table
       → renderdoc 关闭函数分发
       → rdcspv::Shutdown()  @ 0x4A0A4E      ← 崩溃
```

崩溃发生在**进程退出期**，不是测试执行期。这与门禁记录「63 项 OK，但进程未干净
退出」完全一致。

### 15.5 A2 取消

归属**不需要符号**：§12/§13 已由字节匹配 + 反汇编建立代码归属，A1 又独立确认运行时
命中同一 RVA。重链接不会提高证据等级，故 **A2 取消，未执行任何 relink**。

### 15.6 仍开放的唯一问题

> 为什么进程退出时 `allocatedPrograms == NULL`，而 `glslang_inited == true`？

§14.2 给出的候选链条要求 `ShutdownReplay()` 先于 driver 重建发生。**该次序尚未用
证据确立**，须以 harness 与 driver 生命周期的实际调用关系核对，不得以「应该先发生」
补足。若静态代码不足以判定，保持 `UNCLASSIFIED`。

### 15.7 附带发现（独立 issue，不参与本节判定）

未提供 RenderDoc 时，integration 套件为 **60 skipped + 1 failure + 1 error**（exit 1）。
那些用例应当 skip 而非失败。此为 harness 健壮性缺口，**与本 fault identity 无关，
不得用它削弱 A1，也不得用它污染本节结论**。

## 16. 静态核对 shutdown 次序：排除 P-b，候选收敛为 P-a

承接 §15。**纯静态核对**，未运行实验，未改动被观测对象。

### 16.1 `shutdown_replay()` 在本次运行中并未真正执行

`shutdown_replay()` 全仓库**只有一个真实调用点**：`tests/integration/test_ide_ownership.py:144`。
而 5 处测试断言 `initialise_epoch == 1`
（`test_ide_ci_workflow.py:89`、`test_ide_ownership.py:172`、`test_m15_acceptance.py:172,178`、
`test_runtime_isolation.py:149`），且 A1 实测 **63 项全部 OK**。

`core.py:275-292`：

```python
if _REPLAY_LIFECYCLE["initialised"] and _REPLAY_LIFECYCLE["sessions"] == 0:
    _REPLAY_LIFECYCLE["rd"].ShutdownReplay()
    ...
    _REPLAY_LIFECYCLE["initialised"] = False
```

若该调用成功执行，`initialised` 被置 `False`，其后任何 `CaptureSession` 都会再次调用
`InitialiseReplay()`（`core.py:186-190`），`initialise_epoch` 必然变为 2，上述断言必然失败。
**它们没有失败** ⇒ `rd.ShutdownReplay()` 未被执行。

### 16.2 排除 P-b

§14.2 的候选链条要求「`ShutdownReplay()` 运行 → 指针置 NULL → driver 重建（重新注册
`Shutdown`）→ 进程退出时 `~RenderDoc()` 再跑一次 `Shutdown()`」。该链条以
`initialise_epoch >= 2` 为必要条件，与 §16.1 的实测约束**不相容**。

> **P-b（Shutdown → 重建 → 退出再 Shutdown）已排除。**

### 16.3 剩余唯一静态一致的候选：P-a（初始化顺序缺陷）

```cpp
44:   glslang::InitializeProcess();
45:   glslang_inited = true;              ← 守卫变量先置位
47:   allocatedPrograms = new rdcarray<...>;   ← 被守卫资源后分配
48:   allocatedShaders  = new rdcarray<...>;
```

若第 47 / 48 行的 `new` **抛出**，状态恰为观测值：`glslang_inited == true` 而
`allocatedPrograms == NULL`。随后进程退出 → `~RenderDoc()`（core.cpp:765-767）→
`rdcspv::Shutdown()` → 守卫通过 → 第 57 行解引用 NULL → `0x4A0A4E`。

**`new` 是否真的抛出属运行时条件，静态不可判定。** 不以「应该先发生」补足，
故根因仍 `OPEN`，候选状态为：

| 候选 | 状态 |
| --- | --- |
| P-b：Shutdown → driver 重建 → 退出再 Shutdown | **已排除**（`initialise_epoch == 1`） |
| P-a：`Init()` 中 `new` 抛出，留下 `inited=true` / pointers=NULL | **唯一剩余，静态一致，未证实** |

### 16.4 附带发现：harness 自身的第二个缺陷（独立 issue）

`shutdown_replay()` 的 docstring（core.py:276-278）声称「之后不能再开新
`CaptureSession`，因为 RenderDoc 不允许重初始化」，但**代码不强制**该约定：

* `__init__` 只以 `not initialised` 决定是否调用 `InitialiseReplay()`（core.py:186）；
* `shutdown_replay()` 的**成功路径恰好把 `initialised` 置 `False`**（core.py:292），
  即**主动邀请**它自己声明禁止的重初始化；
* 其 `except` 分支还特意**不清** `initialised` 以规避 F-N3-4（core.py:283-291），
  而成功分支清。

该不一致本次**未触发**（因 §16.1），属独立的 harness 缺陷，不参与本 fault 的判定，
亦不得用来削弱 §15 的 fault identity。

### 16.5 证实 P-a 所需的最小实验（尚未执行）

无需修改被观测对象：故障 PE 中 `glslang_inited` 位于 **RVA `0x6BE8FC`**、
`allocatedPrograms` 位于 **RVA `0x6B88A0`**（由 A1 的 cdb 输出解析而得）。可在 cdb 下以
`bu` 对这两处**写入指令**下断点：

* 若命中 `glslang_inited = 1` 而 `allocatedPrograms` **从未被写入** ⇒ **P-a 证实**；
* 若 `allocatedPrograms` 曾被写入 ⇒ **P-a 证伪**，需另寻机制。

此步骤需新的运行时授权（cdb 附加 + 在 RenderDoc 初始化期断下）。