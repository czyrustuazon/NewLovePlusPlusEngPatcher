#!/usr/bin/env python3
"""Guard nw::lyt pane attach + FindPaneByName against a null child.

Azahar crash (title hub, looping back to the layout):

  prefetch abort / NoExecuteFault  PC=0  LR=0x00645A2C
  r3=0  r4=4  r12='Pos_'

LR is the instruction after ``BLX r3`` in Pane_FindPaneByName (file
``0x00545A28``, VA +0x100000). The walk does:

  r1 = *(r4 - 4)        ; vtable
  r3 = *(r1 + 0x2c)     ; virtual Compare/Find
  BLX r3

``r4 == 4`` is a null pane object's intrusive list node (object+4). That
happens when ``Pane_AttachToParent`` (file ``0x00545550``) is called with
child=0: InsertFront uses node ``child+4 == 4``, then FindPaneByName later
``BLX``s through page 0. New Azahar raises NX here; older builds ran the
bytes at address 0.

Two last-.text caves (shared pad, hardware-RX):

  +0x28  Pane_AttachToParent: skip if child (r1) or parent (r0) is 0
  +0xA0  FindPaneByName: skip BLX if node is 0/4 or vtable slot is 0
         (was candmode_reset — banned; this slot is free)

Does not replace the name-input call-site parent guard at ``0x1FA790``.
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

from patch_input_cave_map import ADDR_SHARED_PAD as ADDR_CAVE

# Pane_AttachToParent — PUSH {r4-r6,lr}
ATTACH_SITE = 0x00545550
ATTACH_RESUME = 0x00545554
ATTACH_EXPECT = bytes.fromhex("70402de9")  # e92d4070

# FindPaneByName loop: BLX r3 after LDR r3, [vtable+0x2c]
FIND_SITE = 0x00545A28
FIND_RESUME = 0x00545A2C  # cmp r0, #0
FIND_CONTINUE = 0x00545A34  # next sibling
FIND_NOT_FOUND = 0x00545A44  # mov r0, #0
FIND_EXPECT = bytes.fromhex("33ff2fe1")  # e12fff33 BLX r3

ATTACH_CAVE = ADDR_CAVE + 0x28
ATTACH_CAVE_LEN = 0x18
FIND_CAVE = ADDR_CAVE + 0xA0
FIND_CAVE_LEN = 0x20


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def b_ins(here: int, target: int) -> bytes:
    return u32(0xEA000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def beq(here: int, target: int) -> bytes:
    return u32(0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def cmp_imm(rn: int, imm: int) -> bytes:
    return u32(0xE3500000 | (rn << 16) | (imm & 0xFF))


def bxeq_lr() -> bytes:
    return u32(0x012FFF1E)


def blx_r3() -> bytes:
    return u32(0xE12FFF33)


def build_attach_cave() -> bytes:
    code = bytearray()
    code += cmp_imm(1, 0)  # child
    code += bxeq_lr()
    code += cmp_imm(0, 0)  # parent
    code += bxeq_lr()
    code += ATTACH_EXPECT  # original PUSH
    code += b_ins(ATTACH_CAVE + len(code), ATTACH_RESUME)
    if len(code) != ATTACH_CAVE_LEN:
        raise ValueError(f"attach cave {len(code):#x} != {ATTACH_CAVE_LEN:#x}")
    return bytes(code)


def build_find_cave() -> bytes:
    code = bytearray()
    code += cmp_imm(4, 4)
    code += beq(FIND_CAVE + len(code), FIND_NOT_FOUND)
    code += cmp_imm(4, 0)
    code += beq(FIND_CAVE + len(code), FIND_NOT_FOUND)
    code += cmp_imm(3, 0)
    code += beq(FIND_CAVE + len(code), FIND_CONTINUE)
    code += blx_r3()
    code += b_ins(FIND_CAVE + len(code), FIND_RESUME)
    if len(code) != FIND_CAVE_LEN:
        raise ValueError(f"find cave {len(code):#x} != {FIND_CAVE_LEN:#x}")
    return bytes(code)


def attach_already(data: bytes) -> bool:
    return bytes(data[ATTACH_SITE : ATTACH_SITE + 4]) == b_ins(ATTACH_SITE, ATTACH_CAVE)


def find_already(data: bytes) -> bool:
    return bytes(data[FIND_SITE : FIND_SITE + 4]) == b_ins(FIND_SITE, FIND_CAVE)


def is_patched(data: bytes) -> bool:
    return attach_already(data) and find_already(data)


def _install(data: bytearray, site: int, expect: bytes, cave: int, cave_len: int, blob: bytes) -> None:
    site_b = bytes(data[site : site + 4])
    already = site_b == b_ins(site, cave)
    if site_b != expect and not already:
        raise ValueError(
            f"unexpected bytes at {site:#x}: {site_b.hex()} "
            f"(expected {expect.hex()} or branch to {cave:#x})"
        )
    if not already:
        region = bytes(data[cave : cave + cave_len])
        if region != b"\x00" * cave_len:
            raise ValueError(f"cave @{cave:#x} not empty: {region.hex()}")
    data[cave : cave + cave_len] = blob
    data[site : site + 4] = b_ins(site, cave)


def apply_patch(data: bytearray) -> None:
    _install(data, ATTACH_SITE, ATTACH_EXPECT, ATTACH_CAVE, ATTACH_CAVE_LEN, build_attach_cave())
    _install(data, FIND_SITE, FIND_EXPECT, FIND_CAVE, FIND_CAVE_LEN, build_find_cave())
    print(
        f"[lyt-null-pane] attach @{ATTACH_SITE:#x} -> {ATTACH_CAVE:#x}, "
        f"find @{FIND_SITE:#x} -> {FIND_CAVE:#x}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        build_attach_cave()
        build_find_cave()
        print("dry-run OK")
        return 0
    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")

    dest = Path.home() / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")
    bak = dest.with_name(dest.name + ".bak_pre_lyt_null_pane")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    apply_patch(data)
    dest.write_bytes(data)
    shutil.copy2(dest, dest.parent.parent / "code.bin")
    print("Rollback: copy bak_pre_lyt_null_pane -> code.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
