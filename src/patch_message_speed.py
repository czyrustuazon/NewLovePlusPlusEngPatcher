#!/usr/bin/env python3
"""Faster Message Speed typewriter (Options preview + in-game talk).

Two independent tables plus a voice/script cap:

1. Options preview ``FUN_005d1e18`` @ file ``0x005D1E18`` (slider → frames/glyph):

       1 → 18    2 → 12    3 → 6    4 → 0 (instant)
   patched: 1 → 14    2 → 8     3 → 2    4 → 0

   Only the Display Settings sample uses this (``FUN_001d2e5c``).

2. In-game TalkWindow @ ``0x006E3024`` (index → wait units):

       index 0..4 = 40, 70, 90, 110, 220   (5 = 0 unused)
   patched:          10, 18, 22,  28,  55

   Saved rate ``cfg+0x0C`` (0x3F/0x7F/0xBF/0xFF) is mapped by ``FUN_002d8874``
   to index 3/2/1/0 and stored at TalkWindow ``+0xd9c``. Tick ``0x0013B6C4``.

3. Tick ``0x0013B718`` cave: after table / ``+0xd5c`` script / ``+0xd60`` voice
   delay is chosen, ``r2 = min(r2, table[index])``. Unvoiced player lines already
   use the table; voiced heroine lines otherwise ignore it.

Ghidra image base 0; runtime VA = file + ``0x100000``. See technical.md §21.

  python src/patch_message_speed.py --dry-run
  python src/patch_message_speed.py --deploy-azahar
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from patch_input_cave_map import ADDR_TALK_CAP_CAVE, TALK_CAP_CAVE_LEN, TEXT_PAGE_END

# FUN_005d1e18 — cmp r0,#1 / moveq r0,#imm / beq …
ADDR_FN = 0x005D1E18
# moveq r0, #delay  (cond EQ, MOV imm)
OFF_LV1 = 0x005D1E1C
OFF_LV2 = 0x005D1E28
OFF_LV3 = 0x005D1E34
OFF_LV4 = 0x005D1E40  # already 0; not rewritten

_MOV_EQ_R0 = bytes.fromhex("00a003")  # little-endian tail of MOV r0,#imm (cond EQ)


def _mov_eq_r0(imm: int) -> bytes:
    if not 0 <= imm <= 255:
        raise ValueError(f"imm8 out of range: {imm}")
    return bytes((imm,)) + _MOV_EQ_R0


VANILLA_LV1 = _mov_eq_r0(0x12)  # 18
VANILLA_LV2 = _mov_eq_r0(0x0C)  # 12
VANILLA_LV3 = _mov_eq_r0(0x06)  # 6
VANILLA_LV4 = _mov_eq_r0(0x00)  # 0 (unchanged)
PATCHED_LV1 = _mov_eq_r0(0x0E)  # 14
PATCHED_LV2 = _mov_eq_r0(0x08)  # 8
PATCHED_LV3 = _mov_eq_r0(0x02)  # 2

# cmp r0,#1 at function entry — refuse unknown binaries
VANILLA_HEAD = bytes.fromhex("010050e3")

_SITES = (
    (OFF_LV1, VANILLA_LV1, PATCHED_LV1, "lv1"),
    (OFF_LV2, VANILLA_LV2, PATCHED_LV2, "lv2"),
    (OFF_LV3, VANILLA_LV3, PATCHED_LV3, "lv3"),
)

# TalkWindow delay table (file). Index 5 stays 0 (divide-by-zero if used).
TALK_TABLE_OFF = 0x006E3024
TALK_VANILLA = (40, 70, 90, 110, 220)
TALK_PATCHED = (10, 18, 22, 28, 55)
TALK_VANILLA_BYTES = struct.pack(f"<{len(TALK_VANILLA)}I", *TALK_VANILLA)
TALK_PATCHED_BYTES = struct.pack(f"<{len(TALK_PATCHED)}I", *TALK_PATCHED)
_TALK_NEED = TALK_TABLE_OFF + len(TALK_VANILLA_BYTES)

# After table / +0xd5c / voice-sync, cpy r6, r2 @ tick 0x0013B718.
TALK_HOOK_OFF = 0x0013B718
TALK_HOOK_VANILLA = bytes.fromhex("0260a0e1")  # cpy r6, r2
TALK_TABLE_VA = TALK_TABLE_OFF + 0x100000
_CAP_NEED = ADDR_TALK_CAP_CAVE + TALK_CAP_CAVE_LEN


def _u32(word: int) -> bytes:
    return struct.pack("<I", word & 0xFFFFFFFF)


def _arm_bl(here: int, target: int) -> bytes:
    return _u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def build_talk_cap_cave(cave: int = ADDR_TALK_CAP_CAVE) -> bytes:
    """r2 = min(r2, table[+0xd9c]); never cap with 0; cpy r6, r2; bx lr."""
    pool_off = 0x24
    ldr_pc = 0x04
    pc_lit = pool_off - (ldr_pc + 8)
    if pc_lit < 0 or pc_lit > 0xFFF:
        raise ValueError(f"literal pool too far: {pc_lit:#x}")
    blob = (
        _u32(0xE5940D9C)  # ldr r0, [r4, #0xd9c]
        + _u32(0xE59F1000 | pc_lit)  # ldr r1, [pc, #pool]
        + _u32(0xE7911100)  # ldr r1, [r1, r0, lsl #2]
        + _u32(0xE3510000)  # cmp r1, #0
        + _u32(0x03A01001)  # moveq r1, #1
        + _u32(0xE1520001)  # cmp r2, r1
        + _u32(0xC1A02001)  # movgt r2, r1
        + _u32(0xE1A06002)  # cpy r6, r2
        + _u32(0xE12FFF1E)  # bx lr
        + _u32(TALK_TABLE_VA)
    )
    if len(blob) != TALK_CAP_CAVE_LEN:
        raise ValueError(f"talk cap cave {len(blob):#x} != {TALK_CAP_CAVE_LEN:#x}")
    if cave + len(blob) > TEXT_PAGE_END:
        raise ValueError("talk cap cave leaves .text RX")
    return blob


TALK_CAP_CAVE_BYTES = build_talk_cap_cave()
TALK_HOOK_PATCHED = _arm_bl(TALK_HOOK_OFF, ADDR_TALK_CAP_CAVE)


def _has_talk(data: bytes) -> bool:
    return len(data) >= _TALK_NEED


def _has_cap_region(data: bytes) -> bool:
    return len(data) >= _CAP_NEED


def is_options_patched(data: bytes) -> bool:
    return all(data[off : off + 4] == patched for off, _v, patched, _n in _SITES)


def is_options_vanilla(data: bytes) -> bool:
    return all(data[off : off + 4] == vanilla for off, vanilla, _p, _n in _SITES)


def is_talk_patched(data: bytes) -> bool:
    if not _has_talk(data):
        return False
    return data[TALK_TABLE_OFF : TALK_TABLE_OFF + len(TALK_PATCHED_BYTES)] == TALK_PATCHED_BYTES


def is_talk_vanilla(data: bytes) -> bool:
    if not _has_talk(data):
        return False
    return data[TALK_TABLE_OFF : TALK_TABLE_OFF + len(TALK_VANILLA_BYTES)] == TALK_VANILLA_BYTES


def is_patched(data: bytes) -> bool:
    """Options preview table is patched (unit-test / small-blob compatible)."""
    return is_options_patched(data)


def is_vanilla(data: bytes) -> bool:
    return is_options_vanilla(data)


def is_talk_cap_patched(data: bytes) -> bool:
    if not _has_cap_region(data):
        return False
    return (
        data[TALK_HOOK_OFF : TALK_HOOK_OFF + 4] == TALK_HOOK_PATCHED
        and data[ADDR_TALK_CAP_CAVE : ADDR_TALK_CAP_CAVE + TALK_CAP_CAVE_LEN]
        == TALK_CAP_CAVE_BYTES
    )


def is_talk_cap_vanilla(data: bytes) -> bool:
    if len(data) < TALK_HOOK_OFF + 4:
        return False
    if data[TALK_HOOK_OFF : TALK_HOOK_OFF + 4] != TALK_HOOK_VANILLA:
        return False
    if not _has_cap_region(data):
        return True
    cave = data[ADDR_TALK_CAP_CAVE : ADDR_TALK_CAP_CAVE + TALK_CAP_CAVE_LEN]
    return cave == b"\x00" * TALK_CAP_CAVE_LEN or cave == TALK_CAP_CAVE_BYTES


def is_fully_patched(data: bytes) -> bool:
    if not is_options_patched(data):
        return False
    if _has_talk(data) and not is_talk_patched(data):
        return False
    if _has_cap_region(data) and not is_talk_cap_patched(data):
        return False
    return True


def _apply_options(data: bytearray) -> bool:
    if is_options_patched(data):
        print(f"[msg-speed] options already patched @{ADDR_FN:#x} (14/8/2/0)")
        return False
    if data[ADDR_FN : ADDR_FN + 4] != VANILLA_HEAD:
        raise ValueError(
            f"unexpected FUN_005d1e18 head @{ADDR_FN:#x}: "
            f"{data[ADDR_FN:ADDR_FN+4].hex()} (want {VANILLA_HEAD.hex()})"
        )
    if not is_options_vanilla(data):
        got = " ".join(
            f"{name}={data[off:off+4].hex()}" for off, _v, _p, name in _SITES
        )
        raise ValueError(f"unexpected message-speed delays: {got}")
    for off, _vanilla, patched, name in _SITES:
        data[off : off + 4] = patched
        print(f"[msg-speed] {name} @{off:#x} -> {patched[0]} frames")
    return True


def _apply_talk(data: bytearray) -> bool:
    if not _has_talk(data):
        return False
    if is_talk_patched(data):
        print(
            f"[msg-speed] talk already patched @{TALK_TABLE_OFF:#x} "
            f"({'/'.join(str(v) for v in TALK_PATCHED)})"
        )
        return False
    if not is_talk_vanilla(data):
        got = struct.unpack_from(f"<{len(TALK_VANILLA)}I", data, TALK_TABLE_OFF)
        raise ValueError(f"unexpected talk delay table: {got}")
    data[TALK_TABLE_OFF : TALK_TABLE_OFF + len(TALK_PATCHED_BYTES)] = TALK_PATCHED_BYTES
    print(
        f"[msg-speed] talk @{TALK_TABLE_OFF:#x} "
        f"{'/'.join(str(v) for v in TALK_VANILLA)} -> "
        f"{'/'.join(str(v) for v in TALK_PATCHED)}"
    )
    return True


def _apply_talk_cap(data: bytearray) -> bool:
    if not _has_cap_region(data):
        return False
    if is_talk_cap_patched(data):
        print(f"[msg-speed] talk cap already patched @{TALK_HOOK_OFF:#x}")
        return False
    hook = bytes(data[TALK_HOOK_OFF : TALK_HOOK_OFF + 4])
    if hook != TALK_HOOK_VANILLA:
        if hook == b"\x00\x00\x00\x00":
            return False
        raise ValueError(
            f"unexpected talk-cap hook @{TALK_HOOK_OFF:#x}: {hook.hex()} "
            f"(want {TALK_HOOK_VANILLA.hex()})"
        )
    data[TALK_HOOK_OFF : TALK_HOOK_OFF + 4] = TALK_HOOK_PATCHED
    data[ADDR_TALK_CAP_CAVE : ADDR_TALK_CAP_CAVE + TALK_CAP_CAVE_LEN] = TALK_CAP_CAVE_BYTES
    print(
        f"[msg-speed] talk cap BL @{TALK_HOOK_OFF:#x} -> cave "
        f"{ADDR_TALK_CAP_CAVE:#x} (min vs table)"
    )
    return True


def apply_patch(data: bytearray) -> bool:
    """Rewrite Options + TalkWindow delays + voice/script cap. Returns True if bytes changed."""
    changed = _apply_options(data)
    changed = _apply_talk(data) or changed
    changed = _apply_talk_cap(data) or changed
    return changed


def _revert_options(data: bytearray) -> bool:
    if is_options_vanilla(data):
        print(f"[msg-speed] options already vanilla @{ADDR_FN:#x} (18/12/6/0)")
        return False
    if not is_options_patched(data):
        raise ValueError("cannot revert: options delay table is neither vanilla nor patched")
    for off, vanilla, _patched, name in _SITES:
        data[off : off + 4] = vanilla
        print(f"[msg-speed] {name} @{off:#x} restored {vanilla[0]} frames")
    return True


def _revert_talk(data: bytearray) -> bool:
    if not _has_talk(data):
        return False
    if is_talk_vanilla(data):
        print(
            f"[msg-speed] talk already vanilla @{TALK_TABLE_OFF:#x} "
            f"({'/'.join(str(v) for v in TALK_VANILLA)})"
        )
        return False
    if not is_talk_patched(data):
        raise ValueError("cannot revert: talk delay table is neither vanilla nor patched")
    data[TALK_TABLE_OFF : TALK_TABLE_OFF + len(TALK_VANILLA_BYTES)] = TALK_VANILLA_BYTES
    print(
        f"[msg-speed] talk @{TALK_TABLE_OFF:#x} restored "
        f"{'/'.join(str(v) for v in TALK_VANILLA)}"
    )
    return True


def _revert_talk_cap(data: bytearray) -> bool:
    if not _has_cap_region(data):
        return False
    if is_talk_cap_patched(data):
        data[TALK_HOOK_OFF : TALK_HOOK_OFF + 4] = TALK_HOOK_VANILLA
        data[ADDR_TALK_CAP_CAVE : ADDR_TALK_CAP_CAVE + TALK_CAP_CAVE_LEN] = (
            b"\x00" * TALK_CAP_CAVE_LEN
        )
        print(f"[msg-speed] talk cap @{TALK_HOOK_OFF:#x} restored cpy r6, r2")
        return True
    hook = bytes(data[TALK_HOOK_OFF : TALK_HOOK_OFF + 4])
    if hook in (TALK_HOOK_VANILLA, b"\x00\x00\x00\x00"):
        if hook == TALK_HOOK_VANILLA:
            print(f"[msg-speed] talk cap already vanilla @{TALK_HOOK_OFF:#x}")
        return False
    raise ValueError("cannot revert: talk-cap hook is neither vanilla nor patched")


def revert_talk_cap(data: bytearray) -> bool:
    """Leave Options + TalkWindow tables; restore vanilla voice-sync (A/B B)."""
    return _revert_talk_cap(data)


def revert_patch(data: bytearray) -> bool:
    changed = _revert_options(data)
    changed = _revert_talk(data) or changed
    changed = _revert_talk_cap(data) or changed
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(
            f"FUN_005d1e18 @{ADDR_FN:#x}: "
            f"vanilla 18/12/6/0 -> patched 14/8/2/0"
        )
        print(
            f"TalkWindow @{TALK_TABLE_OFF:#x}: "
            f"vanilla {'/'.join(str(v) for v in TALK_VANILLA)} -> "
            f"patched {'/'.join(str(v) for v in TALK_PATCHED)}"
        )
        print(
            f"Talk cap BL @{TALK_HOOK_OFF:#x} -> cave {ADDR_TALK_CAP_CAVE:#x} "
            f"({TALK_CAP_CAVE_LEN:#x} bytes, min vs table)"
        )
        return 0

    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar (or import apply_patch)")

    from nlpp_paths import AZAHAR_MOD_CODE, AZAHAR_MOD_ROOT

    dest = AZAHAR_MOD_CODE
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")

    bak = dest.with_name(dest.name + ".bak_pre_msg_speed")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    if args.revert:
        revert_patch(data)
    else:
        apply_patch(data)
    dest.write_bytes(data)
    shutil.copy2(dest, AZAHAR_MOD_ROOT / "code.bin")
    print("Fully quit Azahar so LayeredFS reloads exefs/code.bin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
