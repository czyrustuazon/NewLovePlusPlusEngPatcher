"""Widen the mail-template row text so English fits the pill.

``Pts_Mail_Btn02`` draws each send-phrase (``おはよう`` / ``おやすみ`` /
``何してる？`` …) into ``Tex_Reply_Text``. The row art is 200 px wide, but
``FUN_001acc64`` builds the line at a hardcoded 128 px (``mov r3, #0x80`` at
file ``0x001ACDB8``). Latin comes out about one glyph per 13 px, so
``Morning.`` fits and ``Good night.`` / ``What are you doing?`` stop at
``Good nigh…`` / ``What are …`` with empty pill to the right.

180 px keeps the line's left edge and stops about 9 px inside the pill.
The layout pane is widened to the same size in ``deploy_mail_home_en.py``.
"""
from __future__ import annotations

import struct

# File address. Runtime VA = file + 0x100000.
ADDR = 0x001ACDB8
VANILLA = 0xE3A03080  # mov r3, #0x80
PATCHED = 0xE3A030B4  # mov r3, #180


def _word(data: bytes, addr: int) -> int:
    return struct.unpack_from("<I", data, addr)[0]


def is_patched(data: bytes) -> bool:
    return _word(data, ADDR) == PATCHED


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[mail-reply] template row text already 180 px")
        return False
    got = _word(data, ADDR)
    if got != VANILLA:
        raise ValueError(
            f"mail reply width @ {ADDR:#x}: {got:08x}, expected vanilla {VANILLA:08x}"
        )
    struct.pack_into("<I", data, ADDR, PATCHED)
    print("[mail-reply] template row text 128 -> 180 px")
    return True
