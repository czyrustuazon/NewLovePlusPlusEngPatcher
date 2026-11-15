#!/usr/bin/env python3
"""Profile name caret: sit right after the typed text, ASCII or kana.

The Profile form (``Lyt_Prf_Info_Profile``, class around ``0x247xxx``) draws
Last/First Name centered on the field with DrawText's 7 px cells
(``GetCharWidthCells``: ASCII 1, anything else 2). Its blinking turquoise caret
(``Pts_Prf_Cur_Moji``) is placed from the glyph count ``n`` the setter stores at
``obj+0x4c+row*4``, clamped to 4:

    x = fieldCenter + 14 + (n-1)*7   (n > 0), minus 14 once n >= 4

That is right for centered fullwidth kana (text ends at center + 7n). ASCII
letters are half that width, so "AAA" left a gap and an 8-letter name (clamped
to 4) put the caret on the last two letters.

This patch stores the **cell count** in that slot instead and places the caret
at ``center + 3.5 * (cells + 2)``: half a caret past the text's right edge.
Kana give the vanilla position (cells = 2n); there is no back-step when full.

Sites (all in place, no caves):

* ``FUN_0024842c`` (setter, rows 0..5) caret block @ ``0x2484d0``: measure the
  drawn string (MakeStr char* at ``[sp+0xc]``) with ``MeasureText``
  ``FUN_005c0760`` straight into ``obj+0x4c+row*4``, then call the caret.
* ``FUN_00247d98`` (caret for rows 0/1) math @ ``0x247e24``: read cells from
  the slot; its 14.0 pool word @ ``0x247e80`` becomes 3.5.
* ``FUN_00248124`` (focus refresh) @ ``0x2482bc`` and math @ ``0x24833c``:
  same formula; its 7.0 pool word @ ``0x248388`` becomes 3.5.

Nothing else reads ``obj+0x4c+row*4`` (the ctor @ ``0x24855c`` zeroes it).
``FUN_00247ea4`` still stores a glyph count for row 4, which the caret ignores.
"""
from __future__ import annotations

import struct

ADDR_MEASURE_TEXT = 0x005C0760  # (str, &maxLineCells) -> line count

NOP = "00f020e3"
HALF = struct.pack("<f", 3.5).hex()  # 00006040


def _u32(x: int) -> str:
    return struct.pack("<I", x & 0xFFFFFFFF).hex()


def _bl(here: int, target: int) -> str:
    return _u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


# (file offset, vanilla hex, patched hex)
def sites() -> list[tuple[int, str, str]]:
    return [
        # Setter: measure cells into obj+0x4c+row*4, then caret(obj, row).
        (
            0x002484D0,
            "4c2094e5" "0510a0e1" "0900a0e1" "030052e3" "0420a0c3",
            "0c009de5"  # ldr r0, [sp, #0xc]    MakeStr char*
            "4c1084e2"  # add r1, r4, #0x4c     &cells[row]
            + _bl(0x002484D8, ADDR_MEASURE_TEXT)
            + "0510a0e1"  # mov r1, r5
            "0900a0e1",  # mov r0, sb
        ),
        # Caret rows 0/1: x = center + 3.5 * (cells + 2).
        (
            0x00247E24,
            "840084e0" "141adfed" "000185e0" "640080e2" "000056e3" "030a90ec"
            "070000da" "011046e2" "402af0ee" "101a00ee" "0c2a9fed" "c03ab8ee"
            "610ab0ee" "020a03ee" "800a32ee" "040056e3" "18008de2" "610a30ae",
            "840084e0"  # add r0, r4, r4, lsl #1
            "141adfed"  # vldr s3, [pc, #0x50]  -> 3.5 @ 0x247e80
            "000185e0"  # add r0, r5, r0, lsl #2
            "640080e2"  # add r0, r0, #0x64     field center vec3
            "041185e0"  # add r1, r5, r4, lsl #2
            "4c1091e5"  # ldr r1, [r1, #0x4c]   cells
            "021081e2"  # add r1, r1, #2
            "101a03ee"  # vmov s6, r1
            "c33ab8ee"  # vcvt.f32.s32 s6, s6
            "030a90ec"  # vldmia r0, {s0, s1, s2}
            "210a03ee"  # vmla.f32 s0, s6, s3
            "18008de2"  # add r0, sp, #0x18     handle
            + NOP * 6,
        ),
        (0x00247E80, "00006041", HALF),
        # Focus refresh: cells + 2 instead of min(n, 4).
        (
            0x002482C0,
            "030050e3" "0400a0c3",
            "020080e2"  # add r0, r0, #2
            + NOP,
        ),
        (
            0x0024833C,
            "000050e3" "060000da" "010040e2" "401af0ee" "100a00ee" "c02ab8ee"
            "480ab0ee" "280a02ee" "800a31ee" "68009de5" "040050e3" "38008de2"
            "480a30ae",
            "100a02ee"  # vmov s4, r0
            "c22ab8ee"  # vcvt.f32.s32 s4, s4
            "280a02ee"  # vmla.f32 s0, s4, s17  (s17 = 3.5)
            "38008de2"  # add r0, sp, #0x38     handle
            + NOP * 9,
        ),
        (0x00248388, "0000e040", HALF),
    ]


def _check_lengths() -> None:
    for addr, old, new in sites():
        assert len(old) == len(new), f"site {addr:#x}: {len(old)} != {len(new)}"


def is_patched(data: bytes) -> bool:
    return all(
        bytes(data[a : a + len(new) // 2]) == bytes.fromhex(new) for a, _, new in sites()
    )


def apply_patch(data: bytearray) -> bool:
    _check_lengths()
    if is_patched(data):
        print("[profile-caret] already applied")
        return False
    for addr, old, new in sites():
        have = bytes(data[addr : addr + len(old) // 2])
        if have not in (bytes.fromhex(old), bytes.fromhex(new)):
            raise ValueError(f"unexpected bytes @{addr:#x}: {have[:8].hex()}")
    for addr, _, new in sites():
        data[addr : addr + len(new) // 2] = bytes.fromhex(new)
    print("[profile-caret] Profile name caret = center + 3.5 * (cells + 2)")
    return True
