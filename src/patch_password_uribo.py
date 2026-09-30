#!/usr/bin/env python3
"""Grant ウリボー傘 from shared codes UriboKasaM/R/N (pack 0xb000 slots 33–35).

Password bits are set by ``FUN_00257600``. Presents are applied later by
``FUN_0038dc70``, which reads ``s32 item_id[53]`` at file ``0x006B6F00``
(VA ``0x007B6F00``) and inventory-key bases:

  slot < 0x21  →  present flag ``0x04000614 + slot``
  slot < 0x34  →  内部 flag     ``0x04000659 + slot``
  else         →  strap pack    ``0x0400066C + slot``

Vanilla table[33..40] is sentinel ``-500``. That falls through to a junk
item id and still stamps 内部 flags (arcade / medal / all-mode for 33–35).
ウリボー傘 itself is present ids **465/466/467** (pack ``0x0404``; the same
ids the VISA ``-200`` branch already loads for heroine 0/1/2).

Patch:

1. table[33..35] = 465, 466, 467 so ``FUN_00390058`` adds the umbrellas.
2. ``cmp r4, #0x21`` @ ``0x0038DDA0`` → ``#0x24`` so 33–35 use present
   flags ``0x04000635..637`` instead of 内部. Slots 36–40 stay 内部.

``.rodata`` table write is fine on hardware (not a cave). Ships in
``deploy_name_input_en.py`` / ``release/name_input_code.bin``.

  python src/patch_password_uribo.py --dry-run
  python src/patch_password_uribo.py --deploy-azahar
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

# FUN_0038dc70 item_id table (file offset; Ghidra image base 0).
ADDR_TABLE = 0x006B6F00
N_SLOTS = 53
URIBO_SLOTS = (33, 34, 35)
URIBO_ITEMS = (465, 466, 467)  # ウリボー傘 Manaka / Rinko / Nene

SENTINEL_INTERNAL = -500  # vanilla table[33..40]
GLOVE_MANAKA = 355  # table[0] fingerprint
SENTINEL_VISA = -200  # table[24..26]

# cmp r4, #0x21 / bge 内部-base  (present vs 内部 inventory split)
ADDR_SLOT_THRESH = 0x0038DDA0
VANILLA_CMP = bytes.fromhex("210054e3")  # cmp r4, #0x21
PATCHED_CMP = bytes.fromhex("240054e3")  # cmp r4, #0x24
VANILLA_BGE = bytes.fromhex("4a0000aa")  # bge 0x0038ded4


def _table_off(slot: int) -> int:
    if not 0 <= slot < N_SLOTS:
        raise ValueError(f"password grant slot {slot} out of range")
    return ADDR_TABLE + slot * 4


def _s32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def _put_s32(data: bytearray, off: int, value: int) -> None:
    struct.pack_into("<i", data, off, value)


def is_vanilla(data: bytes) -> bool:
    if len(data) < ADDR_TABLE + N_SLOTS * 4:
        return False
    if data[ADDR_SLOT_THRESH : ADDR_SLOT_THRESH + 4] != VANILLA_CMP:
        return False
    if data[ADDR_SLOT_THRESH + 4 : ADDR_SLOT_THRESH + 8] != VANILLA_BGE:
        return False
    if _s32(data, _table_off(0)) != GLOVE_MANAKA:
        return False
    if _s32(data, _table_off(24)) != SENTINEL_VISA:
        return False
    return all(_s32(data, _table_off(s)) == SENTINEL_INTERNAL for s in URIBO_SLOTS)


def is_patched(data: bytes) -> bool:
    if len(data) < ADDR_TABLE + N_SLOTS * 4:
        return False
    if data[ADDR_SLOT_THRESH : ADDR_SLOT_THRESH + 4] != PATCHED_CMP:
        return False
    if data[ADDR_SLOT_THRESH + 4 : ADDR_SLOT_THRESH + 8] != VANILLA_BGE:
        return False
    return all(
        _s32(data, _table_off(s)) == item for s, item in zip(URIBO_SLOTS, URIBO_ITEMS)
    )


def apply_patch(data: bytearray) -> bool:
    """Remap slots 33–35 to ウリボー傘 presents. Returns True if bytes changed."""
    if is_patched(data):
        print(
            f"[password-uribo] already patched "
            f"table@${ADDR_TABLE:08X} slots 33-35={list(URIBO_ITEMS)} "
            f"cmp@${ADDR_SLOT_THRESH:08X} #0x24"
        )
        return False
    if not is_vanilla(data):
        got_cmp = data[ADDR_SLOT_THRESH : ADDR_SLOT_THRESH + 8].hex()
        got_items = [
            _s32(data, _table_off(s)) if len(data) >= _table_off(s) + 4 else None
            for s in URIBO_SLOTS
        ]
        raise ValueError(
            f"unexpected password grant table @{ADDR_TABLE:#x} slots 33-35={got_items} "
            f"cmp @{ADDR_SLOT_THRESH:#x}={got_cmp}"
        )
    for slot, item in zip(URIBO_SLOTS, URIBO_ITEMS):
        _put_s32(data, _table_off(slot), item)
    data[ADDR_SLOT_THRESH : ADDR_SLOT_THRESH + 4] = PATCHED_CMP
    print(
        f"[password-uribo] table@${ADDR_TABLE:08X} slots 33-35 "
        f"{SENTINEL_INTERNAL} -> {list(URIBO_ITEMS)}; "
        f"cmp r4,#0x21 -> #0x24 (present flags, not internal unlocks)"
    )
    return True


def revert_patch(data: bytearray) -> bool:
    if is_vanilla(data):
        print(f"[password-uribo] already vanilla @{ADDR_TABLE:#x}")
        return False
    if not is_patched(data):
        raise ValueError("cannot revert: password-uribo site is neither vanilla nor patched")
    for slot in URIBO_SLOTS:
        _put_s32(data, _table_off(slot), SENTINEL_INTERNAL)
    data[ADDR_SLOT_THRESH : ADDR_SLOT_THRESH + 4] = VANILLA_CMP
    print(f"[password-uribo] restored vanilla table 33-35 and cmp #0x21")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(
            f"FUN_0038dc70 table @{ADDR_TABLE:#x}: slots 33-35 "
            f"{SENTINEL_INTERNAL} -> {list(URIBO_ITEMS)}; "
            f"cmp @{ADDR_SLOT_THRESH:#x} #0x21 -> #0x24"
        )
        return 0

    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar (or import apply_patch)")

    from nlpp_paths import AZAHAR_MOD_CODE, AZAHAR_MOD_ROOT

    dest = AZAHAR_MOD_CODE
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")

    bak = dest.with_name(dest.name + ".bak_pre_password_uribo")
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
