"""Restore Default on the My Camera list asks first, then unequips all but the Memory Card.

``patch_camera_restore_default`` shows the softkey (slot 3). This makes a tap
open a Yes/No dialog and, on Yes, reset the equipment. Both hooks are in the
list update ``0x002D0438`` (r4 = camera-settings operator, r6 = softkey
manager); the caves live in the dead body of ``FUN_000EA964``, which
``patch_spotpass_skip`` turns into ``bx lr`` at its first word.

Press (``ldrb r0, [r6, #0xdb]`` @ ``0x002D07C8``, Back's pressed byte): the
cave reads slot 3's pressed byte ``[r6+0x10f]`` (slot ``mgr+0x6C+3*0x34``,
+7). Unless it is set it returns Back's byte as before. On a press it opens
the game's message dialog ``FUN_00195FA4(*0x008BFA7C, layout, mode, 2, 2, 0,
0, 0, 0, 0)``, the call the album's wallpaper confirm makes (``0x002DED38``):
``r3 = 2`` is the Yes/No button set (1 is OK only), the first stack word the
window style. The handle goes to ``r4+0x4c`` (the picker's sub-state, -1
whenever the list runs; the picker sets it on entry) and ``r4+0x5d`` (padding
after the ``+0x5c`` byte, unused by the operator) marks the confirm open. It
then jumps to the list's own exit hide (``0x002D08D4``: Back, and Restore
Default through the softkey cave, and Select) and returns 0.

Poll (``ldrb r0, [r4, #0x52]`` @ ``0x002D0760``, the start of the active-list
block): with ``+0x5d`` clear it returns that byte. Otherwise it asks
``FUN_00196FF8(_, handle)``: 1 is Yes, 2 is No (also for a handle of 0, so a
dialog that failed to open cancels), anything else is still open and the
list update returns 0 without touching the list, like the wallpaper screen.

On Yes, for categories 0, 1, 2 and 4 (everything but the Memory Card, cat 3):

* ``r4[0x84 + cat*4] = -1``: the operator's equipped index (-1 = none);
* ``SetCameraEquip(cat, -1)`` @ ``0x005CFB04``: the save-data setter the
  picker's Equip confirm uses (``0x002D0F1C``), so it persists like a normal
  equip;

then ``CalcCameraStats(r4+0x68)`` @ ``0x005CDD9C`` recomputes the left-screen
values. Categories are not in screen order: cat 3 = row 0 Mem. Card,
1 = Lens, 4 = Stabilization, 2 = S. Effects, 0 = row 4 Parts.

Yes and No both clear the flag, restore ``+0x4c = -1``, drop stale softkey
presses, set ``+0x58 = -2`` so the Select softkey is re-shown for the cursor,
and set ``r4[0x50] = r4[0x51] = 1``. That is the list's return-from-picker
entry: next frame it redraws both screens and shows Back and Restore Default.

The sentence is pack ``0x1901`` slot ``table[layout] + mode`` (halfwords at
``0x006C6F5C``). The last layout, 53, starts at slot 498 and the vanilla sub
has 501 slots, so mode 3 is a new slot 501. ``append_confirm_message`` adds it
to the TRB (``tools/deploy_name_kanji_trb.py``).
"""
from __future__ import annotations

import hashlib
import struct

# Dead body of FUN_000EA964 (entry stubbed to bx lr by patch_spotpass_skip).
# The rest of the body, up to its literal pool end 0x000EAB80, belongs to
# patch_title_engpatch_info.
ADDR_STUB = 0x000EA964
STUB_PATCHED = bytes.fromhex("1eff2fe1")  # bx lr
CAVE_START = 0x000EA968
CAVE_END = 0x000EAA60
CAVE_VANILLA_SHA256 = "beb9bef8b7acef4fe94722c87f11d2b3a8f7383cc5d60d40b6ecbd36c11e9628"

HOOK_PRESS = 0x002D07C8
HOOK_PRESS_VANILLA = bytes.fromhex("db00d6e5")  # ldrb r0, [r6, #0xdb]
HOOK_POLL = 0x002D0760
HOOK_POLL_VANILLA = bytes.fromhex("5200d4e5")  # ldrb r0, [r4, #0x52]

LIST_HIDE_SOFTKEYS = 0x002D08D4  # hide Back (+ slot 3 via cave) and Select, return 0
LIST_RETURN_0 = 0x002D0914  # mov r0, #0; pop

ADDR_OPEN_DIALOG = 0x00195FA4
ADDR_DIALOG_RESULT = 0x00196FF8
DIALOG_MGR_PTR = 0x008BFA7C  # VA; *ptr is FUN_00195FA4's r0
ADDR_SET_CAMERA_EQUIP = 0x005CFB04  # (cat, item id or -1)
ADDR_CALC_CAMERA_STATS = 0x005CDD9C  # (stats = operator + 0x68)

# Sentence: pack 0x1901 slot table[layout] + mode.
ADDR_LAYOUT_TABLE = 0x006C6F5C
DIALOG_LAYOUT = 53
DIALOG_LAYOUT_BASE = 498
DIALOG_MODE = 3
DIALOG_BUTTONS_YES_NO = 2
DIALOG_STYLE = 2  # same as the wallpaper confirm
MSG_CAT = 0x19
MSG_SUB = 1
MSG_SLOT = DIALOG_LAYOUT_BASE + DIALOG_MODE  # 501
MSG_VANILLA_SLOTS = 501
CONFIRM_TEXT = (
    "Restore the defaults？\n"
    "The Lens, Stabilization,\n"
    "S. Effects and Parts\n"
    "will be unequipped.\n"
    "The Memory Card stays."
)

CAT_MEMORY_CARD = 3  # kept; the loop runs cat 4..0 and skips it


def _u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def bl(here: int, target: int, cond: int = 0xE) -> bytes:
    return _u32((cond << 28) | 0x0B000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def b(here: int, target: int, cond: int = 0xE) -> bytes:
    return _u32((cond << 28) | 0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def build_cave(base: int = CAVE_START) -> tuple[bytes, int, int]:
    """Return (blob, press entry, poll entry)."""
    code = bytearray()
    fixups: list[tuple[int, str, int]] = []  # (offset, label, cond)
    labels: dict[str, int] = {}

    def here() -> int:
        return base + len(code)

    def op(word: int) -> None:
        code.extend(_u32(word))

    def call(target: int) -> None:
        code.extend(bl(here(), target))

    def jump(target: int, cond: int = 0xE) -> None:
        code.extend(b(here(), target, cond))

    def jump_label(label: str, cond: int = 0xE) -> None:
        fixups.append((len(code), label, cond))
        op(0)

    # Press: replaces ldrb r0, [r6, #0xdb]; returns Back's byte when slot 3 is idle.
    press = here()
    op(0xE5D6010F)  # ldrb r0, [r6, #0x10f]  (slot 3 pressed)
    op(0xE3500000)  # cmp r0, #0
    op(0x05D600DB)  # ldrbeq r0, [r6, #0xdb]
    op(0x012FFF1E)  # bxeq lr
    op(0xE3A00000)  # mov r0, #0
    op(0xE5C6010F)  # strb r0, [r6, #0x10f]
    op(0xE3A01000)  # mov r1, #0
    op(0xE52D1004)  # str r1, [sp, #-4]!  (alt-table flag = 0)
    op(0xE3A00000 | DIALOG_STYLE)  # mov r0, #style
    op(0xE3A02000)  # mov r2, #0
    op(0xE3A03000)  # mov r3, #0
    op(0xE3A0C000)  # mov ip, #0
    op(0xE92D100F)  # push {r0-r3, ip}  (style, then four empty params)
    lit_at = len(code)
    op(0)  # ldr r0, =DIALOG_MGR_PTR (patched below)
    op(0xE5900000)  # ldr r0, [r0]
    op(0xE3A01000 | DIALOG_LAYOUT)  # mov r1, #layout
    op(0xE3A02000 | DIALOG_MODE)  # mov r2, #mode
    op(0xE3A03000 | DIALOG_BUTTONS_YES_NO)  # mov r3, #2
    call(ADDR_OPEN_DIALOG)
    op(0xE28DD018)  # add sp, sp, #0x18
    op(0xE584004C)  # str r0, [r4, #0x4c]  (handle)
    op(0xE3A00001)  # mov r0, #1
    op(0xE5C4005D)  # strb r0, [r4, #0x5d]  (confirm open)
    jump(LIST_HIDE_SOFTKEYS)

    # Poll: replaces ldrb r0, [r4, #0x52].
    poll = here()
    op(0xE5D4005D)  # ldrb r0, [r4, #0x5d]
    op(0xE3500000)  # cmp r0, #0
    op(0x05D40052)  # ldrbeq r0, [r4, #0x52]
    op(0x012FFF1E)  # bxeq lr
    op(0xE594104C)  # ldr r1, [r4, #0x4c]
    call(ADDR_DIALOG_RESULT)
    op(0xE3500001)  # cmp r0, #1
    jump_label("yes", cond=0x0)  # beq yes
    op(0xE3500002)  # cmp r0, #2
    jump(LIST_RETURN_0, cond=0x1)  # bne: still open
    labels["done"] = len(code)
    op(0xE3A00000)  # mov r0, #0
    op(0xE5C4005D)  # strb r0, [r4, #0x5d]
    op(0xE5C600DB)  # strb r0, [r6, #0xdb]   (Back)
    op(0xE5C6010F)  # strb r0, [r6, #0x10f]  (Restore Default)
    op(0xE5C60143)  # strb r0, [r6, #0x143]  (Select)
    op(0xE3E00000)  # mvn r0, #0
    op(0xE584004C)  # str r0, [r4, #0x4c]  (picker sub-state idle)
    op(0xE2400001)  # sub r0, r0, #1
    op(0xE5840058)  # str r0, [r4, #0x58]  (-2: re-show Select for the cursor)
    op(0xE3A00001)  # mov r0, #1
    op(0xE5C40050)  # strb r0, [r4, #0x50]
    op(0xE5C40051)  # strb r0, [r4, #0x51]
    jump(LIST_RETURN_0)

    labels["yes"] = len(code)
    op(0xE3A05004)  # mov r5, #4  (r5 is saved by the list update)
    loop = here()
    op(0xE3550000 | CAT_MEMORY_CARD)  # cmp r5, #3
    jump_label("next", cond=0x0)  # beq next
    op(0xE3E01000)  # mvn r1, #0
    op(0xE0840105)  # add r0, r4, r5, lsl #2
    op(0xE5801084)  # str r1, [r0, #0x84]
    op(0xE1A00005)  # mov r0, r5
    call(ADDR_SET_CAMERA_EQUIP)
    labels["next"] = len(code)
    op(0xE2555001)  # subs r5, r5, #1
    jump(loop, cond=0x5)  # bpl loop (cat 0 included)
    op(0xE2840068)  # add r0, r4, #0x68
    call(ADDR_CALC_CAMERA_STATS)
    jump_label("done")

    lit = len(code)
    op(DIALOG_MGR_PTR)
    code[lit_at : lit_at + 4] = _u32(0xE59F0000 | (lit - lit_at - 8))  # ldr r0, [pc, #imm]
    for at, label, cond in fixups:
        code[at : at + 4] = b(base + at, base + labels[label], cond)
    return bytes(code), press, poll


def build_region() -> tuple[bytes, int, int]:
    """Cave blob NOP-padded to the dead body."""
    blob, press, poll = build_cave()
    size = CAVE_END - CAVE_START
    if len(blob) > size:
        raise ValueError(f"camera reset cave {len(blob)} > {size}")
    return blob + _u32(0xE320F000) * ((size - len(blob)) // 4), press, poll


def is_patched(data: bytes) -> bool:
    region, press, poll = build_region()
    return (
        data[CAVE_START:CAVE_END] == region
        and data[HOOK_PRESS : HOOK_PRESS + 4] == bl(HOOK_PRESS, press)
        and data[HOOK_POLL : HOOK_POLL + 4] == bl(HOOK_POLL, poll)
    )


def apply_patch(data: bytearray) -> bool:
    region, press, poll = build_region()
    if is_patched(data):
        print(f"[camera-reset] already applied @{CAVE_START:#x}")
        return False
    if data[ADDR_STUB : ADDR_STUB + 4] != STUB_PATCHED:
        raise ValueError(f"{ADDR_STUB:#x} is not bx lr; apply patch_spotpass_skip first")
    got = hashlib.sha256(bytes(data[CAVE_START:CAVE_END])).hexdigest()
    if got != CAVE_VANILLA_SHA256:
        raise ValueError(f"dead body @{CAVE_START:#x} is not vanilla")
    for addr, vanilla in ((HOOK_PRESS, HOOK_PRESS_VANILLA), (HOOK_POLL, HOOK_POLL_VANILLA)):
        if data[addr : addr + 4] != vanilla:
            raise ValueError(f"unexpected insn @{addr:#x}: {data[addr:addr+4].hex()}")
    base = struct.unpack_from("<H", data, ADDR_LAYOUT_TABLE + 2 * DIALOG_LAYOUT)[0]
    if base != DIALOG_LAYOUT_BASE:
        raise ValueError(f"dialog layout {DIALOG_LAYOUT} starts at slot {base}, not {DIALOG_LAYOUT_BASE}")
    data[CAVE_START:CAVE_END] = region
    data[HOOK_PRESS : HOOK_PRESS + 4] = bl(HOOK_PRESS, press)
    data[HOOK_POLL : HOOK_POLL + 4] = bl(HOOK_POLL, poll)
    print(
        f"[camera-reset] Restore Default confirm: press @{HOOK_PRESS:#x} -> {press:#x}, "
        f"poll @{HOOK_POLL:#x} -> {poll:#x}"
    )
    return True


def append_confirm_message(data: bytes) -> tuple[bytes, list[str]]:
    """Add pack 0x1901 slot 501 (the confirm sentence) to a TRB."""
    return append_message_slot(data, MSG_SLOT, CONFIRM_TEXT, "Restore Default confirm")


def append_message_slot(data: bytes, slot: int, text: str, label: str) -> tuple[bytes, list[str]]:
    """Add ``slot`` to the end of pack 0x1901 sub 1, which must hold ``slot`` slots.

    The new slot's u16 goes at the end of the sub's list with a u16 pad, so
    every later offset in INDX moves by 4 and keeps its alignment. A TRB that
    already holds ``text`` there is returned unchanged.
    """
    from patch_password_serials import _pack_trb, _strb_used, _sub_u16_off
    from patch_textresource import iter_entries, parse_chunks, to_game_newlines

    chunks = parse_chunks(data)
    stri = bytearray(chunks["STRI"])
    strb = bytearray(chunks["STRB"])
    indx = bytearray(chunks["INDX"])
    u16_off, count = _sub_u16_off(indx, MSG_CAT, MSG_SUB)
    payload = to_game_newlines(text).encode("utf-8")
    if count > slot:
        cur = struct.unpack_from("<H", indx, u16_off + 2 * slot)[0]
        start = struct.unpack_from("<I", stri, cur * 8)[0]
        if bytes(strb[start : start + len(payload) + 1]) == payload + b"\x00":
            return data, [f"slot {slot} already set"]
        raise ValueError(f"pack 0x{MSG_CAT:02x}{MSG_SUB:02x} slot {slot} holds other text")
    if count != slot:
        raise ValueError(f"pack 0x{MSG_CAT:02x}{MSG_SUB:02x} has {count} slots, expected {slot}")

    new_idx = sum(1 for _ in iter_entries(stri))
    strb = strb[: _strb_used(stri, strb)]
    stri += struct.pack("<IHH", len(strb), len(payload), 1)
    strb += payload + b"\x00"
    strb += b"\xc9" * ((4 - len(strb) % 4) % 4)

    insert_at = u16_off + 2 * count
    cat_off = struct.unpack_from("<I", indx, MSG_CAT * 4)[0]
    sub_rel = struct.unpack_from("<I", indx, cat_off + 4 + MSG_SUB * 4)[0]
    sub_count = struct.unpack_from("<I", indx, cat_off)[0]
    for s in range(sub_count):
        at = cat_off + 4 + s * 4
        rel = struct.unpack_from("<I", indx, at)[0]
        if rel > sub_rel:
            struct.pack_into("<I", indx, at, rel + 4)
    for c in range(0x100):
        off = struct.unpack_from("<I", indx, c * 4)[0]
        if off > cat_off:
            struct.pack_into("<I", indx, c * 4, off + 4)
    struct.pack_into("<I", indx, u16_off - 4, count + 1)
    indx[insert_at:insert_at] = struct.pack("<HH", new_idx, 0)

    chunks["STRI"] = bytes(stri)
    chunks["STRB"] = bytes(strb)
    chunks["INDX"] = bytes(indx)
    return _pack_trb(chunks), [f"slot {slot} -> stri={new_idx} ({label})"]
