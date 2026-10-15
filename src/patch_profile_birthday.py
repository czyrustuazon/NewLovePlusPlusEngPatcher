#!/usr/bin/env python3
"""Profile confirm sheet: birthday value prints "June 23".

File 0x00350254 sprintf's the month byte, strcat's TRB slot 0x3f (月 → "Month"),
then the day byte and slot 0x3e (日 → " Day(s)"). June 23 becomes
"6Month23 Day(s)". Those two tokens are shared duration units, so this
overwrites that stretch instead of the TRB. Month names sit in the unused
tail of the SpotPass .rodata pad (data only). A month outside 1..12 leaves
the row blank and continues with blood type.
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

SITE = 0x00350254
DRAW = 0x003502D8  # add r2, sp, #8; pane index 5
SKIP = 0x003502E8  # blood type; birthday row stays empty
WINDOW = DRAW - SITE

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# The stretch this patch replaces. Captured from vanilla code.bin.
VANILLA_WINDOW = bytes.fromhex(
    "c0208fe2"  # add r2, pc, #0xc0
    "1810a0e3"  # mov r1, #0x18
    "08008de2"  # add r0, sp, #8
    "e6bff2fa"  # blx sprintf
    "3f30a0e3"  # mov r3, #0x3f
    "0720a0e1"
    "0810a0e3"
    "38008de2"
    "00608de5"
    "ffc209eb"  # bl TextResource
    "1820a0e3"
    "38108de2"
    "08008de2"
    "23c2f2fa"  # blx strcat
    "8130d4e5"  # ldrb r3, [r4, #0x81]
    "84208fe2"
    "1810a0e3"
    "20008de2"
    "d7bff2fa"
    "3e30a0e3"  # mov r3, #0x3e
    "0720a0e1"
    "0810a0e3"
    "38008de2"
    "00608de5"
    "f0c209eb"
    "1820a0e3"
    "38108de2"
    "20008de2"
    "14c2f2fa"
    "1820a0e3"
    "20108de2"
    "08008de2"
    "10c2f2fa"  # blx strcat day onto month
)


def _u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def _b(here: int, target: int, cond: int = 0xE) -> bytes:
    imm = ((target - here - 8) >> 2) & 0xFFFFFF
    return _u32((cond << 28) | 0x0A000000 | imm)


def format_birthday(month: int, day: int) -> str | None:
    """English confirm-sheet value, or None when the month byte is unusable."""
    if not 1 <= month <= 12:
        return None
    return f"{MONTHS[month - 1]} {day}"


def build_month_table() -> bytes:
    if len(MONTHS) != BIRTHDAY_MONTH_COUNT:
        raise ValueError(f"{len(MONTHS)} months, want {BIRTHDAY_MONTH_COUNT}")
    blob = bytearray()
    for name in MONTHS:
        raw = name.encode("ascii") + b"\x00"
        if len(raw) > BIRTHDAY_MONTH_STRIDE:
            raise ValueError(f"{name} is {len(raw)} bytes, stride {BIRTHDAY_MONTH_STRIDE}")
        blob += raw + b"\x00" * (BIRTHDAY_MONTH_STRIDE - len(raw))
    end = ADDR_BIRTHDAY_MONTHS + len(blob)
    pad_end = ADDR_SPOTPASS_PAYLOAD + SPOTPASS_PAYLOAD_MAX
    if end > pad_end:
        raise ValueError(f"month table ends @{end:#x}, past the SpotPass pad @{pad_end:#x}")
    return bytes(blob)


def build_window() -> bytes:
    """ARM that writes "June 23" at sp+8, then branches to the existing draw."""
    table_va = ADDR_BIRTHDAY_MONTHS + 0x100000
    here = SITE
    code = bytearray()

    def emit(word: bytes) -> None:
        nonlocal here
        code.extend(word)
        here += 4

    emit(_u32(0xE5D40080))  # ldrb r0, [r4, #0x80]
    emit(_u32(0xE2500001))  # subs r0, r0, #1
    emit(_u32(0xE350000B))  # cmp r0, #11
    emit(_b(here, SKIP, 0x8))  # bhi skip
    emit(_u32(0xE59F1060))  # ldr r1, [pc, #0x60]
    emit(_u32(0xE0800080))  # add r0, r0, r0, lsl #1
    emit(_u32(0xE0811100))  # add r1, r1, r0, lsl #2
    emit(_u32(0xE28D2008))  # add r2, sp, #8
    loop = here
    emit(_u32(0xE4D10001))  # ldrb r0, [r1], #1
    emit(_u32(0xE3500000))  # cmp r0, #0
    beq_at = here
    emit(b"\x00" * 4)  # beq space
    emit(_u32(0xE4C20001))  # strb r0, [r2], #1
    emit(_b(here, loop))  # b loop
    space = here
    emit(_u32(0xE3A00020))  # mov r0, #0x20
    emit(_u32(0xE4C20001))  # strb r0, [r2], #1
    emit(_u32(0xE5D43081))  # ldrb r3, [r4, #0x81]
    emit(_u32(0xE3A00000))  # mov r0, #0
    emit(_u32(0xE353000A))  # cmp r3, #10
    blo_at = here
    emit(b"\x00" * 4)  # blo ones
    tens = here
    emit(_u32(0xE243300A))  # sub r3, r3, #10
    emit(_u32(0xE2800001))  # add r0, r0, #1
    emit(_u32(0xE353000A))  # cmp r3, #10
    emit(_b(here, tens, 0x2))  # bhs tens
    emit(_u32(0xE2800030))  # add r0, r0, #'0'
    emit(_u32(0xE4C20001))  # strb r0, [r2], #1
    ones = here
    emit(_u32(0xE2833030))  # add r3, r3, #'0'
    emit(_u32(0xE5C23000))  # strb r3, [r2]
    emit(_u32(0xE3A00000))  # mov r0, #0
    emit(_u32(0xE5C20001))  # strb r0, [r2, #1]
    emit(_b(here, DRAW))
    lit = here
    emit(_u32(table_va))
    while here < DRAW:
        emit(_u32(0xE1A00000))  # nop

    code[beq_at - SITE : beq_at - SITE + 4] = _b(beq_at, space, 0x0)
    code[blo_at - SITE : blo_at - SITE + 4] = _b(blo_at, ones, 0x3)
    if lit != SITE + 30 * 4:
        raise ValueError(f"literal at {lit:#x}, ldr imm assumes {SITE + 30 * 4:#x}")
    if len(code) != WINDOW:
        raise ValueError(f"window {len(code)} != {WINDOW}")
    return bytes(code)


def is_patched(data: bytes) -> bool:
    return data[SITE : SITE + WINDOW] == build_window()


def apply_patch(data: bytearray) -> bool:
    window = build_window()
    table = build_month_table()
    have = bytes(data[SITE : SITE + WINDOW])
    have_table = bytes(data[ADDR_BIRTHDAY_MONTHS : ADDR_BIRTHDAY_MONTHS + len(table)])
    if have == window and have_table == table:
        print(f"[profile-birthday] already applied @{SITE:#x}")
        return False
    if have != VANILLA_WINDOW:
        raise ValueError(f"unexpected insn @{SITE:#x}: {have[:4].hex()}")
    if have_table != b"\x00" * len(table):
        raise ValueError(
            f"month table @{ADDR_BIRTHDAY_MONTHS:#x} not empty: {have_table[:8].hex()}"
        )
    if len(VANILLA_WINDOW) != WINDOW:
        raise ValueError(f"vanilla window {len(VANILLA_WINDOW)} != {WINDOW}")
    data[SITE : SITE + WINDOW] = window
    data[ADDR_BIRTHDAY_MONTHS : ADDR_BIRTHDAY_MONTHS + len(table)] = table
    print(f"[profile-birthday] @{SITE:#x} writes month name + day ({len(window)} B)")
    return True
