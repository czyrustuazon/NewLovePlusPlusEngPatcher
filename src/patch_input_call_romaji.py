#!/usr/bin/env python3
"""ASCII Called-name candidates (Profile 呼ばれ方 list).

Vanilla indexes the Called string as 3-byte hiragana (``r10*3`` / ``add #3``).
Romaji insert is 1-byte ASCII, so the walker steps past the NUL into leftover
kana — the list then shows a stray ``づ`` (pack 0x7000 slot 0x40) no matter
what Latin name you typed.

This patch:
  1. Walks UTF-8 character sizes instead of *3
  2. For a non-empty ASCII Called name, skips the JP dictionary and draws
     the typed string as candidate 0 (so AKIKO is selectable)

Ships in ``deploy_name_input_en.py`` / ``release/name_input_code.bin``.
"""
from __future__ import annotations

import argparse
import struct

from patch_input_cave_map import TEXT_PAGE_END
from patch_input_romaji import (
    add_imm,
    add_reg,
    b_ins,
    bl,
    cmp_imm,
    ldrb_imm,
    mov_imm,
    mov_reg,
    pop,
    push,
    sub_imm,
)

ADDR_UTF8_LEN = 0x005BF4E8

SITE_INDEX_MUL3 = 0x00147904  # add r0, r10, r10, lsl #1
ORIG_INDEX_MUL3 = bytes.fromhex("8a008ae0")

SITE_ZU_ADV = 0x00148098  # add r4, r4, #3
ORIG_ZU_ADV = bytes.fromhex("034084e2")

SITE_CALL01 = 0x0023E468
SITE_CALL02 = 0x001F1A6C
ORIG_PROLOGUE = bytes.fromhex("f34f2de959df4de2")  # stmdb …; sub sp, #0x164

NOP = bytes.fromhex("00f020e3")


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def b_cond(cond: int, here: int, target: int) -> bytes:
    return u32((cond << 28) | 0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def cave_addr() -> int:
    from patch_input_strcat_raw import build_blob as strcat_blob
    from patch_input_strcat_raw import cave_addr as strcat_cave

    sc = strcat_cave()
    return sc + len(strcat_blob(base=sc))


def _bl_target(data: bytes, site: int) -> int | None:
    insn = int.from_bytes(data[site : site + 4], "little")
    kind = insn >> 24
    if kind not in (0xEB, 0xEA):
        return None
    imm = insn & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    return site + 8 + (imm << 2)


def is_patched(data: bytes) -> bool:
    tgt = _bl_target(data, SITE_INDEX_MUL3)
    return tgt is not None and tgt == cave_addr()


def _build_stream() -> list:
    stream: list = []

    def OP(b: bytes) -> None:
        stream.append(("op", b))

    def L(name: str) -> None:
        stream.append(("label", name))

    def BL(addr: int) -> None:
        stream.append(("bl", addr))

    def B(name: str, cond: int | None = None) -> None:
        stream.append(("b", name, cond))

    def BABS(addr: int) -> None:
        stream.append(("b_abs", addr))

    L("utf8_off")
    OP(push(0x400E))  # r1-r3, lr
    OP(mov_reg(1, 6))
    OP(mov_reg(2, 10))
    OP(mov_imm(3, 0))
    L("off_loop")
    OP(cmp_imm(2, 0))
    B("off_done", cond=0x0)
    OP(ldrb_imm(0, 1, 0))
    OP(cmp_imm(0, 0))
    B("off_done", cond=0x0)
    BL(ADDR_UTF8_LEN)
    OP(add_reg(1, 1, 0))
    OP(add_reg(3, 3, 0))
    OP(sub_imm(2, 2, 1))
    B("off_loop")
    L("off_done")
    OP(mov_reg(0, 3))
    OP(pop(0x800E))

    L("utf8_adv")
    # Replaces `add r4, #3` between `cmp r7, r10` and `blt`. ADD does not
    # clobber flags; BL / GetUtf8CharByteLength would, so save CPSR_f in r12
    # (walk loop does not keep r12 live).
    OP(push(0x4003))  # r0, r1, lr
    OP(bytes.fromhex("00c00fe1"))  # mrs r12, cpsr
    OP(ldrb_imm(0, 4, 0))
    BL(ADDR_UTF8_LEN)
    OP(add_reg(4, 4, 0))
    OP(bytes.fromhex("0cf028e1"))  # msr cpsr_f, r12
    OP(pop(0x8003))

    # r3 = 0 Call01 / 1 Call02. r0=obj, r1=name.
    L("call01")
    OP(mov_imm(3, 0))
    B("ascii_chk")

    L("call02")
    OP(mov_imm(3, 1))

    L("ascii_chk")
    OP(cmp_imm(1, 0))
    B("not_ascii", cond=0x0)
    OP(push(0x1001))  # r0, r12
    OP(ldrb_imm(0, 1, 0))
    OP(cmp_imm(0, 0))
    B("asc_fail", cond=0x0)
    OP(mov_reg(12, 1))
    L("asc_scan")
    OP(ldrb_imm(0, 12, 0))
    OP(add_imm(12, 12, 1))
    OP(cmp_imm(0, 0))
    B("asc_ok", cond=0x0)
    OP(cmp_imm(0, 0x80))
    B("asc_fail", cond=0x2)  # hs
    B("asc_scan")
    L("asc_fail")
    OP(pop(0x1001))
    B("not_ascii")
    L("asc_ok")
    OP(pop(0x1001))
    # Vanilla frame, then jump into the existing strncpy+DrawText tail
    # with r1 still the typed name (skip the TRB `add r1, sp, …`).
    # r9 = 1 matches vanilla before FUN_00147e04 (str r9, [sp] extra-arg).
    OP(ORIG_PROLOGUE[:4])
    OP(ORIG_PROLOGUE[4:])
    OP(mov_imm(9, 1))
    OP(cmp_imm(3, 0))
    B("asc02", cond=0x1)  # ne
    OP(mov_reg(6, 0))
    OP(mov_imm(7, 1))
    BABS(0x0023E4F4)
    L("asc02")
    OP(mov_reg(7, 0))
    OP(mov_imm(6, 1))
    BABS(0x001F1AD8)

    L("not_ascii")
    OP(ORIG_PROLOGUE[:4])
    OP(ORIG_PROLOGUE[4:])
    OP(cmp_imm(3, 0))
    B("van02", cond=0x1)
    BABS(SITE_CALL01 + 8)
    L("van02")
    BABS(SITE_CALL02 + 8)
    return stream


def _assemble(base: int, stream: list) -> tuple[bytes, dict[str, int]]:
    labs: dict[str, int] = {}
    addr = base
    for it in stream:
        if it[0] == "label":
            labs[it[1]] = addr
        else:
            addr += 4

    out = bytearray()
    addr = base
    for it in stream:
        kind = it[0]
        if kind == "label":
            continue
        if kind == "op":
            out.extend(it[1])
        elif kind == "bl":
            out.extend(bl(addr, it[1]))
        elif kind == "b":
            cond, tgt = it[2], labs[it[1]]
            out.extend(b_ins(addr, tgt) if cond is None else b_cond(cond, addr, tgt))
        elif kind == "b_abs":
            out.extend(b_ins(addr, it[1]))
        else:
            raise ValueError(it)
        addr += 4
    return bytes(out), labs


def build_blob(base: int | None = None) -> tuple[bytes, dict[str, int]]:
    if base is None:
        base = cave_addr()
    return _assemble(base, _build_stream())


def apply_patch(data: bytearray) -> bool:
    base = cave_addr()
    blob, labs = build_blob(base=base)
    end = base + len(blob)
    if end > TEXT_PAGE_END:
        raise ValueError(f"call-romaji cave {end:#x} past .text {TEXT_PAGE_END:#x}")
    if is_patched(data):
        print(f"[call-romaji] already patched cave @{base:#x}")
        return False

    if bytes(data[SITE_INDEX_MUL3 : SITE_INDEX_MUL3 + 4]) != ORIG_INDEX_MUL3:
        raise ValueError(f"unexpected *3 at {SITE_INDEX_MUL3:#x}")
    if bytes(data[SITE_ZU_ADV : SITE_ZU_ADV + 4]) != ORIG_ZU_ADV:
        raise ValueError(f"unexpected +3 at {SITE_ZU_ADV:#x}")
    if bytes(data[SITE_CALL01 : SITE_CALL01 + 8]) != ORIG_PROLOGUE:
        raise ValueError(f"unexpected Call01 prologue at {SITE_CALL01:#x}")
    if bytes(data[SITE_CALL02 : SITE_CALL02 + 8]) != ORIG_PROLOGUE:
        raise ValueError(f"unexpected Call02 prologue at {SITE_CALL02:#x}")

    data[base:end] = blob
    data[SITE_INDEX_MUL3 : SITE_INDEX_MUL3 + 4] = bl(SITE_INDEX_MUL3, labs["utf8_off"])
    data[SITE_ZU_ADV : SITE_ZU_ADV + 4] = bl(SITE_ZU_ADV, labs["utf8_adv"])
    data[SITE_CALL01 : SITE_CALL01 + 4] = b_ins(SITE_CALL01, labs["call01"])
    data[SITE_CALL01 + 4 : SITE_CALL01 + 8] = NOP
    data[SITE_CALL02 : SITE_CALL02 + 4] = b_ins(SITE_CALL02, labs["call02"])
    data[SITE_CALL02 + 4 : SITE_CALL02 + 8] = NOP
    print(f"[call-romaji] UTF-8 walk + ASCII Called fallback cave @{base:#x} ({len(blob):#x})")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    base = cave_addr()
    blob, labs = build_blob(base=base)
    print(f"call-romaji {len(blob):#x} @ {base:#x}")
    print("  labels", {k: hex(v) for k, v in labs.items()})
    print(
        f"  end {base + len(blob):#x} text_end {TEXT_PAGE_END:#x} "
        f"free {TEXT_PAGE_END - (base + len(blob)):#x}"
    )
    if args.dry_run:
        return 0
    raise SystemExit("applied via deploy_name_input_en.py")


if __name__ == "__main__":
    raise SystemExit(main())
