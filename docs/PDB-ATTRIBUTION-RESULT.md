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
