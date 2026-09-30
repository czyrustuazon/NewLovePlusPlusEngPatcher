"""Card field-row visibility is safe to apply twice (gold --skip-pack)."""

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
    chunks = [_pane(name, flags[name]) for name in sorted(card.SHOW_PANES)]
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


def test_show_field_row_sets_hidden_panes():
    layout = _clyt({name: 0 for name in card.SHOW_PANES})
    out = card.show_field_row(layout)
    assert len(out) == len(layout)
    assert _visible_names(out) == set(card.SHOW_PANES)


def test_show_field_row_is_idempotent_when_already_visible():
    layout = _clyt({name: 0x03 for name in card.SHOW_PANES})
    out = card.show_field_row(layout)
    assert out == layout
    again = card.show_field_row(out)
    assert again == layout


def test_show_field_row_still_errors_when_a_pane_is_absent():
    names = [name for name in sorted(card.SHOW_PANES) if name != "Vis_White_Base"]
    chunks = [_pane(name, 1) for name in names]
    payload = b"".join(chunks)
    header = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, 20, 0, 20 + len(payload), len(chunks))
    with pytest.raises(RuntimeError, match="Vis_White_Base"):
        card.show_field_row(header + payload)
