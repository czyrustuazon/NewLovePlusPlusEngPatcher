#!/usr/bin/env python3
"""Hometown prefecture list: fit 9-letter EN names (Fukushima / Yamanashi).

Vanilla is sized for 3–4 kanji. Latin names clip at 8 letters because:

1. CreateTextPane in FUN_0023c7e8 @ 0x0023cc30 is 64×16 (must stay power-of-two;
   96×16 is not POT and draws as garbage ``S0``). 128×16 matches the name-pane
   patch.
2. List DrawTextToPane in FUN_0023cf24 passes maxGlyphs=8 (four switch cases).
   That is the ``Fukushim`` / ``Yamanash`` cut. Raise to 16.
3. FUN_0023c040 then sizes the visible region from glyph count, clamping
   ``len > 7`` to 8. Raise that clamp to 12.

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

# mov r0, #8; str r0, [sp,#0]  (maxGlyphs) → #16
DRAW_SP0_SITES = (0x0023D008, 0x0023D104, 0x0023D1A8)
ORIG_DRAW_SP0 = bytes.fromhex("0800a0e300008de5")
WIDE_DRAW_SP0 = bytes.fromhex("1000a0e300008de5")
# fourth case stores maxGlyphs at [sp,#4]
ADDR_DRAW_SP4 = 0x0023D278
ORIG_DRAW_SP4 = bytes.fromhex("0800a0e304008de5")
WIDE_DRAW_SP4 = bytes.fromhex("1000a0e304008de5")


def _pane_ok(data: bytes) -> bool:
    return data[ADDR_PANE : ADDR_PANE + len(WIDE_PANE)] == WIDE_PANE


def _caps_ok(data: bytes) -> bool:
    return all(data[s : s + len(WIDE_CAP)] == WIDE_CAP for s in GLYPH_CAP_SITES)


def _draw_ok(data: bytes) -> bool:
    if data[ADDR_DRAW_SP4 : ADDR_DRAW_SP4 + len(WIDE_DRAW_SP4)] != WIDE_DRAW_SP4:
        return False
    return all(
        data[s : s + len(WIDE_DRAW_SP0)] == WIDE_DRAW_SP0 for s in DRAW_SP0_SITES
    )


def is_wide(data: bytes) -> bool:
    return _pane_ok(data) and _caps_ok(data) and _draw_ok(data)


def is_vanilla(data: bytes) -> bool:
    if data[ADDR_PANE : ADDR_PANE + len(ORIG_PANE)] != ORIG_PANE:
        return False
    if any(data[s : s + len(ORIG_CAP)] != ORIG_CAP for s in GLYPH_CAP_SITES):
        return False
    if data[ADDR_DRAW_SP4 : ADDR_DRAW_SP4 + len(ORIG_DRAW_SP4)] != ORIG_DRAW_SP4:
        return False
    return all(
        data[s : s + len(ORIG_DRAW_SP0)] == ORIG_DRAW_SP0 for s in DRAW_SP0_SITES
    )


def apply_patch(data: bytearray) -> bool:
    """Return True if bytes changed. Safe to re-run on the 96px / cap-only experiments."""
    if is_wide(data):
        print("[bplace-pane] hometown list already 128px + DrawText 16 + cap 12")
        return False

    changed = False

    pane = bytes(data[ADDR_PANE : ADDR_PANE + len(WIDE_PANE)])
    if pane != WIDE_PANE:
        if pane not in (ORIG_PANE, BAD_PANE):
            raise ValueError(
                f"unexpected BPlace CreateTextPane setup at {ADDR_PANE:#x}: {pane.hex()}"
            )
        data[ADDR_PANE : ADDR_PANE + len(WIDE_PANE)] = WIDE_PANE
        changed = True

    for site in GLYPH_CAP_SITES:
        cap = bytes(data[site : site + len(ORIG_CAP)])
        if cap == WIDE_CAP:
            continue
        if cap != ORIG_CAP:
            raise ValueError(f"unexpected BPlace glyph cap at {site:#x}: {cap.hex()}")
        data[site : site + len(WIDE_CAP)] = WIDE_CAP
        changed = True

    for site in DRAW_SP0_SITES:
        blk = bytes(data[site : site + len(ORIG_DRAW_SP0)])
        if blk == WIDE_DRAW_SP0:
            continue
        if blk != ORIG_DRAW_SP0:
            raise ValueError(
                f"unexpected BPlace DrawText maxGlyphs at {site:#x}: {blk.hex()}"
            )
        data[site : site + len(WIDE_DRAW_SP0)] = WIDE_DRAW_SP0
        changed = True

    sp4 = bytes(data[ADDR_DRAW_SP4 : ADDR_DRAW_SP4 + len(ORIG_DRAW_SP4)])
    if sp4 != WIDE_DRAW_SP4:
        if sp4 != ORIG_DRAW_SP4:
            raise ValueError(
                f"unexpected BPlace DrawText maxGlyphs at {ADDR_DRAW_SP4:#x}: {sp4.hex()}"
            )
        data[ADDR_DRAW_SP4 : ADDR_DRAW_SP4 + len(WIDE_DRAW_SP4)] = WIDE_DRAW_SP4
        changed = True

    if changed:
        print(
            "[bplace-pane] hometown list: pane 128x16, DrawText maxGlyphs 8->16, "
            "FUN_0023c040 cap 8->12"
        )
    return changed
