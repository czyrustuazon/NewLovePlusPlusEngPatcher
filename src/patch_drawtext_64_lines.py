"""Let DrawTextToPane lay out 64 lines instead of 32.

``DrawTextToPane`` ``FUN_0054b880`` measures the string into two stack tables
at ``sp+0x35c``: glyphs per line (32 words) then cell widths per line (32
words at ``+0x80``), with the line counter right after at ``sp+0x45c``. It
copies all 0x104 bytes to ``sp+0x34`` before drawing. Line 33 writes its glyph
count over ``widths[0]`` and its width over the counter, so every later line
loses its centring and lands at x = half the texture.

This packs both values into one word per line: width in the low halfword,
glyph count in the high one. The same 0x100 bytes then hold 64 lines and the
counter stays where it was. Every rewrite keeps its slot's instruction count;
strings of 32 lines or fewer draw exactly as before.

The Main Menu localization credits (``patch_title_engpatch_info``) are one
59-line box.
"""
from __future__ import annotations

import struct

# File addresses (runtime VA = +0x100000). (address, vanilla, patched)
_WORDS = (
    # End of a line: store its glyph count (vanilla str r0, [sb, r1, lsl #2]).
    (0x0054B980, 0xE1A00005, 0xE0890101),  # mov r0, r5      -> add r0, sb, r1, lsl #2
    (0x0054B984, 0xE3A05000, 0xE1C050B2),  # mov r5, #0      -> strh r5, [r0, #2]
    (0x0054B988, 0xE7890101, 0xE3A05000),  # str r0, [sb..]  -> mov r5, #0
    (0x0054B98C, 0xE59D045C, 0xE2811001),  # ldr r0, [sp, #0x45c] -> add r1, r1, #1
    (0x0054B990, 0xE2800001, 0xE58D145C),  # add r0, r0, #1  -> str r1, [sp, #0x45c]
    (0x0054B994, 0xE58D045C, 0xE320F000),  # str r0, [sp, #0x45c] -> nop
    # Each glyph: add its cells to the line width.
    (0x0054BA98, 0xE5903080, 0xE1D030B0),  # ldr r3, [r0, #0x80] -> ldrh r3, [r0]
    (0x0054BAA0, 0xE5801080, 0xE1C010B0),  # str r1, [r0, #0x80] -> strh r1, [r0]
    # Last line without a trailing newline.
    (0x0054BABC, 0xE7895100, 0xE0891100),  # str r5, [sb, r0, lsl #2] -> add r1, sb, r0, lsl #2
    (0x0054BAC0, 0xE59D045C, 0xE1C150B2),  # ldr r0, [sp, #0x45c] -> strh r5, [r1, #2]
    # First line, read from the copy at sp+0x34.
    (0x0054BB44, 0xE28D1030, 0xE59D0030),  # add r1, sp, #0x30 -> ldr r0, [sp, #0x30]
    (0x0054BB4C, 0xE8910021, 0xE1DD53B6),  # ldm r1, {r0, r5} -> ldrh r5, [sp, #0x36]
    (0x0054BB58, 0xE59D70B4, 0xE1DD73B4),  # ldr r7, [sp, #0xb4] -> ldrh r7, [sp, #0x34]
    # Next line (r3 = sp+0x34 + line * 4).
    (0x0054BD78, 0xE79CC108, 0xE1D3C0B2),  # ldr ip, [ip, r8, lsl #2] -> ldrh ip, [r3, #2]
    (0x0054BD7C, 0xE5933080, 0xE1D330B0),  # ldr r3, [r3, #0x80] -> ldrh r3, [r3]
)

MAX_LINES = 64


def _word(data: bytes, addr: int) -> int:
    return struct.unpack_from("<I", data, addr)[0]


def is_patched(data: bytes) -> bool:
    return all(_word(data, a) == new for a, _old, new in _WORDS)


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[drawtext-64] DrawTextToPane already lays out 64 lines")
        return False
    for addr, old, _new in _WORDS:
        got = _word(data, addr)
        if got != old:
            raise ValueError(f"DrawTextToPane @ {addr:#x}: {got:08x}, expected vanilla {old:08x}")
    for addr, _old, new in _WORDS:
        struct.pack_into("<I", data, addr, new)
    print(f"[drawtext-64] DrawTextToPane line table: 32 -> {MAX_LINES} lines")
    return True
