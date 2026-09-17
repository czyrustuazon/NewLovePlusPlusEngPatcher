"""TRB NLP codebook decode + hometown prefecture translations."""

from __future__ import annotations

import patch_textresource as trb
from conftest import ROOT


def test_nlp_payload_keeps_interior_nul_lo_byte():
    """梨 is codebook index 1536 (0x600) → bytes 86 00; 00 is not EOS."""
    lookup = trb.load_lookup(trb.LOOKUP_PATH)
    assert lookup[1535] == "梨"
    # 山 (0xE9) + 梨 (0x600) + 県 + terminator
    strb = bytes.fromhex("80e98600819700")
    text, raw = trb.decode_entry(strb, 0, 0, lookup)
    assert raw == bytes.fromhex("80e986008197")
    assert text == "山梨県"


def test_nlp_payload_still_stops_at_real_terminator():
    lookup = trb.load_lookup(trb.LOOKUP_PATH)
    strb = bytes.fromhex("80e98343819700ffff")
    text, raw = trb.decode_entry(strb, 0, 0, lookup)
    assert raw == bytes.fromhex("80e983438197")
    assert text == "山形県"


def test_yamanashi_keys_are_full_prefecture_strings():
    mapping = trb.load_translations(trb.DEFAULT_TRANSLATIONS)
    assert mapping.get("山") != "Yamanashi"
    assert mapping["山梨県"] == "Yamanashi"
    assert mapping["山梨県民と名刺交換"] == (
        "Exchange business cards with Yamanashi residents"
    )
    assert mapping["アイ・ラブ・山梨！"] == "I love Yamanashi!"
    assert "アイ・ラブ・山" not in mapping


def test_vanilla_prefecture_220_is_yamanashi():
    if not trb.DEFAULT_TRB.is_file():
        import pytest

        pytest.skip("vanilla textresource_jpn.trb not found")
    lookup = trb.load_lookup(trb.LOOKUP_PATH)
    entries = {e["idx"]: e for e in trb.dump_entries(trb.DEFAULT_TRB.read_bytes(), lookup)}
    assert entries[219]["text"] == "福井県"
    assert entries[220]["text"] == "山梨県"
    assert entries[221]["text"] == "長野県"
    assert "梨" in entries[2914]["text"]
    assert "梨" in entries[3078]["text"]
