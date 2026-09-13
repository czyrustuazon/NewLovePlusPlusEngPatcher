#!/usr/bin/env python3
"""Hometown prefecture list: fit 9-letter EN names (Fukushima / Yamanashi).

Two clamps, both vanilla-sized for 3–4 kanji:

1. CreateTextPane in FUN_0023c7e8 @ 0x0023cc30 is 64×16 (must stay power-of-two;
   96×16 is not POT and draws as garbage ``S0``). 128×16 matches the name-pane
   patch and holds ~16 Latin cells.
2. After DrawText, FUN_0023c040 sizes the visible region from glyph count, but
   three sites clamp ``len > 7`` to 8 — so ``Fukushima`` becomes ``Fukushim``.
   Raise that clamp to 12.

Applied from tools/deploy_name_input_en.py.
"""
from __future__ import annotations

# mov r1, #W; str r10, [sp, #0x94]; mov r0, #0x10; mov r12, #W
ADDR_PANE = 0x0023CC30
ORIG_PANE = bytes.fromhex("4010a0e394a08de51000a0e340c0a0e3")  # 64
BAD_PANE = bytes.fromhex("6010a0e394a08de51000a0e360c0a0e3")  # 96, non-POT
WIDE_PANE = bytes.fromhex("8010a0e394a08de51000a0e380c0a0e3")  # 128

# cmp r2, #7; movgt r2, #8  → movgt r2, #12
GLYPH_CAP_SITES = (0x0023C1E0, 0x0023C2E8, 0x0023C478)
ORIG_CAP = bytes.fromhex("070052e30820a0c3")
WIDE_CAP = bytes.fromhex("070052e30c20a0c3")


def is_wide(data: bytes) -> bool:
    return data[ADDR_PANE : ADDR_PANE + len(WIDE_PANE)] == WIDE_PANE and all(
        data[s : s + len(WIDE_CAP)] == WIDE_CAP for s in GLYPH_CAP_SITES
    )


def is_vanilla(data: bytes) -> bool:
    return data[ADDR_PANE : ADDR_PANE + len(ORIG_PANE)] == ORIG_PANE and all(
        data[s : s + len(ORIG_CAP)] == ORIG_CAP for s in GLYPH_CAP_SITES
    )


def apply_patch(data: bytearray) -> bool:
    """Return True if bytes changed."""
    if is_wide(data):
        print("[bplace-pane] hometown list already 128px + 12-glyph cap")
        return False

    pane = bytes(data[ADDR_PANE : ADDR_PANE + len(WIDE_PANE)])
    if pane not in (ORIG_PANE, BAD_PANE):
        raise ValueError(
            f"unexpected BPlace CreateTextPane setup at {ADDR_PANE:#x}: {pane.hex()}"
        )
    for site in GLYPH_CAP_SITES:
        cap = bytes(data[site : site + len(ORIG_CAP)])
        if cap not in (ORIG_CAP, WIDE_CAP):
            raise ValueError(
                f"unexpected BPlace glyph cap at {site:#x}: {cap.hex()}"
            )

    data[ADDR_PANE : ADDR_PANE + len(WIDE_PANE)] = WIDE_PANE
    for site in GLYPH_CAP_SITES:
        data[site : site + len(WIDE_CAP)] = WIDE_CAP
    print(
        f"[bplace-pane] hometown panes 64x16 -> 128x16 @ {ADDR_PANE:#x}; "
        f"glyph cap 8 -> 12 at {', '.join(f'{s:#x}' for s in GLYPH_CAP_SITES)}"
    )
    return True
