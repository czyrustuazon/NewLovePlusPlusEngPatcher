"""Save-data dates print MM/DD/YYYY.

Each site reads a DateTime through getters (day 0x733280, month 0x733428,
year 0x7333D0) and sprintf's it year first. The patch only reorders the
arguments so month comes first and year last.

Data select "Last Saved" (file 0x00057940) is ``"%d%s%d%s%d"`` with the TRB
"/" between fields, so 2026/7/23 becomes 7/23/2026. 0x0005F3A8 is the same.

File 0x0036A4E8 and 0x0036EA04 use ``"%4d/%2d/%2d"``. That is 12 bytes, too short for ``"%02d/%02d/%4d"``, so
its ``add r2, pc`` becomes ``ldr r2, [pc]`` of the same offset and the old
string's first word holds a pointer to FORMAT in the SpotPass pad.

File 0x0021C0C4 (three-slot list) uses ``"%4d/%02d/%02d"``. Its three getter
calls are reordered instead and the format rewritten in place.

Those print 10/19/2026.
"""
from __future__ import annotations

import struct

from patch_input_cave_map import (
    ADDR_BIRTHDAY_MONTHS,
    ADDR_SPOTPASS_PAYLOAD,
    BIRTHDAY_MONTH_COUNT,
    BIRTHDAY_MONTH_STRIDE,
    SPOTPASS_PAYLOAD_MAX,
)

VA_BASE = 0x100000

FORMAT = b"%02d/%02d/%4d\x00"
# Data only, right after the Profile birthday month table.
ADDR_FORMAT = ADDR_BIRTHDAY_MONTHS + BIRTHDAY_MONTH_COUNT * BIRTHDAY_MONTH_STRIDE
FORMAT_SLOT = 16


def _w(x: int) -> bytes:
    return struct.pack("<I", x)


def _bl(here: int, target: int) -> bytes:
    imm = ((target - (here + VA_BASE) - 8) >> 2) & 0xFFFFFF
    return _w(0xEB000000 | imm)


# (file offset, vanilla word, patched word). Old string words come last.
def _dsel(mov_r3: int, adr: int, adr_imm: int, str4: int, str0: int,
          day_reg: int, month_reg: int) -> list[tuple[int, bytes, bytes]]:
    old_fmt = adr + 8 + adr_imm
    return [
        (mov_r3, _w(0xE1A03000), _w(0xE58D0004)),  # mov r3, r0 -> str r0, [sp, #4]
        (adr, _w(0xE28F2000 | _rot_imm(adr_imm)), _w(0xE59F2000 | adr_imm)),
        (str4, _w(0xE58D0004 | day_reg << 12), _w(0xE1A03000 | month_reg)),
        (str0, _w(0xE58D0000 | month_reg << 12), _w(0xE58D0000 | day_reg << 12)),
        (old_fmt, b"%4d/", _w(ADDR_FORMAT + VA_BASE)),
        (old_fmt + 4, b"%2d/", b"%2d/"),
        (old_fmt + 8, b"%2d\x00", b"%2d\x00"),
    ]


def _rot_imm(v: int) -> int:
    for rot in range(16):
        r = rot * 2
        b = ((v << r) | (v >> (32 - r))) & 0xFFFFFFFF if r else v
        if b < 0x100:
            return rot << 8 | b
    raise ValueError(f"{v:#x} is not an ARM immediate")


GET_DAY = 0x00733280
GET_MONTH = 0x00733428
GET_YEAR = 0x007333D0

ADDR_LIST_CALLS = (0x0021C0C8, 0x0021C0D4, 0x0021C0E0)  # -> [sp+4], [sp], r3
ADDR_LIST_FORMAT = 0x0021C1AC
LIST_VANILLA_FORMAT = b"%4d/%02d/%02d\x00"
LIST_PATCHED_FORMAT = b"%02d/%02d/%4d\x00"


def _list_words() -> list[tuple[int, bytes, bytes]]:
    words = [
        (at, _bl(at, old), _bl(at, new))
        for at, old, new in zip(
            ADDR_LIST_CALLS,
            (GET_DAY, GET_MONTH, GET_YEAR),
            (GET_YEAR, GET_DAY, GET_MONTH),
        )
    ]
    for k in range(0, len(LIST_VANILLA_FORMAT), 4):
        at = ADDR_LIST_FORMAT + k
        old = LIST_VANILLA_FORMAT[k : k + 4].ljust(4, b"\x00")
        new = LIST_PATCHED_FORMAT[k : k + 4].ljust(4, b"\x00")
        words.append((at, old, new))
    return words


def _words(pairs: list[tuple[int, int, int]]) -> list[tuple[int, bytes, bytes]]:
    return [(at, _w(old), _w(new)) for at, old, new in pairs]


R4, R5, R9, R10 = 4, 5, 9, 10

SITES = {
    # Data select "Last Saved": "%d%s%d%s%d" with the TRB "/" (0x100 slot 0xd).
    # r0 year, sb month, r8 day, r6 "/". Unpadded, like vanilla: 7/23/2026.
    "dsel_last_saved": _words([
        (0x00057940, 0xE28D1008, 0xE58D000C),  # add r1, sp, #8 -> str r0, [sp, #12]
        (0x00057944, 0xE88D0240, 0xE88D0140),  # stm sp, {r6, sb} -> {r6, r8}
        (0x00057948, 0xE8810140, 0xE58D6008),  # stm r1, {r6, r8} -> str r6, [sp, #8]
        (0x0005794C, 0xE1A03000, 0xE1A03009),  # mov r3, r0 -> mov r3, sb
    ]),
    # Same "%d%s%d%s%d" date: r0 year, [sp] month, fp day, r8 separator.
    "date_0x15f3c8": _words([
        (0x0005F3A8, 0xE59D1000, 0xE59D3000),  # ldr r1, [sp] -> ldr r3, [sp]
        (0x0005F3AC, 0xE28DC004, 0xE58D000C),  # add ip, sp, #4 -> str r0, [sp, #12]
        (0x0005F3B0, 0xE58D8000, 0xE58D8000),  # str r8, [sp]
        (0x0005F3B4, 0xE1A03000, 0xE58DB004),  # mov r3, r0 -> str fp, [sp, #4]
        (0x0005F3B8, 0xE88C0902, 0xE58D8008),  # stm ip, {r1, r8, fp} -> str r8, [sp, #8]
    ]),
    # "%4d/%2d/%2d" year/month/day lists; screens not identified yet.
    "date_0x46a500": _dsel(0x0036A4E8, 0x0036A4EC, 0x324, 0x0036A4F8, 0x0036A4FC, R9, R10),
    "date_0x46ea1c": _dsel(0x0036EA04, 0x0036EA0C, 0x1E0, 0x0036EA14, 0x0036EA18, R4, R5),
    "date_0x31c0f4": _list_words(),
}


def _format_room() -> None:
    pad_end = ADDR_SPOTPASS_PAYLOAD + SPOTPASS_PAYLOAD_MAX
    if len(FORMAT) > FORMAT_SLOT or ADDR_FORMAT + FORMAT_SLOT > pad_end:
        raise ValueError(f"format @{ADDR_FORMAT:#x} does not fit the SpotPass pad")


def _all_words() -> list[tuple[int, bytes, bytes]]:
    return [w for words in SITES.values() for w in words]


def _format_have(data: bytes) -> bytes:
    return bytes(data[ADDR_FORMAT : ADDR_FORMAT + FORMAT_SLOT])


def _format_new() -> bytes:
    return FORMAT.ljust(FORMAT_SLOT, b"\x00")


def is_patched(data: bytes) -> bool:
    _format_room()
    return _format_have(data) == _format_new() and all(
        data[at : at + 4] == new for at, _old, new in _all_words()
    )


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[save-slot-date] already MM/DD/YYYY")
        return False
    bad = [
        f"{at:#x}: {bytes(data[at : at + 4]).hex()} != {old.hex()}"
        for at, old, _new in _all_words()
        if data[at : at + 4] != old
    ]
    if bad:
        raise ValueError("unexpected save-slot date bytes:\n  " + "\n  ".join(bad))
    if _format_have(data) != b"\x00" * FORMAT_SLOT:
        raise ValueError(f"format pad @{ADDR_FORMAT:#x} not empty: {_format_have(data).hex()}")
    for at, _old, new in _all_words():
        data[at : at + 4] = new
    data[ADDR_FORMAT : ADDR_FORMAT + FORMAT_SLOT] = _format_new()
    print(f"[save-slot-date] {', '.join(SITES)} print MM/DD/YYYY")
    return True
