#!/usr/bin/env python3
"""Open text entry on the gojūon board (Lyt_Prf_Win_ML), not handwriting.

Every name / text entry screen embeds one shared input kit (create
``0x255ba4`` registers Win_Write, Win_ML, Btn_Change, Btn_ML). Kit byte
``+1`` is the input mode: **0** = Win_Write (CLEAR pad + pencil), **1** =
Win_ML (五十音 grid). Each operator's create sets it to 0
(IntroductionInputUtil: ``strb r6,[r4,#0x5d]`` @ ``0x133b5c``).

Kit open ``0x255f38`` opens Write or ML from that byte. Every caller then
runs kit sync ``0x2571d4`` (ML ``+0x30``, Btn_Change icon via ``0x22bf00``,
Btn_ML ``+0x34``) and picks the Write tick ``0x25601c`` or ML tick
``0x2567a8`` from the same byte. So we store mode 1 at the top of kit open
and the rest of the UI follows. In place, no cave.

Covers first-boot "Register Last name" (IntroductionInputUtilUIOperator),
Profile, DateEditName, InputUtil and the other kit users. Btn_Change can
still switch to handwriting.

Ships in ``deploy_name_input_en.py``.
"""
from __future__ import annotations

import argparse

SITE = 0x00255F40
# mov r6,#0 / ldrb r0,[r0,#1] / ldr r5,=mgr / ldrb r1,[r4] / cmp r0,#0 / beq Write
VANILLA = bytes.fromhex(
    "0060a0e3" "0100d0e5" "c8509fe5" "0010d4e5" "000050e3" "1700000a"
)
PATCHED = bytes.fromhex(
    "0100a0e3"  # mov  r0, #1        ; mode = ML
    "0100c4e5"  # strb r0, [r4, #1]  ; kit+1 = 1 (sync/tick read it)
    "c8509fe5"  # ldr  r5, =mgr
    "0010d4e5"  # ldrb r1, [r4]      ; variant
    "0060a0e3"  # mov  r6, #0
    "00f020e3"  # nop                ; falls into cmp r0,#1 / beq ML
)


def is_patched(data: bytes) -> bool:
    return bytes(data[SITE : SITE + len(PATCHED)]) == PATCHED


def apply_patch(data: bytearray) -> None:
    cur = bytes(data[SITE : SITE + len(PATCHED)])
    if cur == PATCHED:
        print(f"[force-ml] already patched @{SITE:#x}")
        return
    if cur != VANILLA:
        raise ValueError(f"unexpected kit open @{SITE:#x}: {cur.hex()}")
    data[SITE : SITE + len(PATCHED)] = PATCHED
    print(f"[force-ml] kit open -> Win_ML (mode 1) @{SITE:#x}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.dry_run:
        from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        for insn in md.disasm(PATCHED, SITE):
            print(f"{insn.address:08x}: {insn.mnemonic:8} {insn.op_str}")
        return 0
    raise SystemExit("applied via deploy_name_input_en.py")


if __name__ == "__main__":
    raise SystemExit(main())
