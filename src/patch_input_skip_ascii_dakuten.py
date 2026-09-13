#!/usr/bin/env python3
"""Skip hiragana/katakana dakuten-sokuon combining on Profile name insert.

Vanilla ProfileField_TickPoller (0x002567a8) on keyboard mode 1/2 compares the
pending tap against TRB ゛/゜/っ and may rewrite the last mora. Hepburn
gojūon writes ASCII (KA/KE/KU); that path can geminate (KAKEKU → KAKKE) or
drop taps.

This is the same 4-byte site as vanilla `bne strcat` when mode is not 1/2.
Patched: unconditional `b strcat` so hira/kata also FUN_002573ac-only, matching
ABC. GA/GE/PA are their own Hepburn keys; ゛ combining is unused.

In-place on purpose — a far cave at shared pad +0xE0 sat against the romaji
DrawCell blob and is a suspect for the empty gojūon checkerboard.

Does NOT touch +0x24.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from patch_input_cave_map import ADDR_SHARED_PAD as ADDR_CAVE

SITE = 0x002568A4
STRCAT = 0x00256924
EXPECT_SITE = bytes.fromhex("1e00001a")  # bne 0x256924
PATCHED_SITE = bytes.fromhex("1e0000ea")  # b   0x256924
SITE_CONVERT = 0x00256914
EXPECT_CONVERT = bytes.fromhex("0a00000a")  # beq 0x256944
PATCHED_CONVERT = bytes.fromhex("00f020e3")  # nop

# Old far-cave slot (pad+0xE0). Must stay zero so it cannot run as code.
OLD_CAVE = ADDR_CAVE + 0xE0
OLD_CAVE_LEN = 0x20


def is_patched(data: bytes) -> bool:
    return bytes(data[SITE : SITE + 4]) == PATCHED_SITE


def apply_patch(data: bytearray) -> None:
    site = bytes(data[SITE : SITE + 4])
    if site == PATCHED_SITE:
        print(f"[skip-ascii-dakuten] already patched @{SITE:#x} (b strcat)")
        return
    old_cave_branch = bytes.fromhex("0de410ea")  # b 0x68F8E0 from SITE
    if site not in (EXPECT_SITE, old_cave_branch):
        raise ValueError(
            f"unexpected bytes at site {SITE:#x}: {site.hex()} "
            f"(expected {EXPECT_SITE.hex()}, cave hook, or {PATCHED_SITE.hex()})"
        )
    data[SITE : SITE + 4] = PATCHED_SITE
    conv = bytes(data[SITE_CONVERT : SITE_CONVERT + 4])
    if conv in (EXPECT_CONVERT, PATCHED_CONVERT):
        data[SITE_CONVERT : SITE_CONVERT + 4] = PATCHED_CONVERT
    data[OLD_CAVE : OLD_CAVE + OLD_CAVE_LEN] = b"\x00" * OLD_CAVE_LEN
    print(f"[skip-ascii-dakuten] @{SITE:#x} bne strcat -> b strcat (no cave)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(f"site {SITE:#x} vanilla={EXPECT_SITE.hex()} patched={PATCHED_SITE.hex()}")
        return 0
    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")

    dest = Path.home() / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")
    bak = dest.with_name(dest.name + ".bak_pre_skip_ascii_dakuten")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    apply_patch(data)
    dest.write_bytes(data)
    shutil.copy2(dest, dest.parent.parent / "code.bin")
    print("Fully quit Azahar to reload exefs/code.bin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
