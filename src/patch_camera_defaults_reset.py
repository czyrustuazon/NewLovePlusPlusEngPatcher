"""Restore Default on the My Camera list unequips everything but the Memory Card.

``patch_camera_restore_default`` shows the softkey (slot 3). This makes a tap
do something. In the list update ``0x002D0438`` (r4 = camera-settings
operator, r6 = softkey manager) the Back check
``ldrb r0, [r6, #0xdb]`` @ ``0x002D07C8`` becomes ``bl`` to a cave. The cave
reads slot 3's pressed byte ``[r6+0x10f]`` (slot ``mgr+0x6C+3*0x34``, +7;
Back is ``+0xdb``). Unless it is set, the cave returns Back's byte as before.

Categories (``r4[0x84 + cat*4]``) are not in screen order. The row setters
(``0x001E380C(list, row, text)``) give: cat 3 = row 0 Mem. Card, cat 1 =
Lens, cat 4 = Stabilization, cat 2 = S. Effects, cat 0 = row 4 Parts. The
picker's cursor map (``0x002D0848``) agrees and never offers cat 3.

On a press, for categories 0, 1, 2 and 4 (everything but the Memory Card):

* ``r4[0x84 + cat*4] = -1``: the operator's equipped index (-1 = none,
  the list draws an empty row);
* ``SetCameraEquip(cat, -1)`` @ ``0x005CFB04``: the save-data setter the
  picker's Equip confirm uses (``0x002D0F1C``). It ends in ``0x002E1094``,
  which stores the item id at ``save+0xC+cat*2`` and clears the category's
  bit in ``save+0x59`` for -1, so it persists like a normal equip;

then ``CalcCameraStats(r4+0x68)`` @ ``0x005CDD9C`` recomputes the left-screen
values (shots, zoom, stabilize, stealth, part effect, preview) from the new
indices. Last it sets ``r4[0x50] = r4[0x51] = 1``. That is the list's
return-from-picker entry, so the next frame redraws both screens.

Room: the list draws its five row names (``0x002D0628``-``0x002D074C``) as
five unrolled if/else blocks with NOP pairs. They are rewritten here as five
straight blocks using conditional adds (same calls, same arguments). That
frees the tail of the region for the cave; a ``b`` skips over it.
"""
from __future__ import annotations

import hashlib
import struct

REGION_START = 0x002D0628
REGION_END = 0x002D0750  # first insn after the row-name blocks (strb sb, [r4, #0x50])
REGION_VANILLA_SHA256 = "db67e0b0289cb2979a431ebd94275e75f80589bd833ac7e61280b13c8bd1f2df"
EMPTY_STRING = 0x002D0990  # zero word after the function's literal pool

HOOK = 0x002D07C8
HOOK_VANILLA = bytes.fromhex("db00d6e5")  # ldrb r0, [r6, #0xdb]

ADDR_SET_CAMERA_EQUIP = 0x005CFB04  # (cat, item id or -1)
ADDR_CALC_CAMERA_STATS = 0x005CDD9C  # (stats = operator + 0x68)

# (operator field, name offset in the operator, draw function) in list order.
ROWS: tuple[tuple[int, int, int], ...] = (
    (0x84, 0x0AE, 0x001E3800),  # cat 0 -> row 4 Parts
    (0x88, 0x618, 0x001E3698),  # cat 1 -> row 1 Lens
    (0x90, 0x10EC, 0x001E368C),  # cat 3 -> row 0 Mem. Card
    (0x94, 0x1656, 0x001E3A28),  # cat 4 -> row 2 Stabilization
    (0x8C, 0xB82, 0x001E3A00),  # cat 2 -> row 3 S. Effects
)
CAT_MEMORY_CARD = 3  # kept; the loop runs cat 4..0 and skips it
NOP = 0xE320F000


def _u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def bl(here: int, target: int, cond: int = 0xE) -> bytes:
    return _u32((cond << 28) | 0x0B000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def b(here: int, target: int, cond: int = 0xE) -> bytes:
    return _u32((cond << 28) | 0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _imm12(value: int) -> int:
    """ARM data-processing immediate (8 bits rotated right by an even amount)."""
    for rot in range(16):
        v = ((value << (2 * rot)) | (value >> (32 - 2 * rot))) & 0xFFFFFFFF
        if v < 0x100:
            return (rot << 8) | v
    raise ValueError(f"{value:#x} is not an ARM immediate")


def _split_imm(value: int) -> list[int]:
    """One or two ARM immediates that add up to ``value``."""
    try:
        _imm12(value)
        return [value]
    except ValueError:
        hi = value & ~0xFF
        _imm12(hi)
        _imm12(value & 0xFF)
        return [hi, value & 0xFF]


def build_rows(base: int = REGION_START) -> bytes:
    """Five row-name draws: r1 = idx == -1 ? "" : name; FN(r7, r1)."""
    code = bytearray()

    def op(word: int) -> None:
        code.extend(_u32(word))

    for field, name_off, fn in ROWS:
        here = base + len(code)
        op(0xE5940000 | field)  # ldr r0, [r4, #field]
        op(0xE28F1000 | _imm12(EMPTY_STRING - (base + len(code)) - 8))  # add r1, pc, #""
        op(0xE3700001)  # cmn r0, #1
        op(0x10800280)  # addne r0, r0, r0, lsl #5  (idx * 33)
        op(0x10840080)  # addne r0, r4, r0, lsl #1  (operator + idx * 66)
        parts = _split_imm(name_off)
        op(0x12801000 | _imm12(parts[0]))  # addne r1, r0, #hi
        for extra in parts[1:]:
            op(0x12811000 | _imm12(extra))  # addne r1, r1, #lo
        op(0xE1A00007)  # mov r0, r7
        code.extend(bl(base + len(code), fn))
        del here
    return bytes(code)


def build_reset(base: int) -> bytes:
    """Hooked over ``ldrb r0, [r6, #0xdb]``; returns Back's pressed byte in r0."""
    code = bytearray()

    def op(word: int) -> None:
        code.extend(_u32(word))

    op(0xE5D6010F)  # ldrb r0, [r6, #0x10f]  (slot 3 pressed)
    op(0xE3500000)  # cmp r0, #0
    op(0x05D600DB)  # ldrbeq r0, [r6, #0xdb]
    op(0x012FFF1E)  # bxeq lr
    op(0xE92D4020)  # push {r5, lr}
    op(0xE3A00000)  # mov r0, #0
    op(0xE5C6010F)  # strb r0, [r6, #0x10f]
    op(0xE3A05004)  # mov r5, #4
    loop = len(code)
    op(0xE3550000 | CAT_MEMORY_CARD)  # cmp r5, #3
    skip_at = len(code)
    op(0)  # beq next (patched below)
    op(0xE3E01000)  # mvn r1, #0
    op(0xE0840105)  # add r0, r4, r5, lsl #2
    op(0xE5801084)  # str r1, [r0, #0x84]
    op(0xE1A00005)  # mov r0, r5
    code.extend(bl(base + len(code), ADDR_SET_CAMERA_EQUIP))
    nxt = len(code)
    op(0xE2555001)  # subs r5, r5, #1
    code.extend(b(base + len(code), base + loop, cond=0x5))  # bpl loop (0 included)
    code[skip_at : skip_at + 4] = b(base + skip_at, base + nxt, cond=0x0)  # beq next
    op(0xE2840068)  # add r0, r4, #0x68
    code.extend(bl(base + len(code), ADDR_CALC_CAMERA_STATS))
    op(0xE3A00001)  # mov r0, #1
    op(0xE5C40050)  # strb r0, [r4, #0x50]
    op(0xE5C40051)  # strb r0, [r4, #0x51]
    op(0xE5D600DB)  # ldrb r0, [r6, #0xdb]
    op(0xE8BD8020)  # pop {r5, pc}
    return bytes(code)


def build_region() -> tuple[bytes, int]:
    """Rows + ``b REGION_END`` + reset cave, NOP-padded to the region size."""
    rows = build_rows()
    skip_at = REGION_START + len(rows)
    blob = bytearray(rows)
    blob += b(skip_at, REGION_END)
    reset_at = REGION_START + len(blob)
    blob += build_reset(reset_at)
    size = REGION_END - REGION_START
    if len(blob) > size:
        raise ValueError(f"rows + reset {len(blob)} > region {size}")
    while len(blob) < size:
        blob += _u32(NOP)
    return bytes(blob), reset_at


def is_patched(data: bytes) -> bool:
    region, reset_at = build_region()
    return (
        data[REGION_START:REGION_END] == region
        and data[HOOK : HOOK + 4] == bl(HOOK, reset_at)
    )


def apply_patch(data: bytearray) -> bool:
    region, reset_at = build_region()
    if is_patched(data):
        print(f"[camera-reset] already applied @{reset_at:#x}")
        return False
    got = hashlib.sha256(bytes(data[REGION_START:REGION_END])).hexdigest()
    if got != REGION_VANILLA_SHA256:
        raise ValueError(f"camera row-name region @{REGION_START:#x} is not vanilla")
    if data[HOOK : HOOK + 4] != HOOK_VANILLA:
        raise ValueError(f"unexpected insn @{HOOK:#x}: {data[HOOK:HOOK+4].hex()}")
    data[REGION_START:REGION_END] = region
    data[HOOK : HOOK + 4] = bl(HOOK, reset_at)
    print(
        f"[camera-reset] Restore Default press @{HOOK:#x} -> cave @{reset_at:#x} "
        f"(rows compacted in {REGION_START:#x}..{REGION_END:#x})"
    )
    return True
