"""Keep the Web event-card digits in their original slots.

Month tens/ones and day tens/ones are the vanilla centers 34, 40, 58, 64.
That row is ``MM/DD``: the picture between the pairs is only a slash
(``deploy_web_event_date_en.py``). An earlier pass slid the digits left so
a longer ``Update`` label would fit, and that covered the Spot-tab HOT badge.
"""
from __future__ import annotations

import struct

# File address of the four X positions. The setter is the loop at 0x1BF418.
ADDR_DIGIT_X = 0x006BE034

# Vanilla centers: 34, 40, 58, 64. Layout space, same as Pos_Spot_Num_*.
VANILLA_X = (34.0, 40.0, 58.0, 64.0)

# The left-shifted experiment. apply_patch puts these back.
SHIFTED_X = (10.0, 16.0, 35.0, 41.0)


def _floats(data: bytes) -> tuple[float, ...]:
    return struct.unpack_from("<4f", data, ADDR_DIGIT_X)


def is_patched(data: bytes) -> bool:
    return _floats(data) == VANILLA_X


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[web-event-date] digit positions already MM/DD slots")
        return False
    got = _floats(data)
    if got != SHIFTED_X:
        raise ValueError(f"unexpected date-digit X @ {ADDR_DIGIT_X:#x}: {got}")
    struct.pack_into("<4f", data, ADDR_DIGIT_X, *VANILLA_X)
    print("[web-event-date] digit X restored to 34, 40, 58, 64")
    return True
