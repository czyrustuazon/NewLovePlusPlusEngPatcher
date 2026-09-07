#!/usr/bin/env python3
"""Deploy the verified Profile name-input EN stack.

Verified stack (2026-08-31):

  1. patch_input_pane_registry_nullguard
  2. patch_input_candidate_nullguard
  3. patch_input_candmode_fillflag_reset   # NOT candmode_reset (+0x24)
  4. patch_input_romaji                    # Hepburn labels + romaji insert
  5. patch_input_kana_direct_insert        # skip kanji list; tap inserts

  # Azahar LayeredFS (default)
  python tools/deploy_name_input_en.py
  python tools/deploy_name_input_en.py --dry-run

  # Gold CIA artifact (bake / drop-bat --inject-code)
  python tools/deploy_name_input_en.py --src vanilla/code.bin --out release/name_input_code.bin

Rollback (Azahar): python tools/restore_name_input_baseline.py
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
from patch_input_kana_direct_insert import (  # noqa: E402
    SITE as KANA_SITE,
    PATCHED as KANA_PATCHED,
    apply_patch as apply_kana_direct,
    restore_bind_sites,
)
from patch_input_pane_registry_nullguard import (  # noqa: E402
    CAVE as PANE_CAVE,
    SITE as PANE_SITE,
    apply_patch as apply_pane_nullguard,
    b_ins as pane_b_ins,
    build_cave as build_pane_cave,
)
from patch_input_romaji import (  # noqa: E402
    is_romaji_patched,
    patch_input_romaji,
)

from nlpp_paths import AZAHAR_MOD_CODE, AZAHAR_MOD_ROOT, NAME_INPUT_CODE  # noqa: E402

MOD = AZAHAR_MOD_ROOT
DEST = AZAHAR_MOD_CODE


def _u32_at(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def pane_already(data: bytes) -> bool:
    return _u32_at(data, PANE_SITE) == struct.unpack("<I", pane_b_ins(PANE_SITE, PANE_CAVE))[0]


def cand_already(data: bytes) -> bool:
    return data[CAND_SITE1 : CAND_SITE1 + 4] != bytes.fromhex("1010b0e5")


def fillflag_already(data: bytes) -> bool:
    return _u32_at(data, FILL_SITE) == struct.unpack("<I", fill_b_ins(FILL_SITE, FILL_CAVE))[0]


def kana_already(data: bytes) -> bool:
    return data[KANA_SITE : KANA_SITE + 4] == KANA_PATCHED


def apply_name_input_stack(data: bytearray) -> int:
    """Apply the full verified stack in-place. Returns number of steps run."""
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
        # Force refresh so insert buffer matches display (romaji, not kana).
        patch_input_romaji(data, force=True)
        print("[input-romaji] refreshed (insert=display)")
        steps += 1
    else:
        if not patch_input_romaji(data, force=False):
            raise SystemExit("romaji patch failed")
        print("[input-romaji] applied")
        steps += 1

    restore_bind_sites(data)
    if kana_already(data):
        print("[skip] kana_direct_insert already applied")
    else:
        apply_kana_direct(data)
        steps += 1

    return steps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--src",
        type=Path,
        default=None,
        help="vanilla (or base) decompressed code.bin to patch",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"write patched code.bin here (default Azahar LayeredFS, or {NAME_INPUT_CODE.name} with --src)",
    )
    args = ap.parse_args(argv)

    if args.dry_run:
        build_pane_cave()
        build_site_cave(CAND_CAVE1, 0x001FBC0C, 0x001FBC30, 6)
        build_site_cave(CAND_CAVE2, 0x001FBD28, 0x001FBD4C, 11)
        build_fillflag_cave()
        print("dry-run OK (caves assemble)")
        return 0

    if args.src is not None:
        src = args.src.resolve()
        if not src.is_file():
            raise SystemExit(f"missing --src {src}")
        out = (args.out or NAME_INPUT_CODE).resolve()
        data = bytearray(src.read_bytes())
        steps = apply_name_input_stack(data)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        print(f"wrote {out} ({steps} new step(s))")
        return 0

    dest = (args.out or DEST).resolve()
    if not dest.is_file() and args.out is None:
        raise SystemExit(f"missing {DEST} — seed LayeredFS exefs/code.bin first")
    if not dest.is_file():
        raise SystemExit(f"missing --out base file {dest}")

    bak = dest.with_name(dest.name + ".bak_pre_name_input_en")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    steps = apply_name_input_stack(data)
    dest.write_bytes(data)
    if dest.resolve() == DEST.resolve():
        shutil.copy2(dest, MOD / "code.bin")
    print(f"wrote {dest} ({steps} new step(s))")
    print("Rollback: python tools/restore_name_input_baseline.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
