"""Show the Restore Default softkey on the My Camera equipment list.

The camera UI drives the shared Common02Icon softkey manager through
``SetSoftkey(mgr, slot, on)`` @ ``0x001F5A9C``. Its five slots are built at
``0x001F637C`` from the name table at ``0x006C1AF0`` (stride 0x24):

  0 ``t``  1 ``k``  2 ``m`` (Back)  3 ``Sy`` (Restore Default)  4 ``s`` (Select)

Slot 3 is ``Pos_C_icon_Sy`` / ``Pos_C_icon_hSy`` with ``C_Com_icon_Sy``
(already EN in the bake). The equipment-list update ``0x002D0438`` shows Back
on entry (``0x002D0564``) and hides it on exit (``0x002D08E0``); it never
touches slot 3. Both calls go through a cave that makes the same call for
slot 3, so Restore Default appears and goes with Back.

Where it is drawn: ``SetSoftkey`` only toggles visibility. Every frame the
manager puts the slot's ``Pos_C_icon_Sy`` pane at ``slot+0xC`` plus the slide
offset (``SetSlotOffset`` @ ``0x001F5D3C``). The hold-angle setter
(``0x001F60A0``, virtual) fills ``slot+0xC`` from the saved layout spot of
``Pos_C_icon_Sy`` (``slot+0x18``) or, held sideways, ``Pos_C_icon_hSy``
(``slot+0x24``); those are read from the layout once at ``0x001F5564``.
So moving the layout pane at runtime does nothing. Slot ``i`` is at
``mgr + 0x6C + i*0x34``, so slot 3's ``+0xC`` / ``+0x24`` are ``mgr+0x114`` /
``mgr+0x12C``.

The vanilla sideways spot (87, -97) overlaps the Mem. Card row. Before the
slot-3 call the cave writes (121, -85), up against the header like the
mockup, to both, and on hide it writes (87, -97) back, because another
screen's softkey set shows slot 3 too (the ``0x0068xxxx`` callers).

Display only: nothing reads a slot-3 press on this screen yet.
"""
from __future__ import annotations

import struct

from patch_input_cave_map import ADDR_CAMERA_DEFAULTS_CAVE, CAMERA_DEFAULTS_CAVE_LEN

ADDR_SET_SOFTKEY = 0x001F5A9C
SLOT3_BASE = 0x6C + 3 * 0x34  # slot 3 inside the manager
OFF_ACTIVE_POS = SLOT3_BASE + 0x0C  # drawn base (x, y, z)
OFF_HOLD_POS = SLOT3_BASE + 0x24  # saved Pos_C_icon_hSy spot (x, y, z)
SLOT_BACK = 2
SLOT_DEFAULTS = 3
VANILLA_POS = (87.0, -97.0)
CAMERA_POS = (121.0, -85.0)

# bl SetSoftkey(mgr, 2, on) in the equipment-list update.
SITES: tuple[tuple[int, str], ...] = (
    (0x002D0564, "show"),
    (0x002D08E0, "hide"),
)


def _u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def bl(here: int, target: int) -> bytes:
    return _u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _str_r4(rt: int, off: int) -> int:
    return 0xE5840000 | (rt << 12) | off  # str rt, [r4, #off]


def build_cave(cave: int = ADDR_CAMERA_DEFAULTS_CAVE) -> bytes:
    """Set slot 3's spot for ``on``; SetSoftkey(mgr, 2, on); SetSoftkey(mgr, 3, on)."""
    code = bytearray()

    def op(word: int) -> None:
        code.extend(_u32(word))

    op(0xE92D4070)  # push {r4, r5, r6, lr}
    op(0xE1A04000)  # mov r4, r0  (mgr; r1 is still slot 2)
    op(0xE1A05002)  # mov r5, r2  (on: 0 / 1)
    adr_at = len(code)
    op(0)  # add r3, pc, #table (patched below)
    op(0xE0833185)  # add r3, r3, r5, lsl #3
    op(0xE8930000 | (1 << 2) | (1 << 3))  # ldm r3, {r2, r3}  (x, y)
    op(_str_r4(2, OFF_ACTIVE_POS))
    op(_str_r4(3, OFF_ACTIVE_POS + 4))
    op(_str_r4(2, OFF_HOLD_POS))
    op(_str_r4(3, OFF_HOLD_POS + 4))
    op(0xE1A00004)  # mov r0, r4
    op(0xE1A02005)  # mov r2, r5
    code.extend(bl(cave + len(code), ADDR_SET_SOFTKEY))
    op(0xE1A00004)  # mov r0, r4
    op(0xE3A01000 | SLOT_DEFAULTS)  # mov r1, #3
    op(0xE1A02005)  # mov r2, r5
    op(0xE8BD4070)  # pop {r4, r5, r6, lr}
    code.extend(_u32(0xEA000000 | (((ADDR_SET_SOFTKEY - (cave + len(code)) - 8) >> 2) & 0xFFFFFF)))
    table = len(code)
    code.extend(struct.pack("<4f", *VANILLA_POS, *CAMERA_POS))
    struct.pack_into("<I", code, adr_at, 0xE28F3000 | (table - adr_at - 8))
    if len(code) > CAMERA_DEFAULTS_CAVE_LEN:
        raise ValueError(f"camera defaults cave {len(code)} > {CAMERA_DEFAULTS_CAVE_LEN}")
    return bytes(code)


def is_patched(data: bytes) -> bool:
    return all(
        data[site : site + 4] == bl(site, ADDR_CAMERA_DEFAULTS_CAVE) for site, _ in SITES
    )


def apply_patch(data: bytearray) -> bool:
    cave = build_cave()
    if is_patched(data):
        if data[ADDR_CAMERA_DEFAULTS_CAVE : ADDR_CAMERA_DEFAULTS_CAVE + len(cave)] != cave:
            raise ValueError("camera defaults sites patched but cave bytes differ")
        print(f"[camera-defaults] already applied @{ADDR_CAMERA_DEFAULTS_CAVE:#x}")
        return False
    for site, _ in SITES:
        if data[site : site + 4] != bl(site, ADDR_SET_SOFTKEY):
            raise ValueError(f"unexpected insn @{site:#x}: {data[site:site+4].hex()}")
    region = data[ADDR_CAMERA_DEFAULTS_CAVE : ADDR_CAMERA_DEFAULTS_CAVE + len(cave)]
    if region != b"\x00" * len(cave):
        raise ValueError(
            f"cave @{ADDR_CAMERA_DEFAULTS_CAVE:#x} not empty: {region[:8].hex()}"
        )
    data[ADDR_CAMERA_DEFAULTS_CAVE : ADDR_CAMERA_DEFAULTS_CAVE + len(cave)] = cave
    for site, _ in SITES:
        data[site : site + 4] = bl(site, ADDR_CAMERA_DEFAULTS_CAVE)
    print(
        f"[camera-defaults] Back softkey @{', '.join(f'{s:#x}' for s, _ in SITES)} "
        f"-> cave @{ADDR_CAMERA_DEFAULTS_CAVE:#x} (also slot {SLOT_DEFAULTS})"
    )
    return True
