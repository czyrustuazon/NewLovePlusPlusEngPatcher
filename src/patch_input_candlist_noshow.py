#!/usr/bin/env python3
"""C4: place exactly 6 kanji in the left column (cells 9..4, top→bottom).

Skips the vanilla nested fill loops entirely after the clear + header setup.
Does not SHOW B_Place.

  python src/patch_input_candlist_noshow.py --deploy-azahar
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

BL_SITE = 0x001FB150
VT_BP_TOUCH = 0x00713CD0
VANILLA_BL = bytes.fromhex("b80000eb")
VANILLA_VT = struct.pack("<I", 0x0033CD8C)

LOOP_ENTRY = 0x001FB618
LOOP_JOIN = 0x001FB6EC  # BindGridAxisPanes setup

ADDR_RESOLVE = 0x005C0D4C
ADDR_DRAW_CELL = 0x001FC304
ADDR_EMPTY_STR = 0x001FB738  # "" used by vanilla clear loop

ADDR_CAVE = 0x006FC000
CAVE_MAX = 0x200

VANILLA_DUMP = (
    Path(__file__).resolve().parents[2]
    / "New Love Plus Plus/extracted/exefs/code.bin"
)

RESTORE_RANGE = (0x001FB618, 0x001FB6EC)


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def b_ins(src: int, dst: int) -> bytes:
    off = (dst - src - 8) >> 2
    return u32(0xEA000000 | (off & 0xFFFFFF))


def bl_ins(src: int, dst: int) -> bytes:
    off = (dst - src - 8) >> 2
    return u32(0xEB000000 | (off & 0xFFFFFF))


def build_placer() -> bytes:
    """Wipe all 60 cells, then place ≤6 kanji at left-col cells 9..4.

    Incoming (vanilla state at LOOP_ENTRY):
      r6 = nameInputObj
      r8 = bank (0/1 from +0x24)
      sp+0x20 = stride table (2 words)
      sp+0x4c = pack ushort*
      sp+0x60 = base-slot ushort*
      [r6+0x38] = page index
    """
    code = bytearray()
    base = ADDR_CAVE

    def here() -> int:
        return base + len(code)

    def emit(word: int) -> None:
        code.extend(u32(word))

    # ---- wipe every cell (DrawCell + clear meta) so nothing stale remains ----
    emit(0xE3A04000)  # mov r4, #0
    wipe = here()
    emit(0xE354003C)  # cmp r4, #0x3c
    br_wipe_done = len(code)
    emit(0)  # bge after_wipe

    emit(0xE59F0000)  # ldr r0, [pc, ...] — patched below to empty str VA
    # placeholder; fix PC-relative after we know lit pool site
    lit_empty_ref = len(code) - 4

    emit(0xE1A02000)  # mov r2, r0        ; str
    emit(0xE1A01004)  # mov r1, r4        ; cellIdx
    emit(0xE1A00006)  # mov r0, r6
    emit(int.from_bytes(bl_ins(here(), ADDR_DRAW_CELL), "little"))

    emit(0xE0860204)  # add r0, r6, r4, lsl #4
    emit(0xE3A01000)  # mov r1, #0
    emit(0xE3E02000)  # mvn r2, #0
    emit(0xE5801180)  # str r1, [r0, #0x180]
    emit(0xE5C01184)  # strb r1, [r0, #0x184]
    emit(0xE5C01185)  # strb r1, [r0, #0x185]
    emit(0xE580218C)  # str r2, [r0, #0x18c]

    emit(0xE2844001)  # add r4, #1
    emit(int.from_bytes(b_ins(here(), wipe), "little"))

    after_wipe = here()
    off = (after_wipe - (base + br_wipe_done) - 8) >> 2
    struct.pack_into("<I", code, br_wipe_done, 0xAA000000 | (off & 0xFFFFFF))

    # ---- place up to 6 candidates ----
    emit(0xE3A04000)  # mov r4, #0
    loop = here()
    emit(0xE3540006)  # cmp r4, #6
    br_done_off = len(code)
    emit(0)  # bge done

    # slot = page * stride[bank] + *baseSlot + (i+1)
    # mul r0, r0, r1  (Rd=Rm=r0, Rs=r1) → page * stride
    emit(0xE5960038)  # ldr r0, [r6, #0x38]     ; page
    emit(0xE28D1020)  # add r1, sp, #0x20
    emit(0xE7911108)  # ldr r1, [r1, r8, lsl #2] ; stride
    emit(0xE0000091)  # mul r0, r0, r1
    emit(0xE59D1060)  # ldr r1, [sp, #0x60]
    emit(0xE1D110B0)  # ldrh r1, [r1]           ; *baseSlot
    emit(0xE0800001)  # add r0, r0, r1
    emit(0xE2800001)  # add r0, r0, #1
    emit(0xE0800004)  # add r0, r0, r4
    emit(0xE6FF1070)  # uxth r1, r0             ; slot
    emit(0xE59D004C)  # ldr r0, [sp, #0x4c]
    emit(0xE1D000B0)  # ldrh r0, [r0]           ; pack
    emit(int.from_bytes(bl_ins(here(), ADDR_RESOLVE), "little"))

    emit(0xE3500000)  # cmp r0, #0
    br_next_off = len(code)
    emit(0)  # beq next

    # cellIdx = 9 - i
    emit(0xE3A05009)  # mov r5, #9
    emit(0xE0455004)  # sub r5, r5, r4
    emit(0xE58D0008)  # str r0, [sp, #8]
    emit(0xE1A02000)  # mov r2, r0
    emit(0xE1A01005)  # mov r1, r5
    emit(0xE1A00006)  # mov r0, r6
    emit(int.from_bytes(bl_ins(here(), ADDR_DRAW_CELL), "little"))

    emit(0xE59D2008)  # ldr r2, [sp, #8]
    emit(0xE0860205)  # add r0, r6, r5, lsl #4
    emit(0xE3A01001)  # mov r1, #1
    emit(0xE5802180)  # str r2, [r0, #0x180]
    emit(0xE5C01184)  # strb r1, [r0, #0x184]
    emit(0xE5C01185)  # strb r1, [r0, #0x185]
    emit(0xE580518C)  # str r5, [r0, #0x18c]
    emit(0xE59D104C)  # ldr r1, [sp, #0x4c]
    emit(0xE2800C01)  # add r0, r0, #0x100
    emit(0xE1D110B0)  # ldrh r1, [r1]
    emit(0xE1C018B6)  # strh r1, [r0, #0x86]

    # recompute slot for meta +0x188
    emit(0xE5960038)  # ldr r0, [r6, #0x38]
    emit(0xE28D1020)  # add r1, sp, #0x20
    emit(0xE7911108)  # ldr r1, [r1, r8, lsl #2]
    emit(0xE0000091)  # mul r0, r0, r1
    emit(0xE59D1060)  # ldr r1, [sp, #0x60]
    emit(0xE1D110B0)  # ldrh r1, [r1]
    emit(0xE0800001)  # add r0, r0, r1
    emit(0xE2800001)  # add r0, r0, #1
    emit(0xE0800004)  # add r0, r0, r4
    emit(0xE0861205)  # add r1, r6, r5, lsl #4
    emit(0xE2811C01)  # add r1, r1, #0x100
    emit(0xE1C108B8)  # strh r0, [r1, #0x88]

    next_i = here()
    off = (next_i - (base + br_next_off) - 8) >> 2
    struct.pack_into("<I", code, br_next_off, 0x0A000000 | (off & 0xFFFFFF))

    emit(0xE2844001)  # add r4, #1
    emit(int.from_bytes(b_ins(here(), loop), "little"))

    done = here()
    off = (done - (base + br_done_off) - 8) >> 2
    struct.pack_into("<I", code, br_done_off, 0xAA000000 | (off & 0xFFFFFF))

    # Prevent NameInput_Tick → FillGridFromResourceTable from repainting all 60
    # cells (it runs when +0x44!=0 and +0x540==0; FillCandidates clears +0x540).
    emit(0xE3A00001)  # mov r0, #1
    emit(0xE5C60540)  # strb r0, [r6, #0x540]

    emit(int.from_bytes(b_ins(here(), LOOP_JOIN), "little"))

    # literal pool (must be 4-aligned, after a B so never executed)
    while len(code) & 3:
        code.append(0)
    # Fix the wipe-loop ldr r0, [pc+imm] to point at this literal
    lit_at = len(code)
    # ldr at lit_empty_ref: address of ldr insn = base + lit_empty_ref
    ldr_pc = base + lit_empty_ref
    # PC when executing ldr = ldr_pc + 8
    imm = (base + lit_at) - (ldr_pc + 8)
    assert 0 <= imm < 4096 and imm % 4 == 0, imm
    struct.pack_into("<I", code, lit_empty_ref, 0xE59F0000 | imm)
    # store runtime VA of empty string (file + 0x100000)
    code.extend(u32(0x100000 + ADDR_EMPTY_STR))

    if len(code) > CAVE_MAX:
        raise RuntimeError(f"cave too large: {len(code):#x}")
    blob = bytearray(b"\x00" * CAVE_MAX)
    blob[: len(code)] = code
    return bytes(blob)


def apply_patch(data: bytearray, van: bytes) -> None:
    data[BL_SITE : BL_SITE + 4] = VANILLA_BL
    data[VT_BP_TOUCH : VT_BP_TOUCH + 4] = VANILLA_VT

    lo, hi = RESTORE_RANGE
    data[lo:hi] = van[lo:hi]

    for off in (0x001FB6EC, 0x001FB724):
        data[off : off + 4] = van[off : off + 4]

    data[ADDR_CAVE : ADDR_CAVE + 0x580] = b"\x00" * 0x580
    cave = build_placer()
    data[ADDR_CAVE : ADDR_CAVE + len(cave)] = cave

    data[LOOP_ENTRY : LOOP_ENTRY + 4] = b_ins(LOOP_ENTRY, ADDR_CAVE)
    for i in range(1, 4):
        data[LOOP_ENTRY + 4 * i : LOOP_ENTRY + 4 * i + 4] = u32(0xE320F000)

    print(
        f"[candlist-noshow] wipe+placer @{ADDR_CAVE:#x} "
        f"→ cells 9..4, join {LOOP_JOIN:#x}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.dry_run:
        cave = build_placer()
        print(f"size {len(cave)}")
        # verify mul encoding
        assert b"\x91\x00\x00\xe0" in cave[:200] or cave.find(bytes.fromhex("910000e0")) >= 0
        print("mul ok", cave.hex()[:80])
        return 0
    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")
    dest = (
        Path.home()
        / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    )
    bak = dest.with_name(dest.name + ".bak_pre_candlist_noshow")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)
    van = VANILLA_DUMP.read_bytes()
    data = bytearray(dest.read_bytes())
    apply_patch(data, van)
    dest.write_bytes(data)
    shutil.copy2(dest, dest.parent.parent / "code.bin")
    print("Fully quit Azahar. Expect ~6 kanji on the LEFT only (no SU prefix).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
