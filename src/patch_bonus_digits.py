"""Draw the BONUS! popup's Riches amounts in ASCII digits.

"You got ５０ Riches! Now you have １００ Riches." (TRB 4795, pack 0x1901)
gets its two numbers from ``FUN_0056f930``. It splits the value (capped at
999999) into digits, skips leading zeros, and appends text resource pack
0x0100 slot *digit* for each one. Slots 0–9 are full-width ``０``–``９``,
one em wide, so English shows ``5 0`` and ``1 0 0`` with gaps.

The same pack holds ASCII ``0``–``9`` at slots 17–26. Fetching slot
*digit* + 17 draws ``50`` and ``100``. ``FUN_002ef9fc`` (the popup's setter)
is the formatter's only caller, so nothing else changes. The weather digits
were fixed the other way, in the TRB (patch_weather_weekdays.py), because
pack 0xD002 has no ASCII rows.
"""
from __future__ import annotations

import struct

# File address (runtime VA = +0x100000).
ADDR_DIGIT_SLOT = 0x0056F9E4
VANILLA = 0xE6FF1070  # uxth r1, r0         slot = digit
PATCHED = 0xE2801011  # add  r1, r0, #0x11  slot = digit + 17
ASCII_DIGIT_SLOT = 17


def _word(data: bytes) -> int:
    return struct.unpack_from("<I", data, ADDR_DIGIT_SLOT)[0]


def is_patched(data: bytes) -> bool:
    return _word(data) == PATCHED


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[bonus-digits] Riches bonus already uses ASCII digits")
        return False
    got = _word(data)
    if got != VANILLA:
        raise ValueError(f"bonus digit slot @ {ADDR_DIGIT_SLOT:#x}: {got:08x}, expected {VANILLA:08x}")
    struct.pack_into("<I", data, ADDR_DIGIT_SLOT, PATCHED)
    print(f"[bonus-digits] Riches digits: pack 0x0100 slot digit -> digit + {ASCII_DIGIT_SLOT}")
    return True
