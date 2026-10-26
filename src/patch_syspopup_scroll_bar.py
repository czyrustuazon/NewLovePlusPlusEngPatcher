"""Make the SysPopup message box scroll bar track the whole text.

In the Win01 message box (class ctor ``0x001D9BAC``) a scrolling text has
height ``textH`` = lines * 14 (``+0x14c``), window ``winH`` = 112 (``+0x150``),
and scroll position ``pos`` (``+0x148``) starting at -67. The bar is
``track * winH / textH`` long (``FUN_001d909c``), and ``FUN_001d8f54`` places
it at

    t = (pos + 67) * (1 - bar / track) / winH        (clamped to 1)

which treats the scroll range as one window. That holds roughly for the
vanilla boxes (16 lines at most) but not for the 59-line localization
credits: the bar reached the bottom after ~9 lines.

``FUN_001d92f8`` clamps ``pos`` to ``paneY + 14 - winH + textH`` from the
text pane's translate, which also scrolls past the last line into blank
texture. Here the clamp becomes ``textH - winH - 67`` (the last line stops at
the bottom of the window), so the range is exactly ``textH - winH`` and the
bar formula reduces to

    t = (pos + 67) / textH

which ends at ``1 - bar / track``: the bar's bottom on the track's end.
"""
from __future__ import annotations

import struct

# File addresses (runtime VA = +0x100000). (address, vanilla, patched)
_WORDS = (
    # FUN_001d92f8 scroll clamp: max = textH - winH + (-67).
    (0x001D93A0, 0xEE301AC1, 0xEE301A41),  # vsub s2, s1, s2 -> vsub s2, s0, s2
    (0x001D93B4, 0xEE311A08, 0xEE311A28),  # vadd s2, s2, s16 -> vadd s2, s2, s17
    (0x001D93B8, 0xEE310A00, 0xEEB00A41),  # vadd s0, s2, s0 -> vmov s0, s2
    # FUN_001d8f54 bar position: t = (pos + 67) / textH.
    (0x001D8FDC, 0xEDD42A54, 0xEDD42A53),  # vldr s5, [r4, #0x150] -> [r4, #0x14c]
    (0x001D8FF4, 0xEEC20A22, 0xEEC30A22),  # vdiv s1, s4, s5 -> vdiv s1, s6, s5
)


def _word(data: bytes, addr: int) -> int:
    return struct.unpack_from("<I", data, addr)[0]


def is_patched(data: bytes) -> bool:
    return all(_word(data, a) == new for a, _old, new in _WORDS)


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[syspopup-scroll] message box scroll bar already tracks the text")
        return False
    for addr, old, _new in _WORDS:
        got = _word(data, addr)
        if got != old:
            raise ValueError(f"SysPopup scroll @ {addr:#x}: {got:08x}, expected vanilla {old:08x}")
    for addr, _old, new in _WORDS:
        struct.pack_into("<I", data, addr, new)
    print("[syspopup-scroll] message box: scroll stops at the last line, bar spans the text")
    return True
