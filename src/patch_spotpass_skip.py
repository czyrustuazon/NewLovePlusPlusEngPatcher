#!/usr/bin/env python3
"""Skip the boot “No SpotPass data found.” nag when BOSS NsData is missing.

NetDlTaskManager tick ``FUN_006096d8`` @ ``0x006096d8``:

  GetNsDataNewFlag == 0  →  store ``+0x46 = 4`` (error state)
  UI treats state 4 as the TRB line いつの間に通信の受信データがありません。

Patch: ``moveq r0, #4`` → ``moveq r0, #0`` so a missing/dead CDN does not
enter the error state. State stays 0 (idle retry). Does **not** apply Towano
Watcher / city tables — that is ``patch_spotpass_embed.py`` (technical.md §16.8).
Does **not** gate Enoshima (already on-cart).

Ghidra image base 0; runtime VA = file + ``0x100000``. See technical.md §16.7.

  python src/patch_spotpass_skip.py --dry-run
  python src/patch_spotpass_skip.py --deploy-azahar
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# cmp r0,#0 / moveq r0,#4 / strbeq r0,[r4,#0x46] / beq epilogue
ADDR_CMP = 0x0060973C
ADDR_MOVEQ = 0x00609740
VANILLA_CMP = bytes.fromhex("000050e3")
VANILLA_MOVEQ = bytes.fromhex("0400a003")  # moveq r0, #4
PATCHED_MOVEQ = bytes.fromhex("0000a003")  # moveq r0, #0
VANILLA_STRB = bytes.fromhex("4600c405")  # strbeq r0, [r4, #0x46]


def is_vanilla(data: bytes) -> bool:
    if len(data) < ADDR_MOVEQ + 8:
        return False
    return (
        data[ADDR_CMP : ADDR_CMP + 4] == VANILLA_CMP
        and data[ADDR_MOVEQ : ADDR_MOVEQ + 4] == VANILLA_MOVEQ
        and data[ADDR_MOVEQ + 4 : ADDR_MOVEQ + 8] == VANILLA_STRB
    )


def is_patched(data: bytes) -> bool:
    if len(data) < ADDR_MOVEQ + 8:
        return False
    return (
        data[ADDR_CMP : ADDR_CMP + 4] == VANILLA_CMP
        and data[ADDR_MOVEQ : ADDR_MOVEQ + 4] == PATCHED_MOVEQ
        and data[ADDR_MOVEQ + 4 : ADDR_MOVEQ + 8] == VANILLA_STRB
    )


def apply_patch(data: bytearray) -> bool:
    """Quiet missing NsData. Returns True if bytes changed."""
    if is_patched(data):
        print(f"[spotpass-skip] already patched @{ADDR_MOVEQ:#x} (moveq r0,#0)")
        return False
    if not is_vanilla(data):
        got = data[ADDR_CMP : ADDR_MOVEQ + 8].hex()
        raise ValueError(
            f"unexpected SpotPass no-data store @{ADDR_CMP:#x}: {got} "
            f"(want cmp + moveq #4 + strbeq)"
        )
    data[ADDR_MOVEQ : ADDR_MOVEQ + 4] = PATCHED_MOVEQ
    print(
        f"[spotpass-skip] @{ADDR_MOVEQ:#x} moveq r0,#4 -> #0 "
        "(no +0x46=4 error state without BOSS NsData)"
    )
    return True


def revert_patch(data: bytearray) -> bool:
    if is_vanilla(data):
        print(f"[spotpass-skip] already vanilla @{ADDR_MOVEQ:#x}")
        return False
    if not is_patched(data):
        raise ValueError("cannot revert: SpotPass skip site is neither vanilla nor patched")
    data[ADDR_MOVEQ : ADDR_MOVEQ + 4] = VANILLA_MOVEQ
    print(f"[spotpass-skip] @{ADDR_MOVEQ:#x} restored moveq r0,#4")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(
            f"FUN_006096d8 @{ADDR_CMP:#x}: "
            f"moveq r0,#4 -> #0 (skip No SpotPass data found)"
        )
        return 0

    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar (or import apply_patch)")

    from nlpp_paths import AZAHAR_MOD_CODE, AZAHAR_MOD_ROOT

    dest = AZAHAR_MOD_CODE
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")

    bak = dest.with_name(dest.name + ".bak_pre_spotpass_skip")
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
