"""E2: extract real binary, CodeView PDB identity and PDB stream identity.

No identity is inferred from a file name. The EXE's RSDS record is compared
with the PDB info stream's own GUID/Age; a mismatch blocks an S3/S4 claim.
"""

import argparse
import hashlib
import json
import struct
import uuid


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def pe_codeview(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] != b"MZ":
        raise ValueError("not a PE file")
    pe = _u32(data, 0x3C)
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("bad PE signature")
    coff = pe + 4
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic != 0x20B:
        raise ValueError("expected PE32+")
    dd = opt + 112
    debug_rva, debug_size = struct.unpack_from("<II", data, dd + 6 * 8)
    sections = []
    sec = opt + opt_size
    for i in range(num_sections):
        base = sec + 40 * i
        virtual_size = _u32(data, base + 8)
        virtual_addr = _u32(data, base + 12)
        raw_size = _u32(data, base + 16)
        raw_ptr = _u32(data, base + 20)
        sections.append((virtual_addr, virtual_size, raw_ptr, raw_size))

    def rva_to_offset(rva):
        for va, vsize, ptr, size in sections:
            if va <= rva < va + max(vsize, size):
                return ptr + (rva - va)
        raise ValueError("unmapped RVA")

    offset = rva_to_offset(debug_rva)
    for i in range(debug_size // 28):
        base = offset + 28 * i
        if _u32(data, base + 12) != 2:  # IMAGE_DEBUG_TYPE_CODEVIEW
            continue
        cv_offset = rva_to_offset(_u32(data, base + 20))
        if data[cv_offset:cv_offset + 4] != b"RSDS":
            raise ValueError("unexpected CodeView signature")
        guid = uuid.UUID(bytes_le=data[cv_offset + 4:cv_offset + 20])
        age = _u32(data, cv_offset + 20)
        path_end = data.find(b"\0", cv_offset + 24)
        pdb_path = data[cv_offset + 24:path_end].decode("utf-8", "replace")
        return {"guid": str(guid).upper(), "age": age, "pdbPath": pdb_path}
    raise ValueError("no CodeView record")


def pdb_identity(path):
    with open(path, "rb") as fh:
        data = fh.read()
    magic = b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0"
    if not data.startswith(magic):
        raise ValueError("unsupported PDB format")
    block_size = _u32(data, 32)
    num_dir_bytes = _u32(data, 44)
    block_map = _u32(data, 52)
    block_map_offset = block_map * block_size
    count = (num_dir_bytes + block_size - 1) // block_size
    dir_blocks = [_u32(data, block_map_offset + 4 * i) for i in range(count)]
    directory = b"".join(
        data[b * block_size:b * block_size + block_size] for b in dir_blocks)
    num_streams = _u32(directory, 0)
    sizes = [_u32(directory, 4 + 4 * i) for i in range(num_streams)]
    cursor = 4 + 4 * num_streams
    stream_blocks = []
    for size in sizes:
        n = (size + block_size - 1) // block_size
        stream_blocks.append([_u32(directory, cursor + 4 * i) for i in range(n)])
        cursor += 4 * n
    info_blocks = stream_blocks[1]
    info = b"".join(
        data[b * block_size:b * block_size + block_size] for b in info_blocks)
    age = _u32(info, 8)
    guid = uuid.UUID(bytes_le=info[12:28])
    return {"guid": str(guid).upper(), "age": age}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="e-case-identity")
    ap.add_argument("exe")
    ap.add_argument("pdb")
    ap.add_argument("source")
    ap.add_argument("capture")
    ap.add_argument("--json", dest="json_path")
    args = ap.parse_args(argv)
    codeview = pe_codeview(args.exe)
    pdb = pdb_identity(args.pdb)
    matched = codeview["guid"] == pdb["guid"] and codeview["age"] == pdb["age"]
    result = {
        "kind": "e-case-binary-identity",
        "executable": {"path": args.exe, "sha256": sha256(args.exe)},
        "pdb": {"path": args.pdb, "sha256": sha256(args.pdb),
                "guid": pdb["guid"], "age": pdb["age"]},
        "codeview": codeview,
        "pdbMatchesExecutable": matched,
        "source": {"path": args.source, "sha256": sha256(args.source)},
        "capture": {"path": args.capture, "sha256": sha256(args.capture)},
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0 if matched else 2


if __name__ == "__main__":
    raise SystemExit(main())
