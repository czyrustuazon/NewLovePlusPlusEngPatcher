"""Draw short speaker names in the talk window without extra letter spacing.

TalkWindow ``FUN_0013b9a0`` counts the speaker's glyphs (``0x005BF428``,
capped at 8) and indexes this ``.rodata`` table of ``{x offset, spacing}``
halfword pairs. The spacing goes to the name glyph-quad ``+0x17c`` and is
added after every glyph:

    glyphs  1     2      3      4      5..8
    vanilla 21,0  6,16   -1,8   -3,2   0,0

That spreads a two-kanji name across the plate. Latin letters are half as
wide, so a three-letter name such as ``PPP`` draws as ``P P P``. Every
length uses ``0, 0`` here, the same as five or more glyphs.
"""
from __future__ import annotations

import struct

# File address of the table (runtime VA 0x007E3000). 9 entries, index 0 unused.
ADDR_SPEAKER_SPACING = 0x006E3000

VANILLA = ((0, 0), (21, 0), (6, 16), (-1, 8), (-3, 2), (0, 0), (0, 0), (0, 0), (0, 0))
PATCHED = ((0, 0),) * 9

_FMT = "<18h"


def _pack(table: tuple[tuple[int, int], ...]) -> bytes:
    return struct.pack(_FMT, *(v for pair in table for v in pair))


def _read(data: bytes) -> bytes:
    return bytes(data[ADDR_SPEAKER_SPACING : ADDR_SPEAKER_SPACING + struct.calcsize(_FMT)])


def is_patched(data: bytes) -> bool:
    return _read(data) == _pack(PATCHED)


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[speaker-spacing] talk name spacing already 0")
        return False
    got = _read(data)
    if got != _pack(VANILLA):
        raise ValueError(f"unexpected speaker spacing table @ {ADDR_SPEAKER_SPACING:#x}: {got.hex()}")
    data[ADDR_SPEAKER_SPACING : ADDR_SPEAKER_SPACING + len(got)] = _pack(PATCHED)
    print("[speaker-spacing] talk name offsets/spacing for 1-4 glyphs -> 0")
    return True
