#!/usr/bin/env python3
"""Widen the weekly weather day-name capture and untighten the week range.

Txt_Day_%02d (file 0x1ffdd0, inside the weather text setter) captures each
day name at 16×14. That box fits one kanji. English Tue/Wed/… is the same
DrawText path as today's "Mon", which is captured at 64×28 and shown in a
32×14 pane. These four immediates make the weekly names use that capture.
The layout pane stays 32×14 (deploy_web_weather_en.py).

Txt_Week (``10/21-10/27``) and the day numbers Txt_Week_%02d set the text
object's per-glyph spacing (+0x178) to -3 and -2 px. That closed up
vanilla's em-wide ``１０／２１``; the ASCII digits from
patch_weather_weekdays.py overlap or clip, so both use 0.
"""
from __future__ import annotations

import struct

# mov / strh sites. Neighbors (the add ip, the other strh) stay put.
_SITES = (
    # mov r3, #0x10 -> #0x40   clip width
    (0x001FFDD0, 0xE3A03010, 0xE3A03040),
    # mov r1, #0x10 -> #0x20   buffer height (width comes from r3)
    (0x001FFDD4, 0xE3A01010, 0xE3A01020),
    # mov r0, #0xe  -> #0x1c   clip height
    (0x001FFDDC, 0xE3A0000E, 0xE3A0001C),
    # strh r1, [sp, #0xc0] -> strh r3  buffer width 64
    (0x001FFDE0, 0xE1CD1CB0, 0xE1CD3CB0),
    # mvn r0, #2 -> mov r0, #0   Txt_Week glyph spacing -3 -> 0
    (0x001FFBF8, 0xE3E00002, 0xE3A00000),
    # mvn r0, #1 -> mov r0, #0   Txt_Week_%02d glyph spacing -2 -> 0
    (0x001FFCD0, 0xE3E00001, 0xE3A00000),
)


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def is_patched(data: bytes) -> bool:
    return all(_u32(data, off) == new for off, _old, new in _SITES)


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[weather-day] day-name capture already 64x28, week spacing 0")
        return False
    for off, old, new in _SITES:
        got = _u32(data, off)
        if got not in (old, new):
            raise ValueError(f"unexpected insn @{off:#x}: {got:08x}")
    for off, _old, new in _SITES:
        struct.pack_into("<I", data, off, new)
    print("[weather-day] Txt_Day capture 16x14 -> 64x28 (same as Txt_Today01)")
    print("[weather-day] Txt_Week / Txt_Week_NN glyph spacing -> 0 (ASCII dates)")
    return True
