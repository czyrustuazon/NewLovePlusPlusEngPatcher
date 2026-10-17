#!/usr/bin/env python3
"""Text entry: gojūon board only, ABC by default, no pencil or kana buttons.

Every name / text entry screen embeds one shared input kit (create
``0x255ba4`` registers Win_Write, Win_ML, Btn_Change, Btn_ML). Kit byte
``+1`` is the input mode: **0** = Win_Write (CLEAR pad + pencil), **1** =
Win_ML (五十音 grid). Kit word ``+8`` is the keyboard mode = Btn_ML button
index: 0 Kanji, 1 Kana 1, 2 Kana 2, 3 S. Kana, 4 ABC, 5 Symbols.

Kit open ``0x255f38`` opens Write or ML from ``+1``. Every caller then runs
kit sync ``0x2571d4`` (ML ``+0x30`` keyboard mode, Btn_Change icon via
``0x22bf00``, Btn_ML select ``0x1f9138(btn, kit+8)``) and picks the Write
tick ``0x25601c`` or ML tick ``0x2567a8`` from ``+1``.

- Kit open stores ``+8 = 4`` (ABC) and ``+1 = 1`` (ML) and branches straight
  to the ML open. Covers first-boot "Register Last name"
  (IntroductionInputUtilUIOperator), Profile, DateEditName, InputUtil and the
  other kit users.
- Sync sets ML ``+0x30`` from ``+8`` instead of ``+1`` so the board opens in
  the same mode the button bar highlights.
- Btn_ML release handler ``0x1f8c78`` jumps on the touched button id; ids 0–3
  (Kanji / Kana 1 / Kana 2 / S. Kana) now go to its exit.
- Btn_Change (``Lyt_Prf_Btn_Change``) touch handlers: NOP the ``beq`` to the
  ``Bod_Obj01`` (pencil) branch.

The hidden panes / blank pencil are layout + texture edits in
``tools/deploy_input_keyboard_en.py`` and ``tools/deploy_profile_en.py``.

In place, no cave. Ships in ``deploy_name_input_en.py``.
"""
from __future__ import annotations

import argparse

NOP = bytes.fromhex("00f020e3")

SITE = 0x00255F40
VANILLA = bytes.fromhex(
    "0060a0e3"  # mov  r6, #0
    "0100d0e5"  # ldrb r0, [r0, #1]
    "c8509fe5"  # ldr  r5, =mgr
    "0010d4e5"  # ldrb r1, [r4]
    "000050e3"  # cmp  r0, #0
    "1700000a"  # beq  Write
    "010050e3"  # cmp  r0, #1
    "2100000a"  # beq  ML (0x255fe8)
)
PATCHED = bytes.fromhex(
    "0400a0e3"  # mov  r0, #4        ; keyboard mode = ABC
    "080084e5"  # str  r0, [r4, #8]
    "c8509fe5"  # ldr  r5, =mgr      ; same address, same literal
    "0010d4e5"  # ldrb r1, [r4]      ; variant
    "0100a0e3"  # mov  r0, #1        ; input mode = ML
    "0100c4e5"  # strb r0, [r4, #1]
    "0060a0e3"  # mov  r6, #0
    "210000ea"  # b    ML (0x255fe8)
)
# 2026-10-17 grid-only revision (6 words, cmp/beq left vanilla).
_OLD_PATCHED = bytes.fromhex(
    "0100a0e3" "0100c4e5" "c8509fe5" "0010d4e5" "0060a0e3" "00f020e3"
) + VANILLA[24:]

# (site, vanilla, patched, label)
SITES: tuple[tuple[int, bytes, bytes, str], ...] = (
    # Kit sync: ML +0x30 = kit+8 (ldrb r1,[r4,#1] -> ldr r1,[r4,#8]).
    (0x00257238, bytes.fromhex("0110d4e5"), bytes.fromhex("081094e5"), "sync mode"),
    # Btn_ML release jump table ids 0-3 -> exit 0x1f8fa8 (VA 0x2f8fa8).
    *(
        (0x001F8C9C + 4 * i, bytes.fromhex("b88c2f00"), bytes.fromhex("a88f2f00"), f"btn {i}")
        for i in range(4)
    ),
    # Btn_Change touch handlers (vtable +0x2c / +0x28): beq -> Bod_Obj01.
    (0x0022BFA4, bytes.fromhex("0500000a"), NOP, "pencil +0x2c"),
    (0x0022C1F8, bytes.fromhex("0500000a"), NOP, "pencil +0x28"),
)


def is_patched(data: bytes) -> bool:
    if bytes(data[SITE : SITE + len(PATCHED)]) != PATCHED:
        return False
    return all(bytes(data[s : s + len(p)]) == p for s, _v, p, _l in SITES)


def apply_patch(data: bytearray) -> None:
    cur = bytes(data[SITE : SITE + len(PATCHED)])
    if cur not in (VANILLA, PATCHED, _OLD_PATCHED):
        raise ValueError(f"unexpected kit open @{SITE:#x}: {cur.hex()}")
    for site, vanilla, patched, label in SITES:
        cur = bytes(data[site : site + len(patched)])
        if cur not in (vanilla, patched):
            raise ValueError(f"unexpected {label} @{site:#x}: {cur.hex()}")
    if is_patched(data):
        print(f"[force-ml] already patched @{SITE:#x}")
        return
    data[SITE : SITE + len(PATCHED)] = PATCHED
    for site, _vanilla, patched, _label in SITES:
        data[site : site + len(patched)] = patched
    print(
        f"[force-ml] kit open -> Win_ML, ABC @{SITE:#x}; "
        "kana/kanji buttons + pencil tap ignored"
    )


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
