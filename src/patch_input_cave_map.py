"""Name-input codecave placement (must be inside .text RX pages).

NLPP ExeFS CodeSetInfo (exheader):

  .text  VA 0x00100000 .. 0x00790000  (file 0x00000000 .. 0x00690000)  RX
  .ro    VA 0x00790000 .. 0x00889000  (file 0x00690000 .. 0x00789000)  R, no-X
  .data  VA 0x00889000 .. 0x008C0000                                RW

Azahar maps the whole decompressed code.bin executable, so caves in .rodata
work in emulator. On a real 3DS those same addresses prefetch-abort
(Permission-Page) — Luma dump PC 0x007E6A78 = old shared pad 0x006E6A38+0x40.

Use the last .text page's unused tail (after Text.size 0x0068F7FC, still RX).
"""
from __future__ import annotations

# File offsets (Ghidra base 0). VA = file + 0x100000.
TEXT_PAGE_END = 0x00690000
TEXT_SIZE = 0x0068F7FC

# 2 KiB zero pad at the end of the last RX page.
ADDR_SHARED_PAD = 0x0068F800
ADDR_ROMAJI_CAVE = 0x0068F900

# Historical pads in .rodata — never execute from these on hardware.
OLD_RODATA_SHARED_PAD = 0x006E6A38
OLD_RODATA_ROMAJI_CAVE = 0x006FBB08
