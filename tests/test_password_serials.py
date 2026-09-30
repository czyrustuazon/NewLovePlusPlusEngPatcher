"""Shared serial password holes → unique pack 0xb000 codes."""

from __future__ import annotations

import struct
import sys

import pytest

from conftest import ROOT, SRC, TOOLS

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from patch_password_serials import (
    PASSWORD_CAT,
    SHARED_SERIALS,
    apply_shared_serial_passwords,
)
from patch_textresource import LOOKUP_PATH, dump_entries, load_lookup, parse_chunks

VANILLA = (
    ROOT.parent
    / "New Love Plus Plus"
    / "extracted"
    / "romfs"
    / "SystemData"
    / "TextResource"
    / "textresource_jpn.trb"
)


def _slot_stri(indx: bytes, slot: int) -> int:
    cat_off = struct.unpack_from("<I", indx, PASSWORD_CAT * 4)[0]
    rel = struct.unpack_from("<I", indx, cat_off + 4)[0]
    sub_off = cat_off + rel
    return struct.unpack_from("<H", indx, sub_off + 4 + slot * 2)[0]


@pytest.mark.skipif(not VANILLA.is_file(), reason="vanilla TRB not in sibling dump")
def test_apply_fills_nashi_holes_and_is_idempotent():
    lookup = load_lookup(LOOKUP_PATH)
    vanilla = VANILLA.read_bytes()
    patched, logs = apply_shared_serial_passwords(vanilla)
    assert patched != vanilla
    assert any("JuhanoManaka" in line for line in logs)

    chunks = parse_chunks(patched)
    entries = dump_entries(patched, lookup)
    for slot, code, _label in SHARED_SERIALS:
        idx = _slot_stri(chunks["INDX"], slot)
        assert entries[idx]["text"] == code
        assert entries[idx]["flag"] == 1

    again, logs2 = apply_shared_serial_passwords(patched)
    assert again == patched
    assert all("already" in line for line in logs2)


def test_deploy_name_kanji_hooks_serial_passwords():
    text = (TOOLS / "deploy_name_kanji_trb.py").read_text(encoding="utf-8")
    assert "apply_shared_serial_passwords" in text
    assert (SRC / "patch_password_serials.py").is_file()
