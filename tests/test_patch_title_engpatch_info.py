"""Main Menu Eng Patch badge tap opens an INFORMATION box with one OK."""

from __future__ import annotations

import struct

import pytest

from conftest import SRC, load_module

info = load_module("patch_title_engpatch_info", SRC / "patch_title_engpatch_info.py")
rst = load_module("patch_camera_defaults_reset", SRC / "patch_camera_defaults_reset.py")


def _words(blob: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(blob) // 4}I", blob[: len(blob) // 4 * 4]))


def _targets(blob: bytes, base: int) -> list[int]:
    out = []
    for i, w in enumerate(_words(blob)):
        if (w >> 28) != 0xF and (w & 0x0E000000) == 0x0A000000:
            imm = w & 0xFFFFFF
            if imm & 0x800000:
                imm -= 0x1000000
            out.append(base + 4 * i + 8 + imm * 4)
    return out


def test_caves_fit_their_dead_bodies():
    region_a, region_b, entries = info.build_regions()
    assert len(region_a) == info.CAVE_A_END - info.CAVE_A_START
    assert len(region_b) == info.CAVE_B_END - info.CAVE_B_START
    assert entries["tap"] == info.CAVE_A_START < entries["enter"] < info.CAVE_A_END
    assert info.CAVE_B_START <= entries["guard"] < info.CAVE_B_END


def test_camera_cave_ends_where_this_one_starts():
    blob, _press, _poll = rst.build_cave()
    assert rst.CAVE_START + len(blob) <= rst.CAVE_END == info.CAVE_A_START


def test_tap_replays_the_load_and_passes_a_chosen_row_through():
    blob_a, _blob_b, _e = info.build_caves()
    words = _words(blob_a)
    assert words[0] == 0xE5950070  # ldr r0, [r5, #0x70]
    assert words[1] == 0xE3700001  # cmn r0, #1
    assert words[2] == 0x112FFF1E  # bxne lr
    assert info.HID_TOUCH_PTR in words and info.CELL in words


def test_boxes_are_information_with_one_ok_from_slot_502():
    _a, blob_b, _e = info.build_caves()
    words = _words(blob_b)
    assert 0xE3A00000 | info.DIALOG_STYLE_INFORMATION in words  # style 2 = INFORMATION
    assert 0xE3A01000 | info.DIALOG_LAYOUT in words
    assert 0xE2806000 | info.DIALOG_MODE in words  # add r6, page, #mode
    assert 0xE3500000 | len(info.CREDIT_PAGES) in words  # cmp page, #pages
    assert 0xE3A03001 in words  # OK only
    assert info.MSG_SLOT == 502 == rst.MSG_SLOT + 1
    targets = _targets(blob_b, info.CAVE_B_START)
    assert info.ADDR_OPEN_DIALOG in targets
    assert info.ADDR_DIALOG_CLOSED in targets
    assert info.HUB_TOUCH_DOWN in targets  # guard falls through to the vanilla handler


def test_badge_rects_follow_the_layout():
    # Pic_EngPatch: 218x26 centred at y=17 under Nul_Copyright.
    lx0, lx1, ly0, ly1 = -109, 109, 4, 30
    pos = {info.ANGLE_H: (0, -95), info.ANGLE_VR: (-152, 0), info.ANGLE_VL: (152, 0)}

    def rotate(x, y, angle):
        return {0: (x, y), -90: (y, -x), 90: (-y, x)}[angle]

    for angle, rect in zip((info.ANGLE_H, info.ANGLE_VR, info.ANGLE_VL), info.BADGE_RECTS):
        px, py = pos[angle]
        corners = [rotate(x, y, angle) for x in (lx0, lx1) for y in (ly0, ly1)]
        xs = [160 + px + x for x, _ in corners]
        ys = [120 - (py + y) for _, y in corners]
        assert rect == (min(xs) - 2, max(xs) + 2, min(ys) - 2, max(ys) + 2)
        assert 0 <= rect[0] < rect[1] < 320 and 0 <= rect[2] < rect[3] < 240


def test_apply_refuses_without_the_stubs():
    data = bytearray(info.HUB_TOUCH_SLOT + 0x10)
    with pytest.raises(ValueError, match="spotpass"):
        info.apply_patch(data)
    data[rst.ADDR_STUB : rst.ADDR_STUB + 4] = rst.STUB_PATCHED
    with pytest.raises(ValueError, match="eula"):
        info.apply_patch(data)


def test_append_info_message_needs_the_camera_slot_first():
    from patch_password_serials import _sub_u16_off
    from patch_textresource import parse_chunks
    from test_patch_camera_defaults_reset import _fake_trb

    src = _fake_trb([3, rst.MSG_VANILLA_SLOTS, 2])
    with pytest.raises(ValueError, match="expected 502"):
        info.append_info_message(src)
    cam, _ = rst.append_confirm_message(src)
    out, logs = info.append_info_message(cam)
    ch = parse_chunks(out)
    u16, count = _sub_u16_off(ch["INDX"], rst.MSG_CAT, rst.MSG_SUB)
    assert count == info.MSG_SLOT + len(info.CREDIT_PAGES) and "slot 502" in logs[0]
    for page, text in enumerate(info.CREDIT_PAGES):
        idx = struct.unpack_from("<H", ch["INDX"], u16 + 2 * (info.MSG_SLOT + page))[0]
        start, length, _flag = struct.unpack_from("<IHH", ch["STRI"], idx * 8)
        assert ch["STRB"][start : start + length].decode() == text
    again, logs = info.append_info_message(out)
    assert again == out and all("already" in line for line in logs)


def test_credit_lines_fit_the_box_width():
    pages = info.CREDIT_PAGES
    for n, page in enumerate(pages, 1):
        lines = page.split("\n")
        title = "Localization Credits" + ("" if len(pages) == 1 else f" ({n}/{len(pages)})")
        assert lines[0] == title
        assert max(map(info._width, lines)) <= info.LINE_WIDTH
        if info.PAGE_LINES:
            assert len(lines) <= info.PAGE_LINES
        assert len(lines) <= info.MAX_BOX_LINES  # DrawTextToPane line table


def test_each_role_line_is_followed_by_its_names():
    text = "\n".join(info.CREDIT_PAGES)
    for role, names in info.CREDITS:
        if names is None:
            continue
        assert role + "\n" + info.BULLET + names[0] in text
    if info.BULLET:
        assert text.count(info.BULLET) == sum(1 for _r, n in info.CREDITS if n)
    assert "\n-" not in text and "\n " not in text
