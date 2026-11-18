"""Card field rows stay hidden as in vanilla, and hiding is safe to apply twice."""

from __future__ import annotations

import struct

import pytest

from conftest import TOOLS, load_module

card = load_module("deploy_card_name_labels_en", TOOLS / "deploy_card_name_labels_en.py")


def _pane(name: str, flag: int) -> bytes:
    body = bytearray(64)
    body[0:4] = b"pan1"
    struct.pack_into("<I", body, 4, 64)
    body[8] = flag
    raw = name.encode("ascii")
    body[12 : 12 + len(raw)] = raw
    return bytes(body)


def _clyt(flags: dict[str, int]) -> bytes:
    chunks = [_pane(name, flags[name]) for name in sorted(card.ROW_PANES)]
    payload = b"".join(chunks)
    header = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, 20, 0, 20 + len(payload), len(chunks))
    return header + payload


def _visible_names(layout: bytes) -> set[str]:
    data = layout
    _magic, _bom, header_size, _rev, _file_size, section_count = struct.unpack_from(
        "<4sHHIII", data, 0
    )
    off = header_size
    shown = set()
    for _ in range(section_count):
        size = struct.unpack_from("<I", data, off + 4)[0]
        name = bytes(data[off + 12 : off + 36]).split(b"\x00", 1)[0].decode("ascii")
        if data[off + 8] & 1:
            shown.add(name)
        off += size
    return shown


def test_hide_field_row_clears_visible_panes():
    layout = _clyt({name: 0x03 for name in card.ROW_PANES})
    out = card.hide_field_row(layout)
    assert len(out) == len(layout)
    assert _visible_names(out) == set()


def test_hide_field_row_is_idempotent_on_vanilla_flags():
    layout = _clyt({name: 0x02 for name in card.ROW_PANES})
    out = card.hide_field_row(layout)
    assert out == layout
    assert card.hide_field_row(out) == layout


def test_hide_field_row_still_errors_when_a_pane_is_absent():
    names = [name for name in sorted(card.ROW_PANES) if name != "Vis_White_Base"]
    chunks = [_pane(name, 1) for name in names]
    payload = b"".join(chunks)
    header = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, 20, 0, 20 + len(payload), len(chunks))
    with pytest.raises(RuntimeError, match="Vis_White_Base"):
        card.hide_field_row(header + payload)
