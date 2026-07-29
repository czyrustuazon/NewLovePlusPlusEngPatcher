#!/usr/bin/env python3
"""Extract Nintendo 3DS RomFS from an IVFC-wrapped romfs.bin dump."""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def read_u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def read_u64(data: bytes, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


def find_fs_base(data: bytes) -> int:
    if data[:4] == b"IVFC":
        # Level-2 logical data starts at 0x1000 in ctrtool --romfs dumps
        if read_u32(data, 0x1000) == 0x28:
            return 0x1000
        raise SystemExit("IVFC present but RomFS header not found at 0x1000")
    if read_u32(data, 0) == 0x28:
        return 0
    raise SystemExit("Unrecognized RomFS format")


def parse_name(data: bytes, off: int, name_len: int) -> tuple[str, int]:
    raw = data[off : off + name_len]
    name = raw.decode("utf-16-le", errors="replace")
    pad = (4 - (name_len % 4)) % 4
    return name, off + name_len + pad


def walk_dirs(
    data: bytes,
    base: int,
    dir_tab: int,
    offset: int,
    path: Path,
    out_root: Path,
    dirs: dict[int, str],
) -> None:
    while offset != 0xFFFFFFFF:
        entry = base + dir_tab + offset
        parent = read_u32(data, entry)
        sibling = read_u32(data, entry + 4)
        child_dir = read_u32(data, entry + 8)
        child_file = read_u32(data, entry + 12)
        name_len = read_u32(data, entry + 20)
        name, _ = parse_name(data, entry + 24, name_len) if name_len else ("", entry + 24)

        rel = path / name if name else path
        abs_path = out_root / rel
        abs_path.mkdir(parents=True, exist_ok=True)
        dirs[offset] = str(rel)

        if child_dir != 0xFFFFFFFF:
            walk_dirs(data, base, dir_tab, child_dir, rel, out_root, dirs)
        if sibling != 0xFFFFFFFF:
            # continue via loop
            offset = sibling
            continue
        break


def extract_files(
    data: bytes,
    base: int,
    file_tab: int,
    file_tab_size: int,
    data_off: int,
    out_root: Path,
    dirs: dict[int, tuple[int, Path]],
) -> int:
    # Rebuild parent dir offset -> Path from directory table walk result stored differently
    # dirs maps dir_offset -> relative Path
    count = 0
    offset = 0
    end = file_tab_size
    while offset < end:
        entry = base + file_tab + offset
        parent = read_u32(data, entry)
        sibling = read_u32(data, entry + 4)
        file_offset = read_u64(data, entry + 8)
        size = read_u64(data, entry + 16)
        name_len = read_u32(data, entry + 28)
        name, next_off = parse_name(data, entry + 32, name_len)
        # entry size from start
        entry_size = next_off - entry

        parent_path = dirs.get(parent, Path("."))
        dest = out_root / parent_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)

        src = base + data_off + file_offset
        if size == 0:
            dest.write_bytes(b"")
        else:
            dest.write_bytes(data[src : src + size])
        count += 1

        # Advance by scanning: next entry starts after this one.
        # Sibling chain is within same directory; table is not strictly sequential by sibling.
        # Walk table linearly by entry sizes.
        offset += entry_size
        # Align: entry_size already includes padding via parse_name
        if offset % 4:
            offset += 4 - (offset % 4)
    return count


def build_dir_map(data: bytes, base: int, dir_tab: int, dir_tab_size: int) -> dict[int, Path]:
    dirs: dict[int, Path] = {0: Path(".")}

    def recurse(offset: int, path: Path) -> None:
        while offset != 0xFFFFFFFF:
            entry = base + dir_tab + offset
            sibling = read_u32(data, entry + 4)
            child_dir = read_u32(data, entry + 8)
            name_len = read_u32(data, entry + 20)
            name, _ = parse_name(data, entry + 24, name_len) if name_len else ("", entry + 24)
            rel = path / name if name else path
            if name:
                dirs[offset] = rel
            if child_dir != 0xFFFFFFFF:
                recurse(child_dir, rel)
            offset = sibling

    # Root at offset 0
    root_child = read_u32(data, base + dir_tab + 8)
    if root_child != 0xFFFFFFFF:
        recurse(root_child, Path("."))
    return dirs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("romfs_bin")
    ap.add_argument("out_dir")
    args = ap.parse_args()

    path = Path(args.romfs_bin)
    out = Path(args.out_dir)
    print(f"Reading {path} ({path.stat().st_size} bytes)...")
    data = path.read_bytes()
    base = find_fs_base(data)
    print(f"RomFS base: 0x{base:X}")

    hdr = base
    dir_tab = read_u32(data, hdr + 0x0C)
    dir_tab_size = read_u32(data, hdr + 0x10)
    file_tab = read_u32(data, hdr + 0x1C)
    file_tab_size = read_u32(data, hdr + 0x20)
    data_off = read_u32(data, hdr + 0x24)
    print(
        f"dir_tab=0x{dir_tab:X}/{dir_tab_size:X} "
        f"file_tab=0x{file_tab:X}/{file_tab_size:X} data=0x{data_off:X}"
    )

    out.mkdir(parents=True, exist_ok=True)
    dirs = build_dir_map(data, base, dir_tab, dir_tab_size)
    for p in sorted({d for d in dirs.values()}):
        (out / p).mkdir(parents=True, exist_ok=True)

    count = 0
    offset = 0
    while offset < file_tab_size:
        entry = base + file_tab + offset
        parent = read_u32(data, entry)
        file_offset = read_u64(data, entry + 8)
        size = read_u64(data, entry + 16)
        name_len = read_u32(data, entry + 28)
        name, next_off = parse_name(data, entry + 32, name_len)
        entry_size = next_off - entry

        parent_path = dirs.get(parent, Path("."))
        dest = out / parent_path / (name if name else f"unnamed_{offset:X}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = base + data_off + file_offset
        if size == 0:
            dest.write_bytes(b"")
        else:
            if src + size > len(data):
                print(f"WARN: truncated {dest} need {size} at {src}", file=sys.stderr)
                dest.write_bytes(data[src:])
            else:
                dest.write_bytes(data[src : src + size])
        count += 1
        if count % 500 == 0:
            print(f"  extracted {count} files...")
        offset += entry_size

    print(f"Done. Extracted {count} files to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
