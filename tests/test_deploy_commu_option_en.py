"""Communication Settings hides the SpotPass row and DATA button."""

from __future__ import annotations

import struct

import pytest

from conftest import TOOLS, load_module

commu = load_module("deploy_commu_option_en", TOOLS / "deploy_commu_option_en.py")


def _pan1(name: str, visible: bool = True, y: float = 10.0) -> bytes:
    sec = bytearray(0x54)
    sec[0:4] = b"pan1"
    struct.pack_into("<I", sec, 4, len(sec))
    sec[8] = 1 if visible else 0
    sec[0x0C : 0x0C + len(name)] = name.encode("ascii")
    struct.pack_into("<3f", sec, 0x24, 5.0, y, 0.0)
    return bytes(sec)


def _layout(names) -> bytes:
    return b"CLYT" + bytes(12) + b"".join(_pan1(n) for n in names)


def _pane(lyt: bytes, name: str) -> tuple[int, float, float]:
    off = commu._find_pane(lyt, name)
    x, y = struct.unpack_from("<2f", lyt, off + 0x24)
    return lyt[off + 8] & 1, x, y


def test_spotpass_row_and_data_button_are_hidden_off_screen():
    names = ["Pos_Text02", "Pos_Text03", "Pos_Btn_Change01", "Pos_Btn_Change02", "Pos_Data_Btn"]
    src = _layout(names)
    out = commu.hide_spotpass_row(src)
    assert len(out) == len(src)
    for name in commu.HIDDEN_PANES:
        assert _pane(out, name) == (0, 5.0, commu.HIDDEN_Y)
    # StreetPass stays put.
    assert _pane(out, "Pos_Text02") == (1, 5.0, 10.0)
    assert _pane(out, "Pos_Btn_Change01") == (1, 5.0, 10.0)
    assert commu.hide_spotpass_row(out) == out


def test_hidden_panes_are_spotpass_label_button_and_data():
    assert commu.HIDDEN_PANES == ("Pos_Text03", "Pos_Btn_Change02", "Pos_Data_Btn")


def test_missing_pane_is_refused():
    with pytest.raises(SystemExit):
        commu.hide_spotpass_row(_layout(["Pos_Text02"]))
