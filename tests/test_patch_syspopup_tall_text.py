"""SysPopup scroll constants follow the tall Tex_Sentence pane."""

from __future__ import annotations

import struct
import sys

import pytest

from conftest import ROOT, SRC, load_module

tall = load_module("patch_syspopup_tall_text", SRC / "patch_syspopup_tall_text.py")


def _image() -> bytearray:
    data = bytearray(tall.ADDR_SCALE_PER_PIXEL + 4)
    struct.pack_into("<f", data, tall.ADDR_V_PER_PIXEL, 1 / 256)
    struct.pack_into("<f", data, tall.ADDR_SCALE_PER_PIXEL, 1 / 255)
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


def test_matches_the_layout_height():
    sys.path.insert(0, str(ROOT / "tools"))
    ui = load_module("deploy_ui_buttons_en", ROOT / "tools" / "deploy_ui_buttons_en.py")
    assert ui.SENTENCE_H == tall.TEXT_H
