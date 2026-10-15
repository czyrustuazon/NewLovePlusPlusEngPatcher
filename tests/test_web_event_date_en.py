"""Web event-card date is MM/DD, back in the original pane."""

from __future__ import annotations

import struct

from conftest import TOOLS, load_module

date = load_module("deploy_web_event_date_en", TOOLS / "deploy_web_event_date_en.py")


def _clyt(x: float, width: float) -> bytes:
    sec = bytearray(128)
    sec[0:4] = b"pic1"
    struct.pack_into("<I", sec, 4, 128)
    sec[12:24] = b"Pic_Txt_Date"
    struct.pack_into("<f", sec, 8 + 28, x)
    struct.pack_into("<f", sec, 8 + 60, width)
    header = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, 20, 0, 0, 1)
    header += b"\x00" * (20 - len(header))
    blob = header + bytes(sec)
    return blob[:0x0C] + struct.pack("<I", len(blob)) + blob[0x10:]


def test_widened_pane_returns_to_vanilla():
    raw = _clyt(date.WIDE_X, date.WIDE_W)
    patched, changed = date.patch_date_layout(raw)
    assert changed
    assert len(patched) == len(raw)
    assert struct.unpack_from("<f", patched, 20 + 8 + 28)[0] == date.VANILLA_X
    assert struct.unpack_from("<f", patched, 20 + 8 + 60)[0] == date.VANILLA_W
    again, changed2 = date.patch_date_layout(patched)
    assert changed2 is False
    assert again == patched


def test_vanilla_pane_stays_put():
    raw = _clyt(date.VANILLA_X, date.VANILLA_W)
    patched, changed = date.patch_date_layout(raw)
    assert changed is False
    assert patched == raw


def test_label_is_slash_then_update():
    im = date.paint_date_label()
    assert im.size == (date.TEX_W, date.TEX_H)
    px = im.load()
    ink = [
        x
        for x in range(im.width)
        if any(px[x, y][3] > 128 for y in range(im.height))
    ]
    slash = [x for x in ink if x < 20]
    word = [x for x in ink if x >= 20]
    assert slash and word
    # Slash sits between the month pair and the day pair.
    assert max(slash) - min(slash) < 12
    assert min(slash) > 2
    assert max(slash) < 20
    # Update starts after the day digits and stops short of the right edge.
    assert min(word) >= 26
    assert max(word) <= date.TEX_W - 2
    assert min(word) - max(slash) >= 6
