#!/usr/bin/env python3
"""Deploy the verified Profile name-input EN stack to Azahar LayeredFS.

Applies, in order (technical.md §17):

  1. patch_input_pane_registry_nullguard
  2. patch_input_candidate_nullguard
  3. patch_input_candmode_fillflag_reset   # NOT candmode_reset (+0x24)
  4. patch_input_romaji                    # display Hepburn; insert stays kana

Idempotent: skips a step if that site is already patched.
Does not touch img.bin (mode-tab textures: tools/deploy_input_keyboard_en.py).

  python tools/deploy_name_input_en.py
  python tools/deploy_name_input_en.py --dry-run

Fully quit Azahar after deploy. Ban: patch_input_candmode_reset.py (deleted).
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patch_input_candidate_nullguard import (  # noqa: E402
    CAVE1 as CAND_CAVE1,
    CAVE2 as CAND_CAVE2,
    SITE1 as CAND_SITE1,
    SITE2 as CAND_SITE2,
    apply_patch as apply_cand_nullguard,
    build_site_cave,
)
from patch_input_candmode_fillflag_reset import (  # noqa: E402
    CAVE as FILL_CAVE,
    SITE as FILL_SITE,
    apply_patch as apply_fillflag,
    b_ins as fill_b_ins,
    build_cave as build_fillflag_cave,
)
from patch_input_pane_registry_nullguard import (  # noqa: E402
    CAVE as PANE_CAVE,
    SITE as PANE_SITE,
    apply_patch as apply_pane_nullguard,
    b_ins as pane_b_ins,
    build_cave as build_pane_cave,
)
from patch_input_romaji import (  # noqa: E402
    ADDR_DRAW_CELL,
    is_romaji_patched,
    patch_input_romaji,
)

MOD = Path.home() / "AppData/Roaming/Azahar/load/mods/00040000000F4E00"
DEST = MOD / "exefs" / "code.bin"


def _u32_at(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def pane_already(data: bytes) -> bool:
    return _u32_at(data, PANE_SITE) == struct.unpack("<I", pane_b_ins(PANE_SITE, PANE_CAVE))[0]


def cand_already(data: bytes) -> bool:
    # Either site branched off vanilla ldr
    return data[CAND_SITE1 : CAND_SITE1 + 4] != bytes.fromhex("1010b0e5")


def fillflag_already(data: bytes) -> bool:
    return _u32_at(data, FILL_SITE) == struct.unpack("<I", fill_b_ins(FILL_SITE, FILL_CAVE))[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        build_pane_cave()
        build_site_cave(CAND_CAVE1, 0x001FBC0C, 0x001FBC30, 6)
        build_site_cave(CAND_CAVE2, 0x001FBD28, 0x001FBD4C, 11)
        build_fillflag_cave()
        print("dry-run OK (caves assemble)")
        return 0

    if not DEST.is_file():
        raise SystemExit(f"missing {DEST} — seed LayeredFS exefs/code.bin first")

    bak = DEST.with_name(DEST.name + ".bak_pre_name_input_en")
    if not bak.exists():
        shutil.copy2(DEST, bak)
        print("backup", bak)

    data = bytearray(DEST.read_bytes())
    steps = 0

    if pane_already(data):
        print("[skip] pane_registry_nullguard already applied")
    else:
        apply_pane_nullguard(data)
        steps += 1

    if cand_already(data):
        print("[skip] candidate_nullguard already applied")
    else:
        apply_cand_nullguard(data)
        steps += 1

    if fillflag_already(data):
        print("[skip] fillflag_reset already applied")
    else:
        apply_fillflag(data)
        steps += 1

    if is_romaji_patched(data):
        print("[skip] romaji DrawCell already applied")
    else:
        if not patch_input_romaji(data, force=False):
            raise SystemExit("romaji patch failed")
        print("[input-romaji] applied")
        steps += 1

    DEST.write_bytes(data)
    shutil.copy2(DEST, MOD / "code.bin")
    print(f"wrote {DEST} ({steps} new step(s))")
    print("Fully quit Azahar to reload exefs/code.bin.")
    print("Rollback: copy bak_pre_name_input_en -> exefs/code.bin (+ mods/.../code.bin)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
