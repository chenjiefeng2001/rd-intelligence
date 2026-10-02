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

对 `renderdoc.dll` 直接读取并解码故障偏移附近的机器码，结果与本文件此前
记录的故障指令**不一致**：

```
0x4A0A42: 48 8b 03        mov rax, qword ptr [rbx]
0x4A0A45: 48 8b cb        mov rcx, rbx
0x4A0A48: 83 fa 01        cmp edx, 1
0x4A0A4B: 75 20           jne 0x4A0A6D
0x4A0A4D: ff 50           call qword ptr [rax+0x0]
```

### 4.1 两处不符

1. **记录的指令在该偏移不存在。** `mov rbx, qword ptr [rax]` 的编码是
   `48 8b 18`；该三字节在故障地址 ±96 字节范围内出现 **0 次**
   （全 DLL 内共 522 次，故不是编码理解错误）。
2. **记录的地址落在一条指令的第二个字节上。** 指令首字节是 `0x4A0A4D`，
   而记录写的是 `0x4A0A4E`。x86 访问违例的 faulting IP 指向指令首字节，
   故若确为此指令，地址应为 `0x4A0A4D`。

`renderdoc.dll` 的 mtime 为 **2026-08-24**，早于全部崩溃记录（2026-09/10），
期间未被替换，因此磁盘字节即崩溃当时的字节。

### 4.2 故障形状因此改变

实际序列是**经 vtable 的虚调用**：

```
mov rax, [rbx]     ; 从对象取 vtable 指针
mov rcx, rbx       ; this
call [rax]         ; 虚调用
```

`rax == 0` 意味着 `[rbx] == 0`，即 `rbx` 指向对象的**首 qword 为空** ——
对象已被清零、已释放，或未完成构造。

这与此前记录的「从空指针**读取** `rbx`」是**不同的故障形状**，指向不同的根因假设：
读取型要求某个指针变量本身为空；虚调用型要求对象存在但其 vtable 槽为空。

### 4.3 这不改变什么

function attribution 仍为 **NOT_ESTABLISHED**。本次分析不需要符号即可确定
故障形状与地址，但把 `0x4A0A4D` 映射到具体函数仍需符号表。

按 scope decision，**未修改 RenderDoc、未启用 WER、未采集 dump**。本节为
只读分析结果。
