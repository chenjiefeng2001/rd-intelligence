---
document_role: evidence_record
freshness_policy: point_in_time
as_of_commit: 4e3c485
document_point_in_time_note: >-
  本文档记录的是一次已经发生的事实核对，结论绑定其考察时刻。它不会随 HEAD
  变化而变化；若下述记录被更正或推翻，须由新的证据记录取代本文档，而非就地改写。
---

# N3-05A 补丁验证：STOP 已被 run7 取代

## 这份文档为何存在

`rdebug-validation` 中有两份机器可读的补丁验证记录，都写着 STOP。而语料里的
metadata 声明 `patch_recorded: true`。两者不能同时为当前事实。

核对结果是：**STOP 是被取代的中间结论，`patch_recorded: true` 属实。** 但那份取代
关系只写在 markdown 里，任何机器消费者读到的仍是 STOP。本文档把更正放进可版本化、
可审计的位置。

## 三份记录

| 记录 | 时间 | 内容 | 状态 |
| --- | --- | --- | --- |
| `n3-corpus/build/build_manifest.json` | 2026-08-28 22:24（`recorded_at` 2026-08-28T07:24） | `renderdoc.patch_verified_in_binary: false` + STOP 注记 | **已失效** |
| `n3-corpus/build/patch_verification.json` | 2026-08-28 22:14 | `verdict: STOP`，P1/P3 `pass: false` | **已失效** |
| `n3-corpus/build/N3-05A-patch-verification-result.md` | 2026-08-29 12:26 | run7，`PASS=4 FAIL=0` | **权威** |

## run7 的结果

run7 时间 2026-08-28 21:0x（PDT），入口
`tools/n3_capture_deelev.bat → n3_deelev_bat.py --medium → n3_capture_unelevated.bat`。

| 探针 | 类型 | 期望 | 实测 | 通过 |
| --- | --- | --- | --- | --- |
| P0 | 负对照（不触发） | 无 .rdc | 无 .rdc | ✅ |
| P1 | 正例（`RDOC_TRIGGER_FRAMES=120`，130 帧） | frame 120 出 .rdc | `P1.rdc` 34,111,522 B，`1.46 b7f155` | ✅ |
| P2 | 下边界（触发 120，帧数 120） | 无 .rdc | 无 .rdc | ✅ |
| P3 | 精确边界（触发 120，帧数 121） | frame 120 出 .rdc | `P3.rdc` 34,111,636 B，`1.46 b7f155` | ✅ |

先前的根因是**提权**：loader 需要管理员权限，未能加载时已安装的未打补丁
RenderDoc v1.44 图层接管了 Vulkan 采集路径。run7 用**降权子进程**
（loader Normal + HKCU 图层扫描）绕开了这一点。该文档的判据是明确的：
**行为验证，而非时间戳或 build freshness**，才是判断补丁在被执行二进制中是否生效的
权威依据。

## 交叉核对：capture 字节数

run7 记录的采集产物与语料目录中的文件逐一相符：

| 文件 | run7 记录 | 磁盘实测 | 相符 |
| --- | ---: | ---: | --- |
| `captures/N3-05A1.rdc` | 34,111,570 B | 34,111,570 B | ✅ |
| `captures/N3-05A2.rdc` | 1,335,110 B | 1,335,110 B | ✅ |

两者均记为 `1.46 b7f155`，由 `renderdoc.dll` sha256 `3c282d83…9828` 写出。
`b7f1554feb0d7d7120f2b9280364b98972ec37d3` 正是本仓库 `fork-exception.json` 为
capture-trigger 例外钉定的基线。

## 结论与其边界

- `N3-05A1.json` / `N3-05A2.json` 中的 `patch_recorded: true` **属实**，有行为验证
  与 capture 字节数两项独立佐证。
- 因此 `capture_mechanism.patch` 与 `capture_mechanism.patch_recorded` **不应被产出**
  来满足 F3：它们并不存在，也不需要存在。`fork-exception.json` 已据此移除了对这两个
  文件的命名，保留全部可验证的 provenance（元数据 glob、机制名、`patch_recorded`、
  制品摘要、基线钉定）。
- **本文档不修改 `rdebug-validation`。** 那是外部、非版本化目录，其中的
  `patch_verified_in_binary: false` 与 `verdict: STOP` 仍然存在。任何直接读取该目录
  而未读到本文档的消费者，仍会得到 STOP —— 这是已知的、未根治的缺口。

## 未根治的部分

取代关系只有散文记录，没有机器可读形式。根治需要将该目录纳入版本控制并在其中
标注取代关系；那是一次治理接管，不在本文档的范围内，也未被授权。