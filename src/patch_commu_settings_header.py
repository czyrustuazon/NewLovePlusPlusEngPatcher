#!/usr/bin/env python3
"""Draw "Communication Settings" into the communication-settings header pane.

The white bar on Communication Settings is Tex_Font_00 (176x14) on the
MultiWin, not the ETC1A4 strip. Com_MultiWin_W01_Text04_04_00 is already
the English label and is not the line in the crop (vanilla of that strip
is the debug text "NETWORK OPTION"). State 2 of CommunicationOptionUIOperator
(file 0x10efdc) binds that strip and draws the help paragraph, and never
fills the header pane. This stub does, once, as the screen opens.

Cave sits in the last RX page, after the name-input caves.
"""
from __future__ import annotations

import struct

from patch_input_cave_map import ADDR_COMMU_HEADER_CAVE, COMMU_HEADER_CAVE_LEN

SITE = 0x0010F130  # mov r0, #3  — r7 is still the MultiWin
RESUME = 0x0010F134
ADDR_SET_HEADER = 0x00255764  # FUN_00255764(window, cstring) -> pane +0x60
TITLE = b"Communication Settings\x00"

VANILLA_SITE = bytes.fromhex("0300a0e3")  # mov r0, #3


def _u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def _b(here: int, target: int) -> bytes:
    imm = ((target - here - 8) >> 2) & 0xFFFFFF
    return _u32(0xEA000000 | imm)


def bl(here: int, target: int) -> bytes:
    imm = ((target - here - 8) >> 2) & 0xFFFFFF
    return _u32(0xEB000000 | imm)


def build_cave(cave: int = ADDR_COMMU_HEADER_CAVE) -> bytes:
    """mov r0, r7; add r1, pc, #8; bl set_header; mov r0, #3; b resume; title."""
    code = bytearray()
    code += _u32(0xE1A00007)  # mov r0, r7
    code += _u32(0xE28F1008)  # add r1, pc, #8  -> title at cave+20
    code += bl(cave + 8, ADDR_SET_HEADER)
    code += _u32(0xE3A00003)  # mov r0, #3
    code += _b(cave + 16, RESUME)
    if len(code) != 20:
        raise ValueError(f"header stub {len(code)} != 20")
    blob = bytes(code) + TITLE
    if len(blob) > COMMU_HEADER_CAVE_LEN:
        raise ValueError(f"header cave {len(blob)} > {COMMU_HEADER_CAVE_LEN}")
    return blob


def is_patched(data: bytes) -> bool:
    return data[SITE : SITE + 4] == bl(SITE, ADDR_COMMU_HEADER_CAVE)


def apply_patch(data: bytearray) -> bool:
    cave = build_cave()
    if is_patched(data):
        if data[ADDR_COMMU_HEADER_CAVE : ADDR_COMMU_HEADER_CAVE + len(cave)] != cave:
            raise ValueError("commu header site patched but cave bytes differ")
        print(f"[commu-header] already applied @{ADDR_COMMU_HEADER_CAVE:#x}")
        return False
    if data[SITE : SITE + 4] != VANILLA_SITE:
        raise ValueError(f"unexpected insn @{SITE:#x}: {data[SITE:SITE+4].hex()}")
    region = data[ADDR_COMMU_HEADER_CAVE : ADDR_COMMU_HEADER_CAVE + len(cave)]
    if region != b"\x00" * len(cave):
        raise ValueError(
            f"cave @{ADDR_COMMU_HEADER_CAVE:#x} not empty: {region[:8].hex()}"
        )
    data[ADDR_COMMU_HEADER_CAVE : ADDR_COMMU_HEADER_CAVE + len(cave)] = cave
    data[SITE : SITE + 4] = bl(SITE, ADDR_COMMU_HEADER_CAVE)
    print(
        f"[commu-header] @{SITE:#x} -> cave @{ADDR_COMMU_HEADER_CAVE:#x} "
        f"({TITLE.decode().rstrip(chr(0))!r})"
    )
    return True
