#!/usr/bin/env python3
"""Skip kanji candidate list: tap gojūon cell inserts kana into the name field.

Vanilla NameInput_OnCellTap (mode +0x30 == 0):
  beq → +0x44 check → FillCandidates (kanji table)

ABC / other modes already fall through into the same memcpy(+0x541 → +0x46)
insert path. This patch NOPs the mode==0 branch so gojūon uses that path too.

Display stays Hepburn (romaji patch); insert buffer is still kana.

Site: 0x001FB070  beq → FillCandidates gate
  vanilla: 0x0A000020
  patched: 0xE320F000  (nop)

Does not touch +0x24 (candmode_reset ban). Does not call RedrawKeyboard /
FillCandidates from SetDisplayMode.

  python src/patch_input_kana_direct_insert.py --deploy-azahar
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

SITE = 0x001FB070
VANILLA = bytes.fromhex("2000000a")  # beq #+0x20 → FillCandidates gate
PATCHED = bytes.fromhex("00f020e3")  # nop


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def is_patched(data: bytes) -> bool:
    return data[SITE : SITE + 4] == PATCHED


def apply_patch(data: bytearray) -> None:
    cur = bytes(data[SITE : SITE + 4])
    if cur == PATCHED:
        print(f"[kana-direct] already patched @{SITE:#x}")
        return
    if cur != VANILLA:
        raise ValueError(
            f"unexpected bytes @{SITE:#x}: {cur.hex()} "
            f"(want vanilla {VANILLA.hex()} or patched {PATCHED.hex()})"
        )
    data[SITE : SITE + 4] = PATCHED
    print(f"[kana-direct] NOP @{SITE:#x} - gojuon tap uses ABC insert path (no FillCandidates)")


def revert_patch(data: bytearray) -> None:
    cur = bytes(data[SITE : SITE + 4])
    if cur == VANILLA:
        print(f"[kana-direct] already vanilla @{SITE:#x}")
        return
    if cur != PATCHED:
        raise ValueError(f"unexpected bytes @{SITE:#x}: {cur.hex()}")
    data[SITE : SITE + 4] = VANILLA
    print(f"[kana-direct] restored beq @{SITE:#x}")


# Undo candidate-chrome BindGridAxisPanes wrappers if present (safe with this UX).
SITE_BIND_KBD = 0x001FAE8C
SITE_BIND_CAND = 0x001FB6F4
VANILLA_BL_KBD = bytes.fromhex("310200eb")  # bl NameInput_BindGridAxisPanes
VANILLA_BL_CAND = bytes.fromhex("170000eb")


def restore_bind_sites(data: bytearray) -> None:
    for site, vanilla, tag in (
        (SITE_BIND_KBD, VANILLA_BL_KBD, "kbd"),
        (SITE_BIND_CAND, VANILLA_BL_CAND, "cand"),
    ):
        cur = bytes(data[site : site + 4])
        if cur == vanilla:
            continue
        data[site : site + 4] = vanilla
        print(
            f"[kana-direct] restored BindGrid BL ({tag}) @{site:#x} "
            f"({cur.hex()} -> {vanilla.hex()})"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(f"site {SITE:#x} vanilla={VANILLA.hex()} patched={PATCHED.hex()}")
        return 0

    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")

    from nlpp_paths import AZAHAR_MOD_CODE, AZAHAR_MOD_ROOT

    dest = AZAHAR_MOD_CODE
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")

    bak = dest.with_name(dest.name + ".bak_pre_kana_direct")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    restore_bind_sites(data)
    if args.revert:
        revert_patch(data)
    else:
        apply_patch(data)
    dest.write_bytes(data)
    shutil.copy2(dest, AZAHAR_MOD_ROOT / "code.bin")
    print("Fully quit Azahar. Tap kana -> should enter name field directly (no kanji list).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
