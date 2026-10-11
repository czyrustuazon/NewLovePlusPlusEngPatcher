"""TRB NLP codebook decode + hometown prefecture translations."""

from __future__ import annotations

import pytest

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


def test_translation_values_keep_japanese_control_tokens():
    """English words inside ▲ ▲ are not lookup keys, except live surname markers.

    Family slots are Takane, Anegasaki, and Kobayaka, so those marker
    values follow the slots.
    """
    from patch_names import CONTROL_TOKEN_RESTORES

    mapping = trb.load_translations(trb.DEFAULT_TRANSLATIONS)
    for placeholder in CONTROL_TOKEN_RESTORES:
        assert all(placeholder not in value for value in mapping.values())
    assert mapping["▲名前▲"] == "▲名前▲"
    assert mapping["▲苗字▲"] == "▲苗字▲"
    assert mapping["▲主人公＊▲"] == "▲主人公＊▲"
    assert mapping["▲姉ヶ崎＊▲"] == "▲Anegasaki＊▲"
    assert mapping["▲小早川＊▲"] == "▲Kobayaka＊▲"
    assert mapping["▲彼女＊＊▲"] == "▲彼女＊＊▲"
    assert mapping["▲高嶺＊＊▲"] == "▲Takane＊＊▲"


def test_restore_control_tokens_in_trb_rewrites_only_placeholders():
    import struct

    lookup = trb.load_lookup(trb.LOOKUP_PATH)

    def chunk(name: str, body: bytes) -> bytes:
        return name.encode("ascii") + struct.pack("<I", len(body)) + body

    rows = ["Hello ▲Protagonist＊▲", "▲彼女＊＊▲", "plain"]
    strb = bytearray()
    stri = bytearray()
    for text in rows:
        payload = text.encode("utf-8")
        stri += struct.pack("<IHH", len(strb), len(payload), 1)
        strb += payload + b"\x00"
    pad = (4 - (len(strb) % 4)) % 4
    strb += b"\xc9" * pad
    data = chunk("STRI", bytes(stri)) + chunk("STRB", bytes(strb))

    out, stats = trb.restore_control_tokens_in_trb(data, lookup)
    assert stats["restored"] == 1
    assert stats["kept"] == 2
    entries = trb.dump_entries(out, lookup)
    assert entries[0]["text"] == "Hello ▲主人公＊▲"
    assert entries[1]["text"] == "▲彼女＊＊▲"
    assert entries[2]["text"] == "plain"


def test_rewrite_rinko_marker_keeps_the_following_slot():
    import struct

    lookup = trb.load_lookup(trb.LOOKUP_PATH)

    def chunk(name: str, body: bytes) -> bytes:
        return name.encode("ascii") + struct.pack("<I", len(body)) + body

    marker = "▲小早川＊▲".encode("utf-8")
    stay = "▲高嶺＊＊▲".encode("utf-8")
    strb = bytearray()
    stri = bytearray()
    stri += struct.pack("<IHH", len(strb), len(marker), 1)
    strb += marker + b"\x00" + b"\xab"
    stri += struct.pack("<IHH", len(strb), len(stay), 1)
    strb += stay + b"\x00"
    pad = (4 - (len(strb) % 4)) % 4
    strb += b"\xc9" * pad
    data = chunk("STRI", bytes(stri)) + chunk("STRB", bytes(strb))

    out, count = trb.rewrite_rinko_marker_in_trb(data, lookup)
    assert count == 1
    assert len(out) == len(data)
    entries = trb.dump_entries(out, lookup)
    assert entries[0]["text"] == "▲Kobayaka＊▲"
    assert entries[0]["flag"] == 1
    assert entries[0]["bytelength"] == len("▲Kobayaka＊▲".encode("utf-8"))
    assert entries[1]["text"] == "▲高嶺＊＊▲"
    again, count2 = trb.rewrite_rinko_marker_in_trb(out, lookup)
    assert count2 == 0
    assert again == out
    chunks = trb.parse_chunks(out)
    # Gap byte between the shortened marker and the next string stays.
    assert chunks["STRB"][19] == 0xAB


def test_rewrite_manaka_marker_keeps_the_following_slot():
    import struct

    lookup = trb.load_lookup(trb.LOOKUP_PATH)

    def chunk(name: str, body: bytes) -> bytes:
        return name.encode("ascii") + struct.pack("<I", len(body)) + body

    marker = "▲高嶺＊＊▲".encode("utf-8")
    stay = "▲Kobayaka＊▲".encode("utf-8")
    strb = bytearray()
    stri = bytearray()
    stri += struct.pack("<IHH", len(strb), len(marker), 1)
    strb += marker + b"\x00" + b"\xab"
    stri += struct.pack("<IHH", len(strb), len(stay), 1)
    strb += stay + b"\x00"
    pad = (4 - (len(strb) % 4)) % 4
    strb += b"\xc9" * pad
    data = chunk("STRI", bytes(stri)) + chunk("STRB", bytes(strb))

    out, count = trb.rewrite_manaka_marker_in_trb(data, lookup)
    assert count == 1
    assert len(out) == len(data)
    entries = trb.dump_entries(out, lookup)
    assert entries[0]["text"] == "▲Takane＊＊▲"
    assert entries[0]["bytelength"] == len("▲Takane＊＊▲".encode("utf-8"))
    assert entries[1]["text"] == "▲Kobayaka＊▲"
    again, count2 = trb.rewrite_manaka_marker_in_trb(out, lookup)
    assert count2 == 0
    assert again == out
    assert trb.parse_chunks(out)["STRB"][19] == 0xAB


@pytest.mark.local_data
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
