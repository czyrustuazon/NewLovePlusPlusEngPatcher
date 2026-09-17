#!/usr/bin/env python3
"""Faster Message Speed typewriter (Display Settings slider).

Vanilla ``FUN_005d1e18`` @ file ``0x005D1E18`` maps slider level → frames/glyph:

    1 → 18    2 → 12    3 → 6    4 → 0 (instant)

This patch subtracts 4 frames from each positive delay (floor 0):

    1 → 14    2 → 8    3 → 2    4 → 0

Ghidra image base 0; runtime VA = file + ``0x100000``. See technical.md §21.

  python src/patch_message_speed.py --dry-run
  python src/patch_message_speed.py --deploy-azahar
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

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


def is_patched(data: bytes) -> bool:
    return all(data[off : off + 4] == patched for off, _v, patched, _n in _SITES)


def is_vanilla(data: bytes) -> bool:
    return all(data[off : off + 4] == vanilla for off, vanilla, _p, _n in _SITES)


def apply_patch(data: bytearray) -> bool:
    """Rewrite delay immediates in-place. Returns True if bytes changed."""
    if is_patched(data):
        print(f"[msg-speed] already patched @{ADDR_FN:#x} (14/8/2/0)")
        return False
    if data[ADDR_FN : ADDR_FN + 4] != VANILLA_HEAD:
        raise ValueError(
            f"unexpected FUN_005d1e18 head @{ADDR_FN:#x}: "
            f"{data[ADDR_FN:ADDR_FN+4].hex()} (want {VANILLA_HEAD.hex()})"
        )
    if not is_vanilla(data):
        got = " ".join(
            f"{name}={data[off:off+4].hex()}" for off, _v, _p, name in _SITES
        )
        raise ValueError(f"unexpected message-speed delays: {got}")
    for off, _vanilla, patched, name in _SITES:
        data[off : off + 4] = patched
        print(f"[msg-speed] {name} @{off:#x} -> {patched[0]} frames")
    return True


def revert_patch(data: bytearray) -> bool:
    if is_vanilla(data):
        print(f"[msg-speed] already vanilla @{ADDR_FN:#x} (18/12/6/0)")
        return False
    if not is_patched(data):
        raise ValueError("cannot revert: delay table is neither vanilla nor patched")
    for off, vanilla, _patched, name in _SITES:
        data[off : off + 4] = vanilla
        print(f"[msg-speed] {name} @{off:#x} restored {vanilla[0]} frames")
    return True


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
