"""Break talk lines at the previous space instead of mid-word.

``FUN_005bf750`` (file ``0x005BF750``) runs after the nickname is filled in.
ASCII is one column, everything else is two, and a line past the width
(30 for talk, 28 for a choice button) gets a newline in front of the
character that crossed. The only vanilla look-back is kinsoku, which will
not start a line on ``, . ) ? !`` and so pulls the letter before that
punctuation down with it: "absen / t," and "agai / n...".

The hook runs at the overflow, before kinsoku. It walks back along the
current line for an ASCII space and breaks in front of the next word.
A line with no space (Japanese) falls through to kinsoku unchanged. A word
longer than the width still hard-breaks, on the next pass, once that word
is alone on the line.
"""
from __future__ import annotations

import struct

from patch_input_cave_map import ADDR_DIALOG_BREAK_CAVE, DIALOG_BREAK_CAVE_LIMIT

# ldr r0, [sp, #0x48] — kinsoku flag. The cave runs this on the no-space path.
SITE = 0x005BF948
VANILLA = 0xE59D0048
RESUME = 0x005BF94C
INSERT = 0x005BFAD0  # newline store, after kinsoku has chosen sl
CAVE = ADDR_DIALOG_BREAK_CAVE


def _u32(word: int) -> bytes:
    return struct.pack("<I", word & 0xFFFFFFFF)


def _b(here: int, target: int, cond: int = 0xE) -> bytes:
    imm = ((target - here - 8) >> 2) & 0xFFFFFF
    return _u32((cond << 28) | 0x0A000000 | imm)


def build_cave(cave: int = CAVE) -> bytes:
    """Scan back for 0x20. Break after it, or resume the vanilla kinsoku path."""
    code = bytearray()

    def at() -> int:
        return cave + len(code)

    def emit(word: int) -> None:
        code.extend(_u32(word))

    emit(0xE1A0600A)  # mov r6, sl
    scan = at()
    emit(0xE3560000)  # cmp r6, #0
    beq_start = at()
    code.extend(b"\x00\x00\x00\x00")  # beq no_space
    emit(0xE2466001)  # sub r6, r6, #1
    emit(0xE7940106)  # ldr r0, [r4, r6, lsl #2]
    emit(0xE350000A)  # cmp r0, #0x0a
    beq_nl = at()
    code.extend(b"\x00\x00\x00\x00")  # beq no_space
    emit(0xE3500020)  # cmp r0, #0x20
    code.extend(_b(at(), scan, cond=0x1))  # bne scan
    emit(0xE2866001)  # add r6, r6, #1
    emit(0xE1A0A006)  # mov sl, r6
    code.extend(_b(at(), INSERT))
    no_space = at()
    emit(VANILLA)  # ldr r0, [sp, #0x48]
    code.extend(_b(at(), RESUME))
    struct.pack_into("<I", code, beq_start - cave, int.from_bytes(_b(beq_start, no_space, 0), "little"))
    struct.pack_into("<I", code, beq_nl - cave, int.from_bytes(_b(beq_nl, no_space, 0), "little"))
    if cave + len(code) > DIALOG_BREAK_CAVE_LIMIT:
        raise ValueError(
            f"dialog-break cave ends @{cave + len(code):#x}, "
            f"past {DIALOG_BREAK_CAVE_LIMIT:#x}"
        )
    return bytes(code)


def _word(data: bytes, addr: int) -> int:
    return struct.unpack_from("<I", data, addr)[0]


def is_patched(data: bytes) -> bool:
    return _word(data, SITE) == int.from_bytes(_b(SITE, CAVE), "little")


def apply_patch(data: bytearray) -> bool:
    cave = build_cave()
    hook = _b(SITE, CAVE)
    if is_patched(data):
        if data[CAVE : CAVE + len(cave)] != cave:
            raise ValueError("dialog break site patched but cave bytes differ")
        print(f"[dialog-break] already applied @{CAVE:#x}")
        return False
    got = _word(data, SITE)
    if got != VANILLA:
        raise ValueError(
            f"dialog break @{SITE:#x}: {got:08x}, expected vanilla {VANILLA:08x}"
        )
    region = data[CAVE : CAVE + len(cave)]
    if region != b"\x00" * len(cave):
        raise ValueError(f"cave @{CAVE:#x} not empty: {region[:8].hex()}")
    data[CAVE : CAVE + len(cave)] = cave
    data[SITE : SITE + 4] = hook
    print(f"[dialog-break] @{SITE:#x} -> cave @{CAVE:#x} (break at the previous space)")
    return True
