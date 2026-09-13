#!/usr/bin/env python3
"""Replace Profile name strcat (FUN_002573ac) with byte strcat + mora cleanup.

Vanilla MakeStr-truncates dest to (maxglyphs-1) then strncat. Hepburn pending
(KA/KE/KU) can arrive as KKE or match っ; the field becomes KAKKE instead of
KAKEKU.

This rewrite:
  1. Copies pending to a stack slot
  2. Strips a trailing '.' (Hepburn cell canary)
  3. Collapses doubled-consonant 3-letter pending (KKE → KE)
  4. Truncates dest to 8 UTF-8 characters (hardcoded; strncpy clobbers r3)
  5. Skips the join when dest+pending would exceed that cap
  6. strncat onto dest (same FUN_00000b1c as vanilla, via BLX)

Do not drop step 4/5 — TickPoller passes dest capacity 0x20/0x40 bytes, but the
name plate / save slot is 8 glyphs. Uncapped strcat overflows the dialogue tag.
Do not trust caller r3 across Runtime_StrNCpyZeroFill — a leftover r3==4
caps Hepburn at two taps (KAKE).
"""
from __future__ import annotations

import argparse

from patch_input_romaji import (
    ADDR_CAVE,
    ADDR_MEMCPY7,
    _assemble,
    add_imm,
    add_imm_cond,
    add_reg,
    and_imm,
    b_ins,
    build_romaji_blob,
    cmp_imm,
    cmp_reg,
    ldrb_imm,
    ldrb_post,
    mov_imm,
    mov_reg,
    pop,
    push,
    str_imm,
    sub_imm,
    u32,
)
from patch_input_cave_map import TEXT_PAGE_END

ADDR = 0x002573AC
SIZE = 0xB0  # 0x002573AC .. 0x0025745B
ADDR_STRN = ADDR_MEMCPY7
ADDR_STRCAT = 0x00000B1C
VANILLA_HEAD = bytes.fromhex("f0402de90160a0e1")
NOP = bytes.fromhex("00f020e3")


def strb_imm(rd: int, rn: int, imm: int = 0) -> bytes:
    return u32(0xE5C00000 | (rn << 16) | (rd << 12) | imm)


def build_blob(base: int = ADDR) -> bytes:
    stream: list = []

    def OP(b: bytes) -> None:
        stream.append(("op", b))

    def L(name: str) -> None:
        stream.append(("label", name))

    def BL(target: int) -> None:
        stream.append(("bl", target))

    def BLX(target: int) -> None:
        stream.append(("blx", target))

    def B(name: str, cond: int | None = None) -> None:
        stream.append(("b", name, cond))

    OP(push(0x40F0))  # r4-r7, lr
    OP(sub_imm(13, 13, 8))
    OP(mov_reg(4, 0))  # dest
    OP(mov_reg(5, 1))  # maxbytes (pending copy cap)
    OP(mov_reg(6, 2))  # pending

    OP(mov_imm(0, 0))
    OP(str_imm(0, 13, 0))
    OP(str_imm(0, 13, 4))
    OP(mov_reg(0, 13))
    OP(mov_reg(1, 6))
    OP(mov_imm(2, 7))
    BL(ADDR_STRN)

    # Strip one trailing '.'
    OP(ldrb_imm(0, 13, 2))
    OP(cmp_imm(0, 0x2E))
    B("try_dot1", 0x1)
    OP(ldrb_imm(1, 13, 3))
    OP(cmp_imm(1, 0))
    B("try_dot1", 0x1)
    OP(mov_imm(0, 0))
    OP(strb_imm(0, 13, 2))
    B("collapse", None)

    L("try_dot1")
    OP(ldrb_imm(0, 13, 1))
    OP(cmp_imm(0, 0x2E))
    B("collapse", 0x1)
    OP(ldrb_imm(1, 13, 2))
    OP(cmp_imm(1, 0))
    B("collapse", 0x1)
    OP(mov_imm(0, 0))
    OP(strb_imm(0, 13, 1))

    # KKE / TTA / PPA → drop the extra consonant
    L("collapse")
    OP(ldrb_imm(0, 13, 0))
    OP(ldrb_imm(1, 13, 1))
    OP(ldrb_imm(2, 13, 2))
    OP(ldrb_imm(3, 13, 3))
    OP(cmp_imm(3, 0))
    B("cap", 0x1)
    OP(cmp_imm(2, 0))
    B("cap", 0x0)
    OP(cmp_reg(0, 1))
    B("cap", 0x1)
    OP(strb_imm(1, 13, 0))
    OP(strb_imm(2, 13, 1))
    OP(strb_imm(3, 13, 2))

    L("cap")
    OP(mov_imm(7, 8))  # after strncpy; 8 ASCII / 8 kana
    OP(mov_reg(0, 4))
    OP(mov_imm(3, 0))
    L("trunc")
    OP(ldrb_imm(1, 0, 0))
    OP(cmp_imm(1, 0))
    B("trunc_done", 0x0)
    OP(and_imm(2, 1, 0xC0))
    OP(cmp_imm(2, 0x80))
    B("trunc_adv", 0x0)
    OP(cmp_reg(3, 7))
    B("trunc_cut", 0x2)
    OP(add_imm(3, 3, 1))
    L("trunc_adv")
    OP(add_imm(0, 0, 1))
    B("trunc", None)
    L("trunc_cut")
    OP(mov_imm(1, 0))
    OP(strb_imm(1, 0, 0))
    L("trunc_done")

    OP(mov_reg(0, 13))
    OP(mov_imm(2, 0))
    L("pcnt")
    OP(ldrb_post(1, 0, 1))
    OP(cmp_imm(1, 0))
    B("pcnt_done", 0x0)
    OP(and_imm(1, 1, 0xC0))
    OP(cmp_imm(1, 0x80))
    OP(add_imm_cond(0x1, 2, 2, 1))
    B("pcnt", None)
    L("pcnt_done")

    OP(add_reg(3, 3, 2))
    OP(cmp_reg(3, 7))
    B("skip", 0x8)

    L("strcat")
    OP(mov_reg(0, 4))
    OP(mov_reg(1, 13))
    OP(mov_reg(2, 5))
    BLX(ADDR_STRCAT)

    L("skip")
    OP(add_imm(13, 13, 8))
    OP(pop(0x80F0))  # r4-r7, pc

    return _assemble(base, stream)


def cave_addr() -> int:
    return ADDR_CAVE + len(build_romaji_blob())


def is_patched(data: bytes) -> bool:
    insn = int.from_bytes(data[ADDR : ADDR + 4], "little")
    if (insn & 0xFF000000) != 0xEA000000:
        return False
    imm = insn & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    return ADDR + 8 + (imm << 2) == cave_addr()


def apply_patch(data: bytearray) -> None:
    cave = cave_addr()
    blob = build_blob(base=cave)
    end = cave + len(blob)
    if end > TEXT_PAGE_END:
        raise ValueError(f"strcat cave {end:#x} past .text {TEXT_PAGE_END:#x}")
    head = bytes(data[ADDR : ADDR + 8])
    if head != VANILLA_HEAD and not is_patched(data):
        raise ValueError(f"unexpected FUN_002573ac head {head.hex()}")
    data[cave : end] = blob
    data[ADDR : ADDR + 4] = b_ins(ADDR, cave)
    data[ADDR + 4 : ADDR + SIZE] = NOP * ((SIZE - 4) // 4)
    print(f"[strcat-raw] FUN_002573ac -> cave @{cave:#x} ({len(blob):#x})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    blob = build_blob(base=cave_addr())
    print(f"strcat-raw {len(blob):#x} @ {cave_addr():#x}")
    if args.dry_run:
        return 0
    raise SystemExit("applied via deploy_name_input_en.py")


if __name__ == "__main__":
    raise SystemExit(main())
