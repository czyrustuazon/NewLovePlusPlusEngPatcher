"""Forecast day names are S M T W Th F Sa, not the shared kanji glosses."""

from __future__ import annotations

import struct
import sys

import pytest

from conftest import ROOT, SRC, TOOLS

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from nlpp_paths import find_vanilla_main_trb
from patch_password_serials import _sub_u16_off
from patch_textresource import LOOKUP_PATH, dump_entries, load_lookup, parse_chunks
from patch_weather_weekdays import WEEKDAY_CAT, WEEKDAY_LABELS, WEEKDAY_SUB, apply_weather_weekdays

VANILLA = find_vanilla_main_trb() or (
    ROOT.parent
    / "New Love Plus Plus"
    / "extracted"
    / "romfs"
    / "SystemData"
    / "TextResource"
    / "textresource_jpn.trb"
)


def _slot_stri(indx: bytes, slot: int) -> int:
    u16, _count = _sub_u16_off(indx, WEEKDAY_CAT, WEEKDAY_SUB)
    return struct.unpack_from("<H", indx, u16 + slot * 2)[0]


@pytest.mark.local_data
@pytest.mark.skipif(not VANILLA.is_file(), reason="vanilla TRB not in sibling dump")
def test_weekday_slots_become_short_labels_and_shared_kanji_stay():
    lookup = load_lookup(LOOKUP_PATH)
    vanilla = VANILLA.read_bytes()
    before = dump_entries(vanilla, lookup)
    patched, logs = apply_weather_weekdays(vanilla)
    assert patched != vanilla
    assert any("-> S " in line for line in logs)

    chunks = parse_chunks(patched)
    entries = dump_entries(patched, lookup)
    old_slots = []
    for slot, label in enumerate(WEEKDAY_LABELS):
        old = _slot_stri(parse_chunks(vanilla)["INDX"], slot)
        old_slots.append(old)
        idx = _slot_stri(chunks["INDX"], slot)
        assert idx != old
        assert entries[idx]["text"] == label
        assert entries[idx]["flag"] == 1
        assert before[old]["text"] == entries[old]["text"]

    # Parenthesized （日）… stay on their original rows.
    for slot in range(7, 14):
        assert _slot_stri(chunks["INDX"], slot) == _slot_stri(parse_chunks(vanilla)["INDX"], slot)

    again, logs2 = apply_weather_weekdays(patched)
    assert again == patched
    assert all("already" in line for line in logs2)


def test_name_kanji_rebuild_hooks_weekday_labels():
    text = (TOOLS / "deploy_name_kanji_trb.py").read_text(encoding="utf-8")
    assert "apply_weather_weekdays" in text
