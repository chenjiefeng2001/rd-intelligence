# OBSERVABILITY-CAPABILITY-MATRIX

> **本文件是从事故附录升级而成的正式能力矩阵。**
> 它记录的是**本项目在特定工具条件下已被实证的能力与边界**，每一条都有具体证据出处。
> 它的价值不在于「做了多少逆向」，而在于**下一次能预先知道哪条路可行、哪条会浪费**。

`as_of`: `b89797d` ｜ 环境：Windows x64 ｜ MSVC `14.44.35207` / `cl 19.44.35228.0` ｜ MSBuild 17.14.40 ｜ LLVM 19.1.5 ｜ CDB 10.0.28000.2114

---

## 1. 二进制取证能力

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| PE 头解析：sections / ImageBase / TimeDateStamp / machine | **PROVEN** | 反复使用 |
| PE CodeView (RSDS) 解析：GUID / age / PDB 路径 | **PROVEN** | 用于证明事故 PE 无 RSDS |
| MSF/PDB 二进制解析（Big/Small MSF、stream directory、DBI header） | **PROVEN** | 手工解析成功（ARM64 版 llvm-pdbutil 不可用时） |
| PDB `Signature` / `Age` / `GUID` 读取 | **PROVEN** | `llvm-pdbutil dump -summary` |
| PE ↔ PDB 配对：RSDS GUID+age | **PROVEN（标准方法）** | — |
| **PE timestamp ↔ PDB signature 差值作为配对判据** | **PROVEN INVALID** | 另一构建自身 PE `0x6A91903B` ↔ PDB `0x6A91903F` 差 **4 秒**仍为健康配对 |
| 已知 RVA → 指令（反汇编） | **PROVEN** | `llvm-objdump` / cdb `ub` |
| 已知 RVA → 源码行（无 PDB，经字节等价中转） | **PROVEN** | 48 字节唯一匹配 → 行表 → 反汇编，见 `TEARDOWN-EVIDENCE-CASE.md` F2 |
| 全局变量虚拟地址（由 RIP 相对反推） | **PROVEN** | `@rip + 0x217E52` 等，并经 `.data` 段范围独立校验 |
| 全部函数 / public 符号枚举 | **PROVEN** | 166,981 行 `dump -publics` |

## 2. 故障捕获与判别能力

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| cdb 下捕获首次/二次访问违例，含 ExceptionAddress / 寄存器 / 栈 | **PROVEN** | `a1_crash3.log` |
| cdb 屏蔽首现异常、仅在 AV 断下（`sxd *; sxe av`） | **PROVEN** | 使 263 秒套件不被调试器扰动 |
| cdb 区分「到达顶层的异常」与「被捕获的异常」 | **PROVEN（重要区分）** | `sxd *` 下被捕获异常不进入顶层计数 |
| 从**实际运行状态**判别竞争假说 | **PROVEN** | `initialise_epoch == 2` + `shutdown_error` 缺失 → P-b′ 成立 |
| 纯源码检查排除竞争假说 | **PROVEN** | P-d：`catch` 命中数 0 |
| 屏幕/转储采集（minidump） | **NOT USED** | 本案不需要 |
| 注入式验证（fault injection） | **NOT ESTABLISHED** | 见 §5 |

## 3. 无符号函数定位 —— **不可靠，已实证**

| 方法 | 失败次数 | 具体失效 |
| --- | --- | --- |
| target 名猜测 | 1 | `pymodules` 是 `OutDir`，`MSB4057` 拒绝全部 29 个项目 |
| 结构指纹（收尾序列） | 2 | 误命中「4 字符字符串比较后置位」；误命中 glslang 池 `operator new` |
| 结构指纹（完整判据：guard + 两次同目标 call + 收尾） | 1 | 判据 5 `movb $1 → add rsp,28h → ret` 全 .text 仅 2 处，均为池分配器 |
| EH / `.pdata` unwind 元数据 | 1 | 390 个 EH 候选，多个不可消歧；handler 提取出无效值 |
| `int3` 填充划分函数边界 | — | 158,644 个边界，远超函数数，不可作为判据 |

> **结论：在无 PDB 的产物上，用结构或元数据反推特定函数不可靠（5 次实证失败）。**
> X2 产物**无 PDB**（Release 未启用 `/DEBUG`），故其函数定位**当前不可完成**。

## 4. 内存寻址能力 —— **DLL 限定读取被阻断**

| 寻址形式 | 结果 | 证据 |
| --- | --- | --- |
| `renderdoc + RVA`（短名） | **UNSAFE — 静默解析到 `.pyd`** | `bl` 阳性对照：落点 = pyd 基址 + offset |
| `<完整路径>+RVA`（`db`） | **UNSUPPORTED BY CURRENT CDB** | `Syntax error at '\...\renderdoc.dll+0x1000 '`（首个反斜杠即停止解析） |
| `<完整路径>+RVA`（`ba`） | **UNSUPPORTED** | `Syntax error` |
| `lm m <模块>` | **无输出** | U2 尝试 |
| `renderdoc_<base>+RVA`（唯一化名） | 推测可用，**事前不可知**（含 ASLR 基址） | — |
| `@rip + delta`（相对表达式） | **PROVEN** | 用于故障构建；受限于目标二进制已知 RVA |
| `~<模块索引>+RVA` | **UNAVAILABLE** | cdb `lm t` 输出不含索引列 |

### 根本障碍

> **同名 basename 模块消歧**：进程内同时加载 `renderdoc.dll` 与 `renderdoc.pyd`，
> 两者 basename 同为 `renderdoc`。cdb 短名解析取先加载的 `.pyd`，
> 且**静默**——不报错，只是读错模块。

## 5. 注入式验证能力

| 能力 | 状态 | 理由 |
| --- | --- | --- |
| Application Verifier 分配失败注入 | **NOT SUITABLE** | 对堆破坏/溢出中止，**不注入分配失败** |
| 调试 CRT `_CrtSetBreakAlloc` | **NOT SUITABLE** | 需重建（破坏产物哈希）；且触发**断点**而非可捕获 `bad_alloc` ⇒ 测不到回滚分支 |
| Job Object 内存上限 | **NOT ATTEMPTED** | 无法指定失败落在哪一次分配；无法排除「失败发生在别处」 |
| 硬件监视点 + 调用点返回地址判据 | **NOT ATTEMPTED（定位前提未建立）** | 依赖 §3 的函数定位，当前不可靠 |
| `.foreach` 捕获唯一化模块名 | **DEFERRED — 见 §6** | 理论可用，本轮不授权 |

## 6. 降级项：`.foreach` 模块别名捕获

> **`.foreach`-based module alias capture remains theoretically available, but is
> outside the frozen verification scope and is not required to sustain any established
> conclusion.**

它**未被证伪**，仅为以下理由而不执行：

1. 继续该方向会把「验证既有修复」变成「开发新的 CDB 寻址技术」——**收益不匹配**；
2. 任何由此产生的读数都属于**新建立的取证环境**，不能自动当作原事故环境的直接事实；
3. 已确立的结论（fault identity、故障点、根因、行为级验收）**均不依赖**它。

**未来仅在以下条件之一满足时重新考虑**（能力变化，而非「还没拿到 PASS」）：

- 获得与事故 DLL 匹配的 PDB
- 获得可明确指定 DLL module object 的调试环境
- 获得经治理批准的新取证工具链

## 7. 治理与记账能力（本项目自有，已固化）

| 能力 | 状态 |
| --- | --- |
| 四态门禁归约（PASS / FAIL / BLOCKED_INFRA / NEEDS_REVIEW） | **PROVEN** |
| `accounting_consistent` 记账一致性校验 | **PROVEN** |
| baseline / drift 强制（含**禁止过度声称新鲜度**） | **PROVEN** |
| `U+FFFD` / `NUL` 字节完整性检查 | **PROVEN**（抓到了本项目自身的文档错误） |
| point-in-time 快照保护（能力矩阵不回写） | **PROVEN** |
| 工件 manifest + 重推导控制 | **PROVEN** |
| 已推翻结论的显式保留（SUPERSEDED / DISPROVEN / REFUTED / EXCLUDED） | **PROVEN** |

## 8. 明确的不可达

| 项 | 状态 |
| --- | --- |
| 门禁 `PASS` | **当前 G4 语义下不可达**，上限 `NEEDS_REVIEW / exit 4` |
| 干净 clone 复现 integration | **不可达**：14 个 fixture 位于 `tests/workload/corpus/`（`.gitignore` 排除） |
| 多机 / hosted 证据 | **不可达**：无 git remote |

---

冻结点：`b89797d`。
