#!/usr/bin/env python3
"""ASCII Called-name candidates (Profile 呼ばれ方 list).

Vanilla indexes the Called string as 3-byte hiragana (``r10*3`` / ``add #3``).
Romaji insert is 1-byte ASCII, so the walker steps past the NUL into leftover
kana — the list then shows a stray ``づ`` (pack 0x7000 slot 0x40) no matter
what Latin name you typed.

This patch:
  1. Walks UTF-8 character sizes instead of *3
  2. When the JP dictionary finds no candidate for a non-empty Called name,
     draws the typed string as candidate 0. ASCII never matches a hiragana
     reading, so AKIKO always lands here; so does a hiragana name that is
     not in pack 0x7100 / 0x7200.

``GetUtf8CharByteLength`` (``0x005BF4E8``) always writes ``r1`` (``mov r1, r0``)
and writes ``r2`` on multibyte leads. The ``*3`` walk must keep its cursor in
registers that call leaves alone (``r3`` byte offset, saved ``r4`` count,
base ``r6``). Holding the pointer in ``r1`` data-aborts on hardware: ASCII
``T`` (``0x54``) comes back in ``r1``, and the next ``ldrb`` reads ``0x55``.

Ships in ``deploy_name_input_en.py`` / ``release/name_input_code.bin``.
"""
from __future__ import annotations

import argparse
import struct

from patch_input_cave_map import ADDR_COMMU_HEADER_CAVE, TEXT_PAGE_END
from patch_input_romaji import (
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

# FUN_0023e468 (Call01) / FUN_001f1a6c (Call02) both leave through
# `add sp, sp, #0x16c`. Candidate count is r7 (Call01) / r6 (Call02).
SITE_EXIT01 = 0x0023E668
SITE_EXIT02 = 0x001F1C58
ORIG_EXIT = bytes.fromhex("5bdf8de2")  # add sp, sp, #0x16c
# Candidate-0 strncpy+DrawText, entered with r1 = string to draw.
CALL01_DRAW0 = 0x0023E4F4
CALL02_DRAW0 = 0x001F1AD8
LDR_NAME = bytes.fromhex("68119de5")  # ldr r1, [sp, #0x168] (saved name arg)


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
    # r6 = Called string, r10 = char index. Return byte offset in r0.
    # Count lives in r4 (dead at the *3 site, saved anyway). Offset lives in
    # r3. Both survive GetUtf8CharByteLength; r1/r2 do not.
    OP(push(0x401E))  # r1-r4, lr
    OP(mov_reg(4, 10))
    OP(mov_imm(3, 0))
    L("off_loop")
    OP(cmp_imm(4, 0))
    B("off_done", cond=0x0)
    OP(u32(0xE7D60003))  # ldrb r0, [r6, r3]
    OP(cmp_imm(0, 0))
    B("off_done", cond=0x0)
    BL(ADDR_UTF8_LEN)
    OP(add_reg(3, 3, 0))
    OP(sub_imm(4, 4, 1))
    B("off_loop")
    L("off_done")
    OP(mov_reg(0, 3))
    OP(pop(0x801E))  # r1-r4, pc

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

    # No-match fallback. Count 0 and a non-empty name: count = 1, then draw
    # the typed name through the candidate-0 tail (skips the TRB
    # `add r1, sp, …`). That tail reruns the ず/づ pass, which finds nothing
    # again, and comes back here with count 1. r9 is still 1 and obj is
    # still r6 (Call01) / r7 (Call02), as the tail expects.
    for n, count_reg, draw0, site in (
        ("01", 7, CALL01_DRAW0, SITE_EXIT01),
        ("02", 6, CALL02_DRAW0, SITE_EXIT02),
    ):
        L("nomatch" + n)
        OP(cmp_imm(count_reg, 0))
        B("done" + n, cond=0x1)  # ne
        OP(LDR_NAME)
        OP(cmp_imm(1, 0))
        B("done" + n, cond=0x0)
        OP(ldrb_imm(0, 1, 0))
        OP(cmp_imm(0, 0))
        B("done" + n, cond=0x0)
        OP(mov_imm(count_reg, 1))
        BABS(draw0)
        L("done" + n)
        OP(ORIG_EXIT)
        BABS(site + 4)
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
    if end > ADDR_COMMU_HEADER_CAVE:
        raise ValueError(
            f"call-romaji cave {end:#x} overlaps commu header {ADDR_COMMU_HEADER_CAVE:#x}"
        )
    if is_patched(data):
        print(f"[call-romaji] already patched cave @{base:#x}")
        return False

    if bytes(data[SITE_INDEX_MUL3 : SITE_INDEX_MUL3 + 4]) != ORIG_INDEX_MUL3:
        raise ValueError(f"unexpected *3 at {SITE_INDEX_MUL3:#x}")
    if bytes(data[SITE_ZU_ADV : SITE_ZU_ADV + 4]) != ORIG_ZU_ADV:
        raise ValueError(f"unexpected +3 at {SITE_ZU_ADV:#x}")
    for site in (SITE_EXIT01, SITE_EXIT02):
        if bytes(data[site : site + 4]) != ORIG_EXIT:
            raise ValueError(f"unexpected Called exit at {site:#x}")
    if any(data[base:end]):
        raise ValueError(f"call-romaji cave {base:#x}..{end:#x} is not empty pad")

    data[base:end] = blob
    data[SITE_INDEX_MUL3 : SITE_INDEX_MUL3 + 4] = bl(SITE_INDEX_MUL3, labs["utf8_off"])
    data[SITE_ZU_ADV : SITE_ZU_ADV + 4] = bl(SITE_ZU_ADV, labs["utf8_adv"])
    data[SITE_EXIT01 : SITE_EXIT01 + 4] = b_ins(SITE_EXIT01, labs["nomatch01"])
    data[SITE_EXIT02 : SITE_EXIT02 + 4] = b_ins(SITE_EXIT02, labs["nomatch02"])
    print(f"[call-romaji] UTF-8 walk + no-match Called fallback cave @{base:#x} ({len(blob):#x})")
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
