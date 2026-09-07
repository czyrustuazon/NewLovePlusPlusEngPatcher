#!/usr/bin/env python3
"""On NameInput_RedrawKeyboard: force nameInputObj+0x44=0 and clamp +0x30 to 0..5.

+0x44 is the "candidates currently showing" flag. Stale 1 makes OnCellTap take
the SELECT path with uninitialized per-slot buffers. Legitimate vanilla paths
already clear it before RedrawKeyboard; forcing 0 here is safe.

+0x30 is the keyboard charset jump index. RedrawKeyboard only dispatches
FillKeyboard_* when mode<6; heap garbage >=6 skips every filler and leaves an
empty gojuon checkerboard (pager 1/1).

Does NOT touch +0x24. Forcing +0x24=0 (removed candmode_reset) kills taps —
see technical.md §17.2.

Call site: file 0x1fa828 (mov r5,#0), resume 0x1fa82c. Cave @0x6E6A38+0xC0.
Works on vanilla RedrawKeyboard without candmode_reset.

Rollback: exefs/code.bin.bak_pre_candmode_fillflag_reset.
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

SITE = 0x001FA828
RESUME = 0x001FA82C
EXPECT_SITE = bytes.fromhex("0050a0e3")  # mov r5,#0x0

ADDR_CAVE = 0x006E6A38
CAVE = ADDR_CAVE + 0xC0
CAVE_LEN = 0x20


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def b_ins(here: int, target: int) -> bytes:
    return u32(0xEA000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def mov_imm0(rd: int) -> bytes:
    return u32(0xE3A00000 | (rd << 12))


def strb_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE5C00000 | (rn << 16) | (rd << 12) | (imm & 0xFFF))


def ldr_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE5900000 | (rn << 16) | (rd << 12) | (imm & 0xFFF))


def cmp_imm(rn: int, imm: int) -> bytes:
    return u32(0xE3500000 | (rn << 16) | (imm & 0xFF))


def build_cave() -> bytes:
    """mov r5,#0; +0x44=0; if +0x30>=6 then +0x30=0; b resume."""
    code = bytearray()
    code += mov_imm0(5)
    code += mov_imm0(1)
    code += strb_imm(1, 4, 0x44)
    code += ldr_imm(1, 4, 0x30)
    code += cmp_imm(1, 6)
    code += u32(0x23A01000)  # movhs r1, #0
    code += u32(0x25841030)  # strhs r1, [r4, #0x30]
    code += b_ins(CAVE + len(code), RESUME)
    if len(code) > CAVE_LEN:
        raise SystemExit(f"fillflag cave {len(code):#x} > {CAVE_LEN:#x}")
    return bytes(code) + b"\x00" * (CAVE_LEN - len(code))


def apply_patch(data: bytearray) -> None:
    site = bytes(data[SITE : SITE + 4])
    already = site == b_ins(SITE, CAVE)
    if site != EXPECT_SITE and not already:
        raise ValueError(
            f"unexpected bytes at site {SITE:#x}: {site.hex()} "
            f"(expected {EXPECT_SITE.hex()} or branch to cave)"
        )
    if not already:
        region = bytes(data[CAVE : CAVE + CAVE_LEN])
        if region != b"\x00" * CAVE_LEN:
            raise ValueError(f"cave @{CAVE:#x} not empty: {region.hex()}")
    cave = build_cave()
    data[CAVE : CAVE + CAVE_LEN] = cave
    data[SITE : SITE + 4] = b_ins(SITE, CAVE)
    print(f"[candmode-fillflag-reset] site @{SITE:#x} -> cave @{CAVE:#x} (clamp +0x30)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        build_cave()
        print("dry-run OK")
        return 0
    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")

    dest = Path.home() / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")
    bak = dest.with_name(dest.name + ".bak_pre_candmode_fillflag_reset")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    apply_patch(data)
    dest.write_bytes(data)
    shutil.copy2(dest, dest.parent.parent / "code.bin")
    print("Fully quit Azahar to reload exefs/code.bin.")
    print("Rollback: copy bak_pre_candmode_fillflag_reset -> code.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
