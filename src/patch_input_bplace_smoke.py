#!/usr/bin/env python3
"""Smoke-test: show real B_Place UI instead of FUN_001fb438 candidate grid.

On NameInput_OnCellTap → candidate enter (BL @ 0x001FB150), close is NOT done;
we open Lyt_Prf_Win_B_Place on a high UI slot (0x1E) via FUN_005c52d8 so ML
stays alive underneath.

Expected: birthplace list chrome appears (still prefecture strings until we
rewire fill). If Azahar unmapped-faults, Profile.arc failed to mount — note PC.

Rollback: restore exefs/code.bin.bak_pre_bplace_smoke
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

# NameInput_OnCellTap: mov r0,r4; str page; bl FUN_001fb438
BL_SITE = 0x001FB150
ADDR_FILL = 0x001FB438

ADDR_CAVE = 0x006E6000  # after mllist cave @ 0x6E5488 (0xAD8)
CAVE_MAX = 0x100

# UI manager pointer (same DAT as FUN_00255f38 / FUN_0034d08c)
DAT_UI_MGR = 0x007BFA40  # file; VA 0x008BFA40
ADDR_SHOW = 0x005C52D8
ADDR_BP_GET = 0x0023D790  # returns descriptor @ 0x89D584

SLOT = 0x1E  # high slot; avoid profile's slot 1 / name-input slots 2–6


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def mov_imm(rd: int, imm: int) -> bytes:
    return u32(0xE3A00000 | (rd << 12) | (imm & 0xFF))


def mov_reg(rd: int, rm: int) -> bytes:
    return u32(0xE1A00000 | (rd << 12) | rm)


def ldr_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE5900000 | (rn << 16) | (rd << 12) | imm)


def strb_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE5C00000 | (rn << 16) | (rd << 12) | imm)


def push(mask: int) -> bytes:
    return u32(0xE92D0000 | mask)


def pop(mask: int) -> bytes:
    return u32(0xE8BD0000 | mask)


def bl(here: int, target: int) -> bytes:
    return u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def ldr_pc_lit(rd: int, lit_off_from_insn: int) -> bytes:
    """ldr rd, [pc, #imm] with imm = lit_off_from_insn - 8 (PC+8)."""
    imm = lit_off_from_insn - 8
    assert imm >= 0 and imm < 0x1000 and (imm & 3) == 0
    return u32(0xE59F0000 | (rd << 12) | imm)


def build_cave() -> bytes:
    """r0 = name-input obj on entry (OnCellTap convention)."""
    # Layout:
    # 00: push {r4-r7,lr}
    # 04: mov r4, r0          ; name-input
    # 08: ldr r0, [pc, #ui] ; &DAT
    # 0c: ldr r0, [r0]        ; ui mgr*
    # 10: mov r1, #0          ; bank
    # 14: mov r2, #SLOT
    # 18: bl BP_GET           ; r0 = desc
    # 1c: mov r3, r0
    # 20: ldr r0, [pc, #ui]
    # 24: ldr r0, [r0]
    # 28: mov r1, #0
    # 2c: mov r2, #SLOT
    # 30: mov r7, #0
    # 34: push {r7}           ; 5th arg
    # 38: bl SHOW
    # 3c: add sp, #4
    # 40: mov r0, #1
    # 44: strb r0, [r4, #0x44]
    # 48: mov r0, #0
    # 4c: str r0, [r4, #0x38]
    # 50: pop {r4-r7,pc}
    # 54: lit ui mgr DAT VA
    code = bytearray()
    lit_pos = 0x54

    def here() -> int:
        return ADDR_CAVE + len(code)

    code += push(0x40F0)  # r4-r7, lr
    code += mov_reg(4, 0)
    # ldr r0, [pc, #lit]; lit at +0x54, insn at +0x08 → imm = 0x54-0x08-8 = 0x44
    code += ldr_pc_lit(0, lit_pos - len(code))
    code += ldr_imm(0, 0, 0)
    code += mov_imm(1, 0)
    code += mov_imm(2, SLOT)
    code += bl(here(), ADDR_BP_GET)
    code += mov_reg(3, 0)
    code += ldr_pc_lit(0, lit_pos - len(code))
    code += ldr_imm(0, 0, 0)
    code += mov_imm(1, 0)
    code += mov_imm(2, SLOT)
    code += mov_imm(7, 0)
    code += u32(0xE52D7004)  # str r7, [sp, #-4]!
    code += bl(here(), ADDR_SHOW)
    code += u32(0xE28DD004)  # add sp, #4
    code += mov_imm(0, 1)
    code += strb_imm(0, 4, 0x44)
    code += mov_imm(0, 0)
    code += u32(0xE5840038)  # str r0, [r4, #0x38]
    code += pop(0x80F0)  # r4-r7, pc
    while len(code) < lit_pos:
        code += b"\x00"
    code += u32(DAT_UI_MGR + 0x100000)  # VA of DAT
    assert len(code) <= CAVE_MAX
    return bytes(code)


def apply_patch(data: bytearray, vanilla: bytes) -> None:
    # restore fill BL site first
    data[BL_SITE : BL_SITE + 4] = vanilla[BL_SITE : BL_SITE + 4]
    blob = build_cave()
    data[ADDR_CAVE : ADDR_CAVE + CAVE_MAX] = b"\x00" * CAVE_MAX
    data[ADDR_CAVE : ADDR_CAVE + len(blob)] = blob
    data[BL_SITE : BL_SITE + 4] = bl(BL_SITE, ADDR_CAVE)
    print(f"[bplace-smoke] BL {BL_SITE:#x} -> cave {ADDR_CAVE:#x} ({len(blob)} B) slot={SLOT:#x}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    blob = build_cave()
    print(f"cave {len(blob)} hex {blob.hex()}")
    if args.dry_run:
        return 0
    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")
    dest = Path.home() / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")
    bak = dest.with_name(dest.name + ".bak_pre_bplace_smoke")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)
    van = (
        Path(__file__).resolve().parents[2]
        / "New Love Plus Plus/extracted/exefs/code.bin"
    ).read_bytes()
    data = bytearray(dest.read_bytes())
    apply_patch(data, van)
    dest.write_bytes(data)
    shutil.copy2(dest, dest.parent.parent / "code.bin")
    print("Fully quit Azahar. Expect B_Place window on kana tap (birthplace data).")
    print("Rollback: copy exefs/code.bin.bak_pre_bplace_smoke → code.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
