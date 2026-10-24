"""SysPopup scroll constants follow the tall Tex_Sentence pane."""

from __future__ import annotations

import faulthandler
import struct
import sys

import pytest

from conftest import ROOT, SRC, load_module

tall = load_module("patch_syspopup_tall_text", SRC / "patch_syspopup_tall_text.py")


def _image() -> bytearray:
    data = bytearray(tall.ADDR_PROGRESS_MODE4 + 0x40)
    for addr, vanilla in tall._VANILLA.items():
        data[addr : addr + len(vanilla)] = vanilla
    return data


def test_apply_once():
    data = _image()
    assert tall.apply_patch(data) is True and tall.is_patched(data)
    assert tall.apply_patch(data) is False


def test_slice_and_on_screen_height_match_vanilla():
    data = _image()
    tall.apply_patch(data)
    v = struct.unpack_from("<f", data, tall.ADDR_V_PER_PIXEL)[0]
    k = struct.unpack_from("<f", data, tall.ADDR_SCALE_PER_PIXEL)[0]
    win = 112.0
    assert win * v * tall.TEXT_H == pytest.approx(win)  # same texel rows as vanilla
    assert tall.TEXT_H * win * k == pytest.approx(256 * win / 255)


def test_refuses_unexpected_pool():
    data = _image()
    data[tall.ADDR_V_PER_PIXEL] ^= 1
    with pytest.raises(ValueError, match="SysPopup"):
        tall.apply_patch(data)


def _run_mode(code: bytes) -> dict[str, int]:
    """Run a mode 3/4 block on unicorn; return the pic's +0x181 / +0x2c and r2/r3."""
    unicorn = pytest.importorskip("unicorn")
    from unicorn.arm_const import UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R6

    base, pic = 0x10000, 0x20000
    uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    # unicorn's first mem_map raises and catches an access violation on
    # Windows; faulthandler would dump it (see test_call_romaji_match.py).
    was_on = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        uc.mem_map(base, 0x1000)
        uc.mem_map(pic, 0x1000)
    finally:
        if was_on:
            faulthandler.enable(file=sys.__stderr__)
    uc.mem_write(base, code)
    uc.mem_write(pic + 0x181, b"\x01")
    uc.reg_write(UC_ARM_REG_R6, pic)
    uc.reg_write(UC_ARM_REG_R3, 0x55)
    uc.emu_start(base, base + len(code))
    return {
        "flag": uc.mem_read(pic + 0x181, 1)[0],
        "y": struct.unpack("<f", bytes(uc.mem_read(pic + 0x2C, 4)))[0],
        "r2": uc.reg_read(UC_ARM_REG_R2),
        "r3": uc.reg_read(UC_ARM_REG_R3),
    }


@pytest.mark.parametrize("addr,r2", [("ADDR_PROGRESS_MODE3", 8), ("ADDR_PROGRESS_MODE4", 4)])
def test_progress_box_text_top_stays_under_the_header(addr, r2):
    # Blank "Creating extra data" box (Oct 2026): the pane's top edge must stay
    # where vanilla's 256-tall pane had it, -67 + 128.
    out = _run_mode(tall._PATCHED[getattr(tall, addr)])
    assert out == {"flag": 0, "y": tall.TOP_TEXT_Y, "r2": r2, "r3": 0}
    assert out["y"] + tall.TEXT_H / 2 == -67 + 256 / 2


def test_upgrades_a_code_bin_with_only_the_scroll_pool():
    data = _image()
    for addr in (tall.ADDR_V_PER_PIXEL, tall.ADDR_SCALE_PER_PIXEL):
        data[addr : addr + 4] = tall._PATCHED[addr]
    assert not tall.is_patched(data)
    assert tall.apply_patch(data) is True and tall.is_patched(data)


def test_matches_the_layout_height():
    sys.path.insert(0, str(ROOT / "tools"))
    ui = load_module("deploy_ui_buttons_en", ROOT / "tools" / "deploy_ui_buttons_en.py")
    assert ui.SENTENCE_H == tall.TEXT_H
