#!/usr/bin/env python3
"""Kanji candidates via B_Place overlay (slot 0x1E) with touch routing.

SHOW alone draws on 0x1E but UIWindowMgr_TouchHitDispatch (0x5c6eec) only
tests slots whose bit is set in mgr+0x100. That bitmask is not updated by
SHOW, so taps fall through to the ML underlay (NameInput_OnCellTap).

After SHOW+fill: OR (1<<0x1E) into mgr+0x100 and BIC the name-input slot
bit so Bod_BP rows win hit-test. vtable+0x28 → select_hook matches
Bod_BP%02d and copies the row into name+0x46 (does NOT call vanilla
BPlace_OnRowSelect — its Pos_W_SCur04 BindByKey ClearPane(NULL) crashes
without the hometown companion on slot 7).

Do NOT steal hometown slot 1 / 7 or hook ProfileField_TickPoller.

Cave: @0x006FC000 (after romaji @0x006FBB08). Not 0x006E6A38 (§17 stack).

Rollback: restore exefs/code.bin.bak_pre_bplace_list.
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

BL_SITE = 0x001FB150
LAB_SITE = 0x001FAFF0
ADDR_FILL = 0x001FB438
ADDR_GOJUON = 0x001FA81C
ADDR_BP_SELECT = 0x0023CD8C
ADDR_BP_GET = 0x0023D790
ADDR_SHOW = 0x005C52D8
ADDR_CLOSE = 0x005C5AD8
ADDR_GET_INST = 0x005C5CB0
ADDR_CLEAR = 0x0054B5FC
ADDR_MAKE_STR = 0x005A1EC8
ADDR_DRAW = 0x0054B880
ADDR_FREE_STR = 0x005A2024
ADDR_MEMCPY7 = 0x000317DC
ADDR_LOOKUP = 0x005C0D4C
ADDR_SPRINTF = 0x00000200
ADDR_STRCMP = 0x001FE040
# UIWindowMgr_Close uses this to drop a layout from the parent display list
# *before* destroying panes — safer than Close or nulling slot ptrs first.
ADDR_SCENE_UNLINK = 0x005E8CA4  # UILayout_UnlinkFromParent
ADDR_GET_LAYOUT = 0x005C6E84  # layout* for (mgr, bank, slot)
ADDR_DELEGATE_INIT = 0x005E828C
ADDR_BIND = 0x005EBA00  # Delegate_BindByKey
ADDR_PANE_SETVIS = 0x005E7D18  # pane +0xb7 visible bit
STR_BOD_BP = 0x0023CEB0  # "Bod_BP%02d"
STR_POS_WIN_BP = 0x0073DBC5  # "Pos_Win_BP"

DAT_UI_MGR = 0x007BFA40
VT_BP_TOUCH = 0x00713CD0  # B_Place vtable +0x28

ADDR_CAVE = 0x006FC000
CAVE_ALIGN = ADDR_CAVE
CAVE_MAX = 0x580

SLOT = 0x1E
SLOT_BIT = 1 << SLOT  # 0x40000000
VISIBLE = 8
BP_NAME_STASH = 0x234  # unused on B_Place object; holds nameInputObj*

# Bruteforce dismiss ladder (bump and redeploy):
# 0 = copy + touch bit restore only (known-good insert; list stays)
# 1 = soft-unlink (null slot ptrs) + RedrawKeyboard (crashed)
# 2 = UIWindowMgr_Close + RedrawKeyboard (crashed)
# 3 = UILayout_UnlinkFromParent + RedrawKeyboard (crashed)
# 4 = ClearPane all Tex_BP + touch off (blanked; random taps crashed)
# 5 = hide Pos_Win_BP + touch off (list vanished, then ClearPane crash lr=0x64B734)
# 6 = mode 5 + RedrawKeyboard (not tested)
DISMISS_MODE = 0


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def mov_imm(rd: int, imm: int) -> bytes:
    assert 0 <= imm <= 0xFF
    return u32(0xE3A00000 | (rd << 12) | imm)


def mov_reg(rd: int, rm: int) -> bytes:
    return u32(0xE1A00000 | (rd << 12) | rm)


def ldr_imm(rd: int, rn: int, imm: int) -> bytes:
    assert 0 <= imm < 0x1000
    return u32(0xE5900000 | (rn << 16) | (rd << 12) | imm)


def str_imm(rd: int, rn: int, imm: int) -> bytes:
    assert 0 <= imm < 0x1000
    return u32(0xE5800000 | (rn << 16) | (rd << 12) | imm)


def ldrb_imm(rd: int, rn: int, imm: int) -> bytes:
    assert 0 <= imm < 0x1000
    return u32(0xE5D00000 | (rn << 16) | (rd << 12) | imm)


def strb_imm(rd: int, rn: int, imm: int) -> bytes:
    assert 0 <= imm < 0x1000
    return u32(0xE5C00000 | (rn << 16) | (rd << 12) | imm)


def encode_imm12(value: int) -> int:
    value &= 0xFFFFFFFF
    for rot in range(16):
        imm8 = (
            value
            if rot == 0
            else ((value << (rot * 2)) | (value >> (32 - rot * 2))) & 0xFFFFFFFF
        )
        if imm8 <= 0xFF:
            got = (
                imm8
                if rot == 0
                else ((imm8 >> (rot * 2)) | (imm8 << (32 - rot * 2))) & 0xFFFFFFFF
            )
            if got == value:
                return (rot << 8) | imm8
    raise ValueError(f"cannot encode imm {value:#x}")


def add_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE2800000 | (rn << 16) | (rd << 12) | encode_imm12(imm))


def sub_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE2400000 | (rn << 16) | (rd << 12) | encode_imm12(imm))


def ldrh_imm(rd: int, rn: int, imm: int) -> bytes:
    assert 0 <= imm <= 0xFF
    return u32(
        0xE1D000B0
        | (rn << 16)
        | (rd << 12)
        | ((imm & 0xF0) << 4)
        | (imm & 0x0F)
    )


def add_reg(rd: int, rn: int, rm: int, shift: int = 0) -> bytes:
    return u32(0xE0800000 | (rn << 16) | (rd << 12) | (shift << 7) | rm)


def push(mask: int) -> bytes:
    return u32(0xE92D0000 | mask)


def pop(mask: int) -> bytes:
    return u32(0xE8BD0000 | mask)


def bl(here: int, target: int) -> bytes:
    return u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def blx(here: int, target: int) -> bytes:
    """ARM→Thumb interworking (e.g. sprintf @0x200)."""
    offset = target - (here + 8)
    assert offset % 2 == 0, (hex(here), hex(target), offset)
    h = (offset >> 1) & 1
    imm24 = (offset >> 2) & 0xFFFFFF
    return u32(0xFA000000 | (h << 24) | imm24)


def b(here: int, target: int) -> bytes:
    return u32(0xEA000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def beq(here: int, target: int) -> bytes:
    return u32(0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def bne(here: int, target: int) -> bytes:
    return u32(0x1A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def bge(here: int, target: int) -> bytes:
    return u32(0xAA000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def cmp_imm(rn: int, imm: int) -> bytes:
    assert 0 <= imm <= 0xFF
    return u32(0xE3500000 | (rn << 16) | imm)


def orr_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE3800000 | (rn << 16) | (rd << 12) | encode_imm12(imm))


def bic_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE3C00000 | (rn << 16) | (rd << 12) | encode_imm12(imm))


def mov_lsl_reg(rd: int, rm: int, rs: int) -> bytes:
    """mov rd, rm, lsl rs"""
    return u32(0xE1A00010 | (rd << 12) | (rs << 8) | rm)


def bic_reg(rd: int, rn: int, rm: int) -> bytes:
    return u32(0xE1C00000 | (rn << 16) | (rd << 12) | rm)


def orr_reg(rd: int, rn: int, rm: int) -> bytes:
    return u32(0xE1800000 | (rn << 16) | (rd << 12) | rm)


def build_blob() -> tuple[bytes, dict[str, int]]:
    code = bytearray()
    labels: dict[str, int] = {}
    lit_vals: list[int] = []
    lit_fixups: list[tuple[int, int, int]] = []
    pending: list[tuple[int, str | None, str]] = []

    def here() -> int:
        return CAVE_ALIGN + len(code)

    def L(name: str) -> None:
        labels[name] = len(code)

    def emit(b: bytes) -> None:
        code.extend(b)

    def ldr_lit(rd: int, value: int) -> None:
        insn_off = len(code)
        emit(u32(0))
        lit_fixups.append((insn_off, len(lit_vals), rd))
        lit_vals.append(value)

    def B(label: str, kind: str = "b") -> None:
        pending.append((len(code), label, kind))
        emit(u32(0))

    def BL(target: int) -> None:
        emit(bl(here(), target))

    def BLX(target: int) -> None:
        emit(blx(here(), target))

    def emit_show_desc(get_desc: int, slot: int) -> None:
        BL(get_desc)
        emit(mov_reg(3, 0))
        ldr_lit(0, DAT_UI_MGR + 0x100000)
        emit(ldr_imm(0, 0, 0))
        emit(mov_imm(1, 0))
        emit(mov_imm(2, slot))
        emit(mov_imm(7, 0))
        emit(u32(0xE52D7004))  # push {r7} 5th arg
        BL(ADDR_SHOW)
        emit(u32(0xE28DD004))  # add sp, #4

    def emit_close_slot(slot: int) -> None:
        ldr_lit(0, DAT_UI_MGR + 0x100000)
        emit(ldr_imm(0, 0, 0))
        emit(mov_imm(1, 0))
        emit(mov_imm(2, slot))
        BL(ADDR_CLOSE)

    def emit_touch_overlay_on(name_rn: int) -> None:
        """OR bit 0x1E; BIC name slot bit; force slot+0x20=1."""
        ldr_lit(0, DAT_UI_MGR + 0x100000)
        emit(ldr_imm(0, 0, 0))
        emit(ldr_imm(1, 0, 0x100))
        emit(orr_imm(1, 1, SLOT_BIT))
        emit(ldrb_imm(2, name_rn, 8))
        emit(mov_imm(3, 1))
        emit(mov_lsl_reg(3, 3, 2))
        emit(bic_reg(1, 1, 3))
        emit(str_imm(1, 0, 0x100))
        # slot entry +0x20 at mgr+0x104+SLOT*0x28+0x20
        emit(add_imm(1, 0, 0x104))
        emit(mov_imm(2, SLOT))
        emit(add_reg(1, 1, 2, shift=5))  # +slot*32
        emit(add_reg(1, 1, 2, shift=3))  # +slot*8 (= *0x28)
        emit(add_imm(1, 1, 0x20))
        emit(mov_imm(2, 1))
        emit(strb_imm(2, 1, 0))

    def emit_touch_overlay_off(name_rn: int) -> None:
        """BIC bit 0x1E; OR name slot bit back."""
        ldr_lit(0, DAT_UI_MGR + 0x100000)
        emit(ldr_imm(0, 0, 0))
        emit(ldr_imm(1, 0, 0x100))
        emit(bic_imm(1, 1, SLOT_BIT))
        emit(ldrb_imm(2, name_rn, 8))
        emit(mov_imm(3, 1))
        emit(mov_lsl_reg(3, 3, 2))
        emit(orr_reg(1, 1, 3))
        emit(str_imm(1, 0, 0x100))

    def emit_soft_unlink(name_rn: int) -> None:
        """Drop slot 0x1E without UIWindowMgr_Close teardown (avoids ClearPane)."""
        emit_touch_overlay_off(name_rn)
        ldr_lit(0, DAT_UI_MGR + 0x100000)
        emit(ldr_imm(0, 0, 0))
        emit(add_imm(1, 0, 0x104))
        emit(mov_imm(2, SLOT))
        emit(add_reg(1, 1, 2, shift=5))
        emit(add_reg(1, 1, 2, shift=3))  # r1 = slot entry
        emit(mov_imm(2, 0))
        emit(strb_imm(2, 1, 0x20))
        emit(str_imm(2, 1, 0x0C))
        emit(str_imm(2, 1, 0x28))
        emit(ldr_imm(1, 0, 0x608))
        emit(cmp_imm(1, 0))
        B("sul_skip_dec", "beq")
        emit(sub_imm(1, 1, 1))
        emit(str_imm(1, 0, 0x608))
        L("sul_skip_dec")

    def emit_scene_detach() -> None:
        """FUN_005e8ca4(*(mgr+0x104), layout) — unlink from display, no pane destroy."""
        ldr_lit(0, DAT_UI_MGR + 0x100000)
        emit(ldr_imm(0, 0, 0))  # r0 = mgr
        emit(ldr_imm(3, 0, 0x104))  # r3 = parent container
        emit(add_imm(1, 0, 0x104))
        emit(mov_imm(2, SLOT))
        emit(add_reg(1, 1, 2, shift=5))
        emit(add_reg(1, 1, 2, shift=3))  # r1 = slot entry
        emit(ldr_imm(2, 1, 0x0C))  # r2 = layout
        emit(cmp_imm(2, 0))
        B("scd_skip", "beq")
        emit(cmp_imm(3, 0))
        B("scd_skip", "beq")
        emit(mov_reg(0, 3))
        emit(mov_reg(1, 2))
        BL(ADDR_SCENE_UNLINK)
        ldr_lit(0, DAT_UI_MGR + 0x100000)
        emit(ldr_imm(0, 0, 0))
        emit(add_imm(1, 0, 0x104))
        emit(mov_imm(2, SLOT))
        emit(add_reg(1, 1, 2, shift=5))
        emit(add_reg(1, 1, 2, shift=3))
        emit(mov_imm(2, 0))
        emit(strb_imm(2, 1, 0x20))  # inactive; keep layout/instance ptrs
        L("scd_skip")

    def emit_blank_rows(bp_rn: int) -> None:
        """ClearPane every Tex_BP pane + zero row strings. No Close/Redraw."""
        emit(mov_imm(7, 0))
        L("blk_loop")
        emit(cmp_imm(7, VISIBLE))
        B("blk_done", "bge")
        emit(add_reg(0, bp_rn, 7, shift=4))
        emit(add_imm(0, 0, 0xDC))
        emit(mov_imm(1, 0))
        emit(strb_imm(1, 0, 0))
        emit(add_reg(0, bp_rn, 7, shift=2))
        emit(ldr_imm(0, 0, 0x4C))
        emit(cmp_imm(0, 0))
        B("blk_next", "beq")
        BL(ADDR_CLEAR)
        L("blk_next")
        emit(add_imm(7, 7, 1))
        B("blk_loop", "b")
        L("blk_done")

    def emit_hide_root() -> None:
        """Hide Pos_Win_BP via BindByKey + pane vis bit clear (no ClearPane)."""
        emit(add_imm(0, 13, 0x20))
        BL(ADDR_DELEGATE_INIT)
        ldr_lit(0, DAT_UI_MGR + 0x100000)
        emit(ldr_imm(0, 0, 0))
        emit(mov_imm(1, 0))
        emit(mov_imm(2, SLOT))
        BL(ADDR_GET_LAYOUT)
        emit(cmp_imm(0, 0))
        B("hide_skip", "beq")
        ldr_lit(1, STR_POS_WIN_BP + 0x100000)
        emit(add_imm(2, 13, 0x20))
        emit(mov_imm(3, 0))
        BL(ADDR_BIND)
        emit(add_imm(0, 13, 0x20))
        emit(mov_imm(1, 0))
        BL(ADDR_PANE_SETVIS)
        L("hide_skip")

    # ----- enter: r0 = name-input -----
    L("enter")
    emit(push(0x4FF0))  # r4-r11, lr
    emit(mov_reg(4, 0))  # r4 = name
    emit(mov_reg(0, 4))
    BL(ADDR_FILL)
    emit_show_desc(ADDR_BP_GET, SLOT)
    ldr_lit(0, DAT_UI_MGR + 0x100000)
    emit(ldr_imm(0, 0, 0))
    emit(mov_imm(1, 0))
    emit(mov_imm(2, SLOT))
    BL(ADDR_GET_INST)
    emit(cmp_imm(0, 0))
    B("skip_fill", "beq")
    emit(mov_reg(1, 4))
    B("fill_rows", "bl_lab")
    L("after_fill")
    emit_touch_overlay_on(4)
    L("skip_fill")
    emit(mov_imm(0, 1))
    emit(strb_imm(0, 4, 0x44))
    emit(mov_imm(0, 0))
    emit(str_imm(0, 4, 0x38))
    emit(pop(0x8FF0))

    # ----- fill_rows: r0=bp, r1=name -----
    L("fill_rows")
    emit(push(0x4FF0))
    emit(sub_imm(13, 13, 0x40))
    emit(mov_reg(4, 0))
    emit(mov_reg(5, 1))
    emit(str_imm(5, 4, BP_NAME_STASH))  # bp+0x234 = name*
    emit(mov_imm(6, 0))
    emit(mov_imm(7, 0))
    L("fl_loop")
    emit(cmp_imm(7, VISIBLE))
    B("fl_clear", "bge")
    emit(cmp_imm(6, 0x3C))
    B("fl_clear", "bge")
    emit(add_reg(8, 5, 6, shift=4))  # &cell meta
    emit(ldrb_imm(0, 8, 0x184))
    emit(cmp_imm(0, 0))
    B("fl_next", "beq")
    emit(add_imm(0, 8, 0x180))
    emit(ldrh_imm(0, 0, 6))  # pack @ +0x186
    emit(add_imm(1, 8, 0x180))
    emit(ldrh_imm(1, 1, 8))  # slot @ +0x188
    emit(mov_imm(2, 0))
    BL(ADDR_LOOKUP)
    emit(cmp_imm(0, 0))
    B("fl_next", "beq")
    emit(mov_reg(9, 0))
    emit(add_reg(10, 4, 7, shift=4))
    emit(add_imm(10, 10, 0xDC))
    emit(mov_reg(0, 10))
    emit(mov_reg(1, 9))
    emit(mov_imm(2, 0x0F))
    BL(ADDR_MEMCPY7)
    emit(add_reg(0, 4, 7, shift=1))
    emit(add_imm(0, 0, 0xCC))
    emit(u32(0xE1C070B0))  # strh r7, [r0]
    emit(add_reg(0, 4, 7, shift=2))
    emit(ldr_imm(8, 0, 0x4C))
    emit(cmp_imm(8, 0))
    B("fl_row_ok", "beq")
    # ClearPane before DrawText — without it, hometown prefecture
    # placeholders (北芽道/青俄県/…) stay and look like “extra” kanji.
    emit(mov_reg(0, 8))
    BL(ADDR_CLEAR)
    emit(mov_reg(1, 10))
    emit(add_imm(0, 13, 0x18))
    BL(ADDR_MAKE_STR)
    emit(mov_reg(3, 0))
    emit(mov_reg(0, 8))
    emit(mov_imm(1, 0))
    emit(mov_imm(2, 0))
    emit(mov_imm(9, 0))
    emit(mov_imm(10, 0))
    emit(u32(0xE88D0600))  # stmia sp, {r9,r10} maxGlyphs=0
    BL(ADDR_DRAW)
    emit(add_imm(0, 13, 0x18))
    BL(ADDR_FREE_STR)
    L("fl_row_ok")
    emit(add_imm(7, 7, 1))
    L("fl_next")
    emit(add_imm(6, 6, 1))
    B("fl_loop", "b")
    L("fl_clear")
    emit(cmp_imm(7, VISIBLE))
    B("fl_ret", "bge")
    emit(add_reg(0, 4, 7, shift=4))
    emit(add_imm(0, 0, 0xDC))
    emit(mov_imm(1, 0))
    emit(strb_imm(1, 0, 0))
    emit(add_reg(0, 4, 7, shift=2))
    emit(ldr_imm(8, 0, 0x4C))
    emit(cmp_imm(8, 0))
    B("fl_cnext", "beq")
    emit(mov_reg(0, 8))
    BL(ADDR_CLEAR)
    L("fl_cnext")
    emit(add_imm(7, 7, 1))
    B("fl_clear", "b")
    L("fl_ret")
    emit(add_imm(13, 13, 0x40))
    emit(pop(0x8FF0))

    # ----- select_hook -----
    L("select_hook")
    emit(push(0x4FF0))
    emit(sub_imm(13, 13, 0x30))
    emit(mov_reg(4, 0))  # r4 = bp
    emit(mov_reg(5, 2))  # r5 = tapped pane name
    emit(ldr_imm(6, 4, BP_NAME_STASH))
    emit(cmp_imm(6, 0))
    B("sel_done", "beq")
    emit(mov_imm(7, 0))  # row
    L("sel_loop")
    emit(cmp_imm(7, VISIBLE))
    B("sel_done", "bge")
    emit(mov_reg(0, 13))
    emit(mov_imm(1, 0x20))
    ldr_lit(2, STR_BOD_BP + 0x100000)
    emit(add_imm(3, 7, 1))
    BLX(ADDR_SPRINTF)
    emit(mov_reg(0, 5))
    emit(mov_reg(1, 13))
    BL(ADDR_STRCMP)
    emit(cmp_imm(0, 0))
    B("sel_next", "bne")
    emit(add_reg(8, 4, 7, shift=4))
    emit(add_imm(8, 8, 0xDC))
    emit(ldrb_imm(0, 8, 0))
    emit(cmp_imm(0, 0))
    B("sel_done", "beq")
    emit(add_imm(0, 6, 0x46))
    emit(mov_reg(1, 8))
    emit(mov_imm(2, 0x0F))
    BL(ADDR_MEMCPY7)
    emit(mov_imm(0, 1))
    emit(strb_imm(0, 6, 0x45))
    emit(mov_imm(0, 0))
    emit(strb_imm(0, 6, 0x44))
    if DISMISS_MODE == 0:
        emit_touch_overlay_off(6)
    elif DISMISS_MODE == 1:
        emit_soft_unlink(6)
        emit(mov_reg(0, 6))
        BL(ADDR_GOJUON)
    elif DISMISS_MODE == 2:
        emit_close_slot(SLOT)
        emit_touch_overlay_off(6)
        emit(mov_reg(0, 6))
        BL(ADDR_GOJUON)
    elif DISMISS_MODE == 3:
        emit_scene_detach()
        emit_touch_overlay_off(6)
        emit(mov_imm(0, 0))
        emit(str_imm(0, 6, 0x38))
        emit(str_imm(0, 6, 0x3C))
        emit(mov_reg(0, 6))
        BL(ADDR_GOJUON)
    elif DISMISS_MODE == 4:
        emit_blank_rows(4)
        emit_touch_overlay_off(6)
    else:
        # Mode 5/6: visibility hide (path C milestone 1) — no ClearPane.
        emit_hide_root()
        emit_touch_overlay_off(6)
        if DISMISS_MODE >= 6:
            emit(mov_imm(0, 0))
            emit(str_imm(0, 6, 0x38))
            emit(str_imm(0, 6, 0x3C))
            emit(mov_reg(0, 6))
            BL(ADDR_GOJUON)
    B("sel_done", "b")
    L("sel_next")
    emit(add_imm(7, 7, 1))
    B("sel_loop", "b")
    L("sel_done")
    emit(mov_imm(0, 0))
    emit(add_imm(13, 13, 0x30))
    emit(pop(0x8FF0))

    for off, label, kind in pending:
        assert label is not None
        target = CAVE_ALIGN + labels[label]
        src = CAVE_ALIGN + off
        if kind == "b":
            struct.pack_into("<I", code, off, int.from_bytes(b(src, target), "little"))
        elif kind == "beq":
            struct.pack_into("<I", code, off, int.from_bytes(beq(src, target), "little"))
        elif kind == "bne":
            struct.pack_into("<I", code, off, int.from_bytes(bne(src, target), "little"))
        elif kind == "bge":
            struct.pack_into("<I", code, off, int.from_bytes(bge(src, target), "little"))
        elif kind == "bl_lab":
            struct.pack_into("<I", code, off, int.from_bytes(bl(src, target), "little"))
        else:
            raise ValueError(kind)

    pool_off = len(code)
    while pool_off & 3:
        code.append(0)
        pool_off = len(code)
    if pool_off + len(lit_vals) * 4 > CAVE_MAX:
        raise SystemExit(
            f"cave overflow: pool {pool_off + len(lit_vals)*4:#x} > {CAVE_MAX:#x}"
        )
    for insn_off, idx, rd in lit_fixups:
        lit_at = pool_off + idx * 4
        imm = lit_at - insn_off - 8
        assert 0 <= imm < 0x1000 and (imm & 3) == 0
        struct.pack_into("<I", code, insn_off, 0xE59F0000 | (rd << 12) | imm)
    for v in lit_vals:
        code.extend(u32(v))

    if len(code) > CAVE_MAX:
        raise SystemExit(f"code {len(code):#x} > cave {CAVE_MAX:#x}")

    blob = bytearray(b"\x00" * CAVE_MAX)
    blob[: len(code)] = code
    return bytes(blob), dict(labels)


def apply_patch(data: bytearray, vanilla: bytes) -> None:
    blob, labels = build_blob()
    enter = CAVE_ALIGN + labels["enter"]
    select = CAVE_ALIGN + labels["select_hook"]

    region = bytes(data[CAVE_ALIGN : CAVE_ALIGN + CAVE_MAX])
    if region != b"\x00" * CAVE_MAX:
        if region[:4] != bytes.fromhex("f04f2de9"):
            raise ValueError(
                f"bplace cave @{CAVE_ALIGN:#x} not empty "
                f"(first16={region[:16].hex()})"
            )

    # Leave LAB_SITE / §17 sites alone; only BL_SITE + our cave + vtable.
    data[CAVE_ALIGN : CAVE_ALIGN + CAVE_MAX] = blob
    data[BL_SITE : BL_SITE + 4] = bl(BL_SITE, enter)
    data[VT_BP_TOUCH : VT_BP_TOUCH + 4] = u32(0x100000 + select)

    print(
        f"[bplace-list] enter@{enter:#x} select@{select:#x} "
        f"slot={SLOT:#x} dismiss_mode={DISMISS_MODE} vtable+0x28 hooked"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    blob, labels = build_blob()
    print("labels", {k: hex(CAVE_ALIGN + v) for k, v in labels.items()})
    print(f"blob reserved {len(blob):#x}")
    if args.dry_run:
        return 0
    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")
    dest = (
        Path.home()
        / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    )
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")
    bak = dest.with_name(dest.name + ".bak_pre_bplace_list")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)
    van = (
        Path(__file__).resolve().parents[2]
        / "New Love Plus Plus/extracted/exefs/code.bin"
    ).read_bytes()
    data = bytearray(dest.read_bytes())
    if bytes(data[CAVE_ALIGN : CAVE_ALIGN + 4]) == bytes.fromhex("f04f2de9"):
        data[CAVE_ALIGN : CAVE_ALIGN + CAVE_MAX] = b"\x00" * CAVE_MAX
    apply_patch(data, van)
    dest.write_bytes(data)
    shutil.copy2(dest, dest.parent.parent / "code.bin")
    print(
        f"Fully quit Azahar. Mode {DISMISS_MODE}: insert only "
        "(list may stay; C1 hide crashed)."
    )
    print("Rollback: bak_pre_bplace_list -> code.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
